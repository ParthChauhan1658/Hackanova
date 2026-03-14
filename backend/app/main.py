"""
SENTINEL — FastAPI application entry point.
Run with:  uvicorn app.main:app --reload
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

# Load .env before anything reads os.getenv()
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent.parent / ".env", override=False)
except ImportError:
    pass

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import audit as audit_router
from app.api.routes import doctors as doctors_router
from app.api.routes import settings as settings_router
from app.api.routes import simulator as simulator_router
from app.api.routes import vitals as vitals_router
from app.core.redis_client import RedisClient
from app.db.audit_repository import AuditRepository
from app.db.database import AsyncSessionLocal, create_tables
from app.ml.isolation_forest import IsolationForestWrapper
from app.services.appointment_service import AppointmentService
from app.services.ems_service import EMSService
from app.services.escalation_engine import EscalationEngine
from app.services.fall_protocol import FallProtocol
from app.services.gemini_client import GeminiClient
from app.services.llm_client import LLMClient
from app.services.notification_service import NotificationService
from app.services.pipeline import VitalsPipeline
from app.services.rule_fallback import RuleFallback
from app.services.scoring_engine import ScoringEngine
from app.services.signal_processor import SignalProcessor
from app.services.simulator import DataSimulator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──────────────────────────────────────────────────────────────

    # Redis
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    redis = RedisClient(url=redis_url)
    await redis.connect()

    # Signal processing + simulator
    signal_processor = SignalProcessor(redis_client=redis)
    simulator        = DataSimulator(redis_client=redis)

    # Isolation Forest — load model (warn but do not crash if pkl missing)
    # Default path is resolved relative to this file so it works regardless of CWD
    _default_if_path = str(Path(__file__).parent / "ml" / "sentinel_if.pkl")
    if_model_path = os.getenv("IF_MODEL_PATH", _default_if_path)
    if_model = IsolationForestWrapper(model_path=if_model_path)
    if_model.load()

    # Scoring engine
    scoring_engine = ScoringEngine(redis_client=redis, if_model=if_model)

    # LLM Reasoning Engine
    rule_fallback  = RuleFallback()
    gemini_client  = GeminiClient(api_key=os.getenv("GEMINI_API_KEY"))
    llm_client     = LLMClient(
        redis_client=redis,
        gemini_client=gemini_client,
        rule_fallback=rule_fallback,
    )

    # PostgreSQL + audit repository
    try:
        await create_tables()
        logger.info("Database tables verified / created")
    except Exception as exc:
        logger.warning("Database unavailable at startup: %s — audit logging disabled", exc)

    audit_repo = AuditRepository(session_factory=AsyncSessionLocal)

    # Escalation services
    notification_svc = NotificationService()
    ems_svc          = EMSService()
    appointment_svc  = AppointmentService()

    fall_protocol = FallProtocol(
        redis_client=redis,
        ems_service=ems_svc,
        notification_service=notification_svc,
    )

    escalation_engine = EscalationEngine(
        redis_client=redis,
        notification_service=notification_svc,
        ems_service=ems_svc,
        appointment_service=appointment_svc,
        fall_protocol=fall_protocol,
        audit_repo=audit_repo,
        rule_fallback=rule_fallback,
    )

    # Assemble pipeline
    pipeline = VitalsPipeline(
        signal_processor=signal_processor,
        redis_client=redis,
        scoring_engine=scoring_engine,
        llm_client=llm_client,
        escalation_engine=escalation_engine,
    )

    # Expose on app.state
    app.state.redis_client      = redis
    app.state.signal_processor  = signal_processor
    app.state.simulator         = simulator
    app.state.scoring_engine    = scoring_engine
    app.state.if_model          = if_model
    app.state.pipeline          = pipeline
    app.state.llm_client        = llm_client
    app.state.escalation_engine = escalation_engine
    app.state.fall_protocol     = fall_protocol
    app.state.audit_repo        = audit_repo

    # ── Auto-start CSV simulation ─────────────────────────────────────────────
    # Resolves CSV_DATA_DIR (from .env) and starts streaming dataset.csv through
    # the full pipeline automatically — no frontend trigger needed.
    _default_data_dir = Path(__file__).parent.parent.parent / "data"
    _csv_dir  = Path(os.getenv("CSV_DATA_DIR", str(_default_data_dir))).resolve()
    _csv_path = _csv_dir / "dataset.csv"
    if _csv_path.exists():
        try:
            await simulator.start(
                patient_id="P01",
                csv_path=str(_csv_path),
                on_reading=pipeline.process,
                interval_seconds=float(os.getenv("SIMULATE_INTERVAL", "0.5")),
                loop=True,
            )
            logger.info(
                "Auto-simulation started — %s | patient=P01 | interval=%.1fs",
                _csv_path, float(os.getenv("SIMULATE_INTERVAL", "0.5")),
            )
        except Exception as _exc:
            logger.warning("Auto-simulation could not start: %s", _exc)
    else:
        logger.warning("Auto-simulation skipped — CSV not found at %s", _csv_path)

    logger.info("SENTINEL backend started — Redis: %s", redis_url)
    yield

    # ── Shutdown ─────────────────────────────────────────────────────────────
    for patient_id in simulator.active_patients():
        await simulator.stop(patient_id)
    await redis.disconnect()
    logger.info("SENTINEL backend stopped")


app = FastAPI(
    title="SENTINEL — Clinical Escalation Agent",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],       # dev mode — restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(vitals_router.router)
app.include_router(simulator_router.router)
app.include_router(audit_router.router)
app.include_router(settings_router.router)
app.include_router(doctors_router.router)


@app.get("/health")
async def health(request: Request):
    redis = request.app.state.redis_client
    try:
        client = await redis.get_client()
        await client.ping()
        redis_status = "connected"
    except Exception:
        redis_status = "disconnected"

    if_model = request.app.state.if_model

    return {
        "status":           "ok",
        "redis":            redis_status,
        "isolation_forest": "loaded" if if_model.is_loaded else "not_loaded",
        "claude_api":       "configured" if os.getenv("ANTHROPIC_API_KEY") else "missing_key",
        "gemini_api":       "configured" if os.getenv("GEMINI_API_KEY") else "missing_key",
        "database":         "configured" if os.getenv("DATABASE_URL") else "default_url",
        "twilio":           "configured" if os.getenv("TWILIO_ACCOUNT_SID") else "missing_key",
        "sendgrid":         "configured" if os.getenv("RESEND_API_KEY") else "missing_key",
        "calendly":         "configured" if os.getenv("CALENDLY_API_TOKEN") else "missing_key",
        "serp_api":         "configured" if os.getenv("SERP_API_KEY") else "osm_only",
        "ems":              "mock" if not os.getenv("EMS_API_URL") else "configured",
    }

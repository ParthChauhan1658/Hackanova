"""
SENTINEL E2E test suite conftest.
All fixtures use *internal* VitalReading field names (not CSV column names).
Field mapping reference:
  heart_rate_bpm      → heart_rate
  spo2_percent        → spo2
  temperature_celsius → body_temperature
  hrv_rmssd_ms        → hrv_ms
  sleep_efficiency_pct→ sleep_efficiency
  signal_quality_pct  → signal_quality
  activity_level      → activity_context
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime

import pytest

try:
    from dotenv import load_dotenv
    from pathlib import Path
    load_dotenv(Path(__file__).parent.parent.parent / ".env", override=False)
except ImportError:
    pass


# ── Service availability checks ───────────────────────────────────────────────

def _check_fastapi(base: str) -> bool:
    try:
        import httpx
        r = httpx.get(f"{base}/health", timeout=5.0)
        return r.status_code == 200
    except Exception:
        return False


def _redis_url() -> str:
    return os.getenv("REDIS_URL", "redis://localhost:6379/0")


def _check_redis() -> bool:
    try:
        import redis as _redis
        c = _redis.from_url(_redis_url(), decode_responses=True, socket_connect_timeout=5)
        c.ping()
        c.close()
        return True
    except Exception:
        return False


def _check_postgres() -> bool:
    try:
        import psycopg2
        dsn = _sync_db_url()
        conn = psycopg2.connect(dsn, connect_timeout=5)
        conn.close()
        return True
    except Exception:
        return False


def _sync_db_url() -> str:
    raw = os.getenv(
        "DATABASE_URL_SYNC",
        os.getenv("DATABASE_URL", "postgresql://postgres:netrika2026@localhost:5432/netrika"),
    )
    # Strip asyncpg driver prefix — psycopg2 uses plain postgresql://
    raw = raw.replace("postgresql+asyncpg://", "postgresql://")
    # asyncpg uses ssl=require; psycopg2 uses sslmode=require
    raw = raw.replace("ssl=require", "sslmode=require")
    return raw


# ── Session-scoped service check fixtures ────────────────────────────────────

@pytest.fixture(scope="session", autouse=True)
def require_fastapi():
    if not _check_fastapi("http://localhost:8000"):
        pytest.skip(
            "FastAPI not running on port 8000 — start with: "
            "cd backend && uvicorn app.main:app --reload"
        )


@pytest.fixture(scope="session", autouse=True)
def require_redis():
    if not _check_redis():
        pytest.skip(
            "Redis not running — start with: docker-compose up redis -d"
        )


@pytest.fixture(scope="session", autouse=True)
def require_postgres():
    if not _check_postgres():
        pytest.skip(
            "PostgreSQL not reachable — start with: docker-compose up postgres -d"
        )


# ── Basic fixtures ────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def base_url() -> str:
    return "http://localhost:8000"


@pytest.fixture(scope="session")
def ws_url() -> str:
    return "ws://localhost:8000"


@pytest.fixture(scope="session")
def redis_client():
    import redis as _redis
    client = _redis.from_url(_redis_url(), decode_responses=True)
    yield client
    client.close()


@pytest.fixture(scope="session")
def db_session():
    import psycopg2
    conn = psycopg2.connect(_sync_db_url())
    conn.autocommit = True
    yield conn
    conn.close()


@pytest.fixture
def http_client():
    import httpx
    with httpx.Client(timeout=60.0) as client:
        yield client


# ── Reading fixtures (use INTERNAL VitalReading field names) ──────────────────

@pytest.fixture
def silent_sepsis_reading() -> dict:
    """
    Centrepiece demo reading.
    HR=108, RR=22, SpO2=93%, Temp=38.4°C, HRV=32ms
    Expected: CRITICAL band, SIRS bonus fires, score >= 60.
    Standard monitor would show ALL GREEN.
    """
    return {
        "reading_id":         f"test_sepsis_{uuid.uuid4().hex[:8]}",
        "patient_id":         "test_patient_sepsis",
        "session_id":         "session_sepsis_001",
        "timestamp":          datetime.utcnow().isoformat() + "Z",
        "heart_rate":         108.0,
        "respiratory_rate":   22.0,
        "spo2":               93.0,
        "ecg_rhythm":         "NORMAL",
        "ecg_st_deviation_mm": 0.1,
        "ecg_qtc_ms":         420.0,
        "body_temperature":   38.4,
        "sleep_efficiency":   72.0,
        "deep_sleep_pct":     18.0,
        "rem_pct":            22.0,
        "hrv_ms":             32.0,
        "stress_score":       68.0,
        "fall_event":         "NONE",
        "steps_per_hour":     0.0,
        "activity_context":   "RESTING",
        "age":                45,
        "gender":             "M",
        "weight_kg":          78.0,
        "has_chronic_condition": False,
        "latitude":           19.0760,
        "longitude":          72.8777,
        "location_stale":     False,
        "source":             "test",
        "signal_quality":     94.0,
    }


@pytest.fixture
def normal_reading() -> dict:
    """Healthy patient. Expected: NOMINAL band, score < 30."""
    return {
        "reading_id":         f"test_normal_{uuid.uuid4().hex[:8]}",
        "patient_id":         "test_patient_normal",
        "session_id":         "session_normal_001",
        "timestamp":          datetime.utcnow().isoformat() + "Z",
        "heart_rate":         72.0,
        "respiratory_rate":   15.0,
        "spo2":               98.0,
        "ecg_rhythm":         "NORMAL",
        "ecg_st_deviation_mm": 0.0,
        "ecg_qtc_ms":         410.0,
        "body_temperature":   37.0,
        "sleep_efficiency":   80.0,
        "deep_sleep_pct":     20.0,
        "rem_pct":            25.0,
        "hrv_ms":             58.0,
        "stress_score":       22.0,
        "fall_event":         "NONE",
        "steps_per_hour":     500.0,
        "activity_context":   "RESTING",
        "age":                35,
        "gender":             "F",
        "weight_kg":          65.0,
        "has_chronic_condition": False,
        "latitude":           19.0760,
        "longitude":          72.8777,
        "location_stale":     False,
        "source":             "test",
        "signal_quality":     96.0,
    }


@pytest.fixture
def exercise_reading() -> dict:
    """
    High HR but VIGOROUS activity.
    Expected: activity suppressor fires, score stays low, NO escalation.
    """
    return {
        "reading_id":         f"test_exercise_{uuid.uuid4().hex[:8]}",
        "patient_id":         "test_patient_exercise",
        "session_id":         "session_exercise_001",
        "timestamp":          datetime.utcnow().isoformat() + "Z",
        "heart_rate":         138.0,
        "respiratory_rate":   24.0,
        "spo2":               97.0,
        "ecg_rhythm":         "NORMAL",
        "ecg_st_deviation_mm": 0.0,
        "ecg_qtc_ms":         390.0,
        "body_temperature":   37.3,
        "sleep_efficiency":   78.0,
        "deep_sleep_pct":     19.0,
        "rem_pct":            23.0,
        "hrv_ms":             38.0,
        "stress_score":       45.0,
        "fall_event":         "NONE",
        "steps_per_hour":     5200.0,
        "activity_context":   "VIGOROUS",
        "age":                28,
        "gender":             "M",
        "weight_kg":          72.0,
        "has_chronic_condition": False,
        "latitude":           19.0760,
        "longitude":          72.8777,
        "location_stale":     False,
        "source":             "test",
        "signal_quality":     91.0,
    }


@pytest.fixture
def hard_override_reading() -> dict:
    """
    SpO2=83% — triggers SPO2_CRITICAL hard override.
    Expected: score = 100, CRITICAL band.
    """
    return {
        "reading_id":         f"test_override_{uuid.uuid4().hex[:8]}",
        "patient_id":         "test_patient_override",
        "session_id":         "session_override_001",
        "timestamp":          datetime.utcnow().isoformat() + "Z",
        "heart_rate":         95.0,
        "respiratory_rate":   18.0,
        "spo2":               83.0,
        "ecg_rhythm":         "NORMAL",
        "ecg_st_deviation_mm": 0.0,
        "ecg_qtc_ms":         415.0,
        "body_temperature":   37.1,
        "sleep_efficiency":   75.0,
        "deep_sleep_pct":     17.0,
        "rem_pct":            21.0,
        "hrv_ms":             48.0,
        "stress_score":       35.0,
        "fall_event":         "NONE",
        "steps_per_hour":     0.0,
        "activity_context":   "RESTING",
        "age":                62,
        "gender":             "M",
        "weight_kg":          85.0,
        "has_chronic_condition": True,
        "latitude":           19.0760,
        "longitude":          72.8777,
        "location_stale":     False,
        "source":             "test",
        "signal_quality":     89.0,
    }


@pytest.fixture
def fall_reading() -> dict:
    """
    CONFIRMED_FALL with zero motion.
    Expected: fall protocol triggers, FALL_UNRESPONSIVE override.
    """
    return {
        "reading_id":         f"test_fall_{uuid.uuid4().hex[:8]}",
        "patient_id":         "test_patient_fall",
        "session_id":         "session_fall_001",
        "timestamp":          datetime.utcnow().isoformat() + "Z",
        "heart_rate":         98.0,
        "respiratory_rate":   17.0,
        "spo2":               95.0,
        "ecg_rhythm":         "NORMAL",
        "ecg_st_deviation_mm": 0.0,
        "ecg_qtc_ms":         420.0,
        "body_temperature":   37.2,
        "sleep_efficiency":   74.0,
        "deep_sleep_pct":     16.0,
        "rem_pct":            20.0,
        "hrv_ms":             50.0,
        "stress_score":       30.0,
        "fall_event":         "CONFIRMED_FALL",
        "steps_per_hour":     0.0,
        "activity_context":   "RESTING",
        "age":                75,
        "gender":             "F",
        "weight_kg":          60.0,
        "has_chronic_condition": True,
        "latitude":           19.0760,
        "longitude":          72.8777,
        "location_stale":     False,
        "source":             "test",
        "signal_quality":     88.0,
    }


@pytest.fixture
def low_signal_reading() -> dict:
    """
    Signal quality 12% — below threshold (20%).
    Expected: all vitals treated as unreliable, low_signal_quality flag set.
    """
    return {
        "reading_id":         f"test_lowsig_{uuid.uuid4().hex[:8]}",
        "patient_id":         "test_patient_lowsig",
        "session_id":         "session_lowsig_001",
        "timestamp":          datetime.utcnow().isoformat() + "Z",
        "heart_rate":         249.0,
        "respiratory_rate":   59.0,
        "spo2":               51.0,
        "ecg_rhythm":         "VF",
        "ecg_st_deviation_mm": 4.0,
        "ecg_qtc_ms":         650.0,
        "body_temperature":   42.9,
        "sleep_efficiency":   50.0,
        "deep_sleep_pct":     10.0,
        "rem_pct":            15.0,
        "hrv_ms":             6.0,
        "stress_score":       99.0,
        "fall_event":         "CONFIRMED_FALL",
        "steps_per_hour":     0.0,
        "activity_context":   "RESTING",
        "age":                40,
        "gender":             "M",
        "weight_kg":          75.0,
        "has_chronic_condition": False,
        "latitude":           19.0760,
        "longitude":          72.8777,
        "location_stale":     False,
        "source":             "test",
        "signal_quality":     12.0,
    }


# ── Session-scoped Redis cleanup ──────────────────────────────────────────────

@pytest.fixture(scope="session", autouse=True)
def cleanup_redis_after_session(redis_client):
    yield
    test_patients = [
        "test_patient_sepsis",
        "test_patient_normal",
        "test_patient_exercise",
        "test_patient_override",
        "test_patient_fall",
        "test_patient_lowsig",
        "test_patient_simulator",
        "test_patient_ws",
        "test_patient_load",
        "test_patient_hold",
        "concurrent_patient_1",
        "concurrent_patient_2",
        "concurrent_patient_3",
    ]
    deleted = 0
    for patient_id in test_patients:
        keys = redis_client.keys(f"*{patient_id}*")
        if keys:
            redis_client.delete(*keys)
            deleted += len(keys)
    print(f"\nCleaned up {deleted} Redis keys for {len(test_patients)} test patients")

"""
VitalsPipeline — orchestrator that wires SignalProcessor, Redis pub/sub,
and optional downstream stubs (scoring engine, LLM client, escalation engine).
"""

from __future__ import annotations

import logging

from app.core.redis_client import RedisClient
from app.models.vitals import ProcessedReading, VitalReading
from app.services.signal_processor import SignalProcessor

logger = logging.getLogger(__name__)


class VitalsPipeline:
    """
    Dependency-injected pipeline.  scoring_engine, llm_client and
    escalation_engine are optional stubs injected at startup — all accept
    duck-typed objects.
    """

    def __init__(
        self,
        signal_processor: SignalProcessor,
        redis_client: RedisClient,
        scoring_engine=None,       # .score(ProcessedReading) -> RiskAssessment
        llm_client=None,           # .reason(ProcessedReading, RiskAssessment) -> LLMReasoning
        escalation_engine=None,    # .escalate(ProcessedReading, RiskAssessment, LLMReasoning) -> EscalationResult
    ) -> None:
        self.signal_processor  = signal_processor
        self.redis             = redis_client
        self.scoring_engine    = scoring_engine
        self.llm_client        = llm_client
        self.escalation_engine = escalation_engine

    async def process(self, reading: VitalReading) -> ProcessedReading:
        # Step 1 — Signal processing
        processed = await self.signal_processor.process(reading)

        # Step 1b — Cache latest raw reading for frontend polling (30 s TTL)
        try:
            import json as _json
            rc = await self.redis.get_client()
            await rc.setex(
                f"sentinel:vitals:{reading.patient_id}:latest",
                30,
                _json.dumps(reading.model_dump(mode="json"), default=str),
            )
        except Exception as _exc:
            logger.debug("Failed to cache latest reading: %s", _exc)

        # Step 2 — Publish processed reading to vitals channel
        await self.redis.publish_event(
            f"vitals:processed:{reading.patient_id}",
            processed.model_dump(mode="json"),
        )

        # Step 3 — Publish hard-override alert if triggered
        if processed.hard_override is not None:
            await self.redis.publish_event(
                f"actions:{reading.patient_id}",
                {
                    "event_type": "HARD_OVERRIDE_DETECTED",
                    "patient_id": reading.patient_id,
                    "reading_id": reading.reading_id,
                    "override":   processed.hard_override.model_dump(),
                },
            )

        # Step 4 — Scoring engine (stub — skipped if not injected)
        assessment = None
        if self.scoring_engine is not None:
            try:
                assessment = await self.scoring_engine.score(processed)
            except Exception as exc:
                logger.error("Scoring engine error for %s: %s", reading.patient_id, exc)

        # Step 5 — LLM client (only for HIGH / CRITICAL bands)
        reasoning = None
        if self.llm_client is not None and assessment is not None:
            try:
                from app.models.assessment import SHALBand
                if assessment.shal_band in (SHALBand.HIGH, SHALBand.CRITICAL):
                    reasoning = await self.llm_client.reason(processed, assessment)
            except Exception as exc:
                logger.error("LLM client error for %s: %s", reading.patient_id, exc)

        # Step 6 — Escalation engine (HIGH/CRITICAL bands + fall events)
        if self.escalation_engine is not None and assessment is not None:
            try:
                from app.models.assessment import SHALBand
                from app.models.vitals import FallEvent
                should_escalate = (
                    assessment.shal_band in (SHALBand.HIGH, SHALBand.CRITICAL)
                    or reading.fall_event in (FallEvent.POSSIBLE_FALL, FallEvent.CONFIRMED_FALL)
                )
                if should_escalate:
                    await self.escalation_engine.escalate(
                        processed, assessment, reasoning
                    )
            except Exception as exc:
                logger.error(
                    "Escalation engine error for %s: %s", reading.patient_id, exc
                )

        return processed

"""
EMSService — Emergency Medical Services dispatch.
Uses httpx REST calls with exponential backoff retry.
Voice call fallback via Twilio if all HTTP attempts fail.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Optional

import httpx

from app.core.constants import (
    EMS_API_URL_ENV,
    EMS_MAX_RETRIES,
    EMS_MOCK_URL,
    EMS_RETRY_BACKOFF_SECONDS,
    EMS_TIMEOUT_SECONDS,
    TWILIO_ACCOUNT_SID_ENV,
    TWILIO_API_BASE,
    TWILIO_AUTH_TOKEN_ENV,
    TWILIO_CALLS_ENDPOINT,
    TWILIO_FROM_NUMBER_ENV,
)
from app.models.assessment import RiskAssessment
from app.models.escalation import ActionResult, ActionStatus
from app.models.reasoning import LLMReasoning
from app.models.vitals import ProcessedReading

logger = logging.getLogger(__name__)


class EMSService:
    """Dispatches emergency medical services via REST API with retry + voice fallback."""

    def __init__(
        self,
        api_url: Optional[str] = None,
        timeout_seconds: float = EMS_TIMEOUT_SECONDS,
        max_retries: int = EMS_MAX_RETRIES,
    ) -> None:
        self._api_url = api_url or os.getenv(EMS_API_URL_ENV, EMS_MOCK_URL)
        self._timeout = timeout_seconds
        self._max_retries = max_retries

    async def dispatch(
        self,
        processed: ProcessedReading,
        assessment: RiskAssessment,
        reasoning: LLMReasoning,
    ) -> ActionResult:
        """
        Dispatch EMS with retry logic.
        Falls back to Twilio voice call if all HTTP attempts fail.
        """
        start = time.monotonic()

        # Mock path — no real EMS URL configured
        is_mock = self._api_url == EMS_MOCK_URL or not self._api_url
        if is_mock:
            logger.info(
                "EMS mock dispatch — set %s for real dispatch (patient %s)",
                EMS_API_URL_ENV,
                processed.original.patient_id,
            )
            return ActionResult(
                action_type="EMS",
                status=ActionStatus.SUCCESS,
                latency_ms=(time.monotonic() - start) * 1000,
                detail="EMS mock dispatched",
                retry_count=0,
            )

        orig = processed.original
        ho = processed.hard_override
        incident_type = (
            "FALL_AND_UNRESPONSIVE"
            if assessment.hard_override_type == "FALL_UNRESPONSIVE"
            else "MEDICAL_EMERGENCY"
        )

        payload = {
            "incident_type": incident_type,
            "patient_id": orig.patient_id,
            "timestamp": orig.timestamp.isoformat(),
            "location": {
                "latitude": orig.latitude,
                "longitude": orig.longitude,
                "location_stale": orig.location_stale,
            },
            "vitals_snapshot": processed.validated_vitals,
            "risk_score": assessment.final_score,
            "shal_band": assessment.shal_band.value,
            "hard_override_type": assessment.hard_override_type,
            "reasoning_summary": reasoning.reasoning_summary,
            "differential_diagnoses": [
                d.model_dump() for d in reasoning.differential_diagnoses
            ],
            "syndromes_fired": assessment.sl3.syndromes_fired,
        }

        last_exc: Optional[Exception] = None
        for attempt in range(self._max_retries):
            backoff = EMS_RETRY_BACKOFF_SECONDS[attempt] if attempt < len(EMS_RETRY_BACKOFF_SECONDS) else 4
            if backoff > 0:
                await asyncio.sleep(backoff)
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.post(self._api_url, json=payload)
                    response.raise_for_status()
                    latency = (time.monotonic() - start) * 1000
                    logger.info(
                        "ACTION EMS → SUCCESS in %.0fms (attempt %d)",
                        latency, attempt + 1,
                    )
                    return ActionResult(
                        action_type="EMS",
                        status=ActionStatus.SUCCESS,
                        latency_ms=latency,
                        detail=f"HTTP {response.status_code}",
                        retry_count=attempt,
                    )
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "EMS attempt %d/%d failed: %s", attempt + 1, self._max_retries, exc
                )

        # All attempts failed — trigger voice call fallback
        logger.error(
            "EMS API failed after %d attempts — voice call fallback triggered",
            self._max_retries,
        )
        await self._voice_call_fallback(processed)
        latency = (time.monotonic() - start) * 1000
        return ActionResult(
            action_type="EMS",
            status=ActionStatus.FAILED,
            latency_ms=latency,
            detail=f"All {self._max_retries} attempts failed. Voice fallback triggered. Last: {last_exc}",
            retry_count=self._max_retries,
        )

    async def _voice_call_fallback(self, processed: ProcessedReading) -> None:
        """Place a Twilio voice call to the first emergency contact."""
        sid   = os.getenv(TWILIO_ACCOUNT_SID_ENV, "")
        token = os.getenv(TWILIO_AUTH_TOKEN_ENV, "")
        from_ = os.getenv(TWILIO_FROM_NUMBER_ENV, "")
        to_   = os.getenv("EMERGENCY_CONTACT_NUMBERS", "").split(",")
        to_   = [n.strip() for n in to_ if n.strip()]

        if not all([sid, token, from_]) or not to_:
            logger.warning("Voice call fallback: Twilio not configured — skipping")
            return

        pid   = processed.original.patient_id
        score = 0  # score not available here without assessment
        twiml = (
            f"<Response><Say>SENTINEL emergency alert for patient {pid}. "
            f"Immediate response required.</Say></Response>"
        )
        url = f"{TWILIO_API_BASE}/{sid}{TWILIO_CALLS_ENDPOINT}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(
                    url,
                    data={
                        "To": to_[0],
                        "From": from_,
                        "Twiml": twiml,
                    },
                    auth=(sid, token),
                )
            logger.info("EMS voice call fallback placed to %s", to_[0])
        except Exception as exc:
            logger.error("Voice call fallback failed: %s", exc)

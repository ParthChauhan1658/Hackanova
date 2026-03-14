"""
AppointmentService — Cal.com v2 REST booking.
Used for HIGH-band escalations to schedule an urgent clinical review.
No SDK — httpx REST only.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from app.core.constants import (
    CAL_COM_API_BASE,
    CAL_COM_API_KEY_ENV,
    CAL_COM_EVENT_TYPE_ID_ENV,
)
from app.models.assessment import RiskAssessment
from app.models.escalation import ActionResult, ActionStatus
from app.models.reasoning import LLMReasoning
from app.models.vitals import ProcessedReading

logger = logging.getLogger(__name__)

_CAL_API_VERSION = "2024-08-13"


class AppointmentService:
    """Books urgent clinical review appointments via Cal.com REST API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        event_type_id: Optional[int] = None,
    ) -> None:
        self._api_key = api_key or os.getenv(CAL_COM_API_KEY_ENV, "")
        raw_id = event_type_id or os.getenv(CAL_COM_EVENT_TYPE_ID_ENV, "")
        try:
            self._event_type_id = int(raw_id) if raw_id else None
        except (ValueError, TypeError):
            self._event_type_id = None

    async def book_urgent_appointment(
        self,
        processed: ProcessedReading,
        assessment: RiskAssessment,
        reasoning: LLMReasoning,
    ) -> ActionResult:
        """Book an urgent clinical review for a HIGH-band patient via Cal.com."""
        start = time.monotonic()

        if not self._api_key:
            logger.warning("Cal.com API key not configured — appointment skipped")
            return ActionResult(
                action_type="APPOINTMENT",
                status=ActionStatus.SKIPPED,
                latency_ms=0,
                detail="Cal.com API key not configured",
            )

        if not self._event_type_id:
            logger.warning("Cal.com event type ID not configured — appointment skipped")
            return ActionResult(
                action_type="APPOINTMENT",
                status=ActionStatus.SKIPPED,
                latency_ms=0,
                detail="Cal.com event type ID not configured",
            )

        pid = processed.original.patient_id
        # Book 30 minutes from now — urgent same-day review
        slot_start = datetime.now(timezone.utc) + timedelta(minutes=30)

        top_syndrome = (
            assessment.sl3.syndromes_fired[0]
            if assessment.sl3.syndromes_fired
            else (assessment.hard_override_type or "High-risk pattern")
        )

        payload = {
            "eventTypeId": self._event_type_id,
            "start": slot_start.isoformat(),
            "responses": {
                "name": f"Patient {pid}",
                "email": f"patient-{pid}@sentinel.local",
                "notes": (
                    f"SENTINEL HIGH alert — Score {assessment.final_score}/100\n"
                    f"Primary concern: {top_syndrome}\n"
                    f"Summary: {reasoning.reasoning_summary[:200]}"
                ),
            },
            "metadata": {
                "sentinel_patient_id": pid,
                "sentinel_shal_band": assessment.shal_band.value,
                "sentinel_score": str(assessment.final_score),
            },
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{CAL_COM_API_BASE}/bookings",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "cal-api-version": _CAL_API_VERSION,
                        "Content-Type": "application/json",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            latency = (time.monotonic() - start) * 1000
            logger.warning("ACTION APPOINTMENT → FAILED in %.0fms: %s", latency, exc)
            return ActionResult(
                action_type="APPOINTMENT",
                status=ActionStatus.FAILED,
                latency_ms=latency,
                detail=str(exc),
            )

        latency = (time.monotonic() - start) * 1000
        booking_data = data.get("data", data)
        booking_uid = str(
            booking_data.get("uid") or booking_data.get("id") or "unknown"
        )

        logger.info(
            "ACTION APPOINTMENT → SUCCESS in %.0fms — booking %s",
            latency,
            booking_uid,
        )
        return ActionResult(
            action_type="APPOINTMENT",
            status=ActionStatus.SUCCESS,
            latency_ms=latency,
            detail=booking_uid,
        )

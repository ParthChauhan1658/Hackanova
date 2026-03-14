"""
AppointmentService — Calendly scheduling-link booking.
Used for HIGH-band escalations to schedule an urgent clinical review.
Creates a single-use Calendly scheduling link and returns it as the booking detail.
No SDK — httpx REST only.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Optional
from urllib.parse import quote

import httpx

from app.core.constants import (
    CALENDLY_API_BASE,
    CALENDLY_API_TOKEN_ENV,
    CALENDLY_EVENT_TYPE_URI_ENV,
)
from app.models.assessment import RiskAssessment
from app.models.escalation import ActionResult, ActionStatus
from app.models.reasoning import LLMReasoning
from app.models.vitals import ProcessedReading

logger = logging.getLogger(__name__)


class AppointmentService:
    """Creates Calendly scheduling links for urgent clinical review appointments."""

    def __init__(
        self,
        api_token: Optional[str] = None,
        event_type_uri: Optional[str] = None,
    ) -> None:
        self._api_token     = api_token or os.getenv(CALENDLY_API_TOKEN_ENV, "")
        self._event_type_uri = event_type_uri or os.getenv(CALENDLY_EVENT_TYPE_URI_ENV, "")

    async def book_urgent_appointment(
        self,
        processed: ProcessedReading,
        assessment: RiskAssessment,
        reasoning: LLMReasoning,
    ) -> ActionResult:
        """Create a Calendly scheduling link for a HIGH-band patient."""
        start = time.monotonic()

        if not self._api_token:
            logger.warning("Calendly API token not configured — appointment skipped")
            return ActionResult(
                action_type="APPOINTMENT",
                status=ActionStatus.SKIPPED,
                latency_ms=0,
                detail="Calendly API token not configured",
            )

        if not self._event_type_uri:
            logger.warning("Calendly event type URI not configured — appointment skipped")
            return ActionResult(
                action_type="APPOINTMENT",
                status=ActionStatus.SKIPPED,
                latency_ms=0,
                detail="Calendly event type URI not configured (set CALENDLY_EVENT_TYPE_URI in .env)",
            )

        pid = processed.original.patient_id
        top_syndrome = (
            assessment.sl3.syndromes_fired[0]
            if assessment.sl3.syndromes_fired
            else (assessment.hard_override_type or "High-risk pattern")
        )

        patient_name  = f"Patient {pid}"
        patient_email = f"patient-{pid}@sentinel.local"
        reason        = f"SENTINEL HIGH alert — Score {assessment.final_score:.0f}/100 | {top_syndrome}"

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{CALENDLY_API_BASE}/scheduling_links",
                    json={
                        "max_event_count": 1,
                        "owner":      self._event_type_uri,
                        "owner_type": "EventType",
                    },
                    headers={
                        "Authorization": f"Bearer {self._api_token}",
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

        booking_url = data["resource"]["booking_url"]
        # Pre-fill patient details in the Calendly page
        booking_url += f"?name={quote(patient_name)}&email={quote(patient_email)}"
        booking_url += f"&a1={quote(reason[:200])}"

        logger.info(
            "ACTION APPOINTMENT → SUCCESS in %.0fms — Calendly link: %s",
            latency,
            booking_url,
        )
        return ActionResult(
            action_type="APPOINTMENT",
            status=ActionStatus.SUCCESS,
            latency_ms=latency,
            detail=booking_url,
        )

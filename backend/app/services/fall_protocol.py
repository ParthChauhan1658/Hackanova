"""
FallProtocol — two-stage fall detection state machine.

Stage 1  POSSIBLE_FALL detected → monitor for 30 s (configurable) → false
          positive if motion, or upgrade to CONFIRMED_FALL.
Stage 2  CONFIRMED_FALL → 60 s acknowledgement countdown (configurable) →
          EMS dispatch if nobody acknowledges.

All timing constants are configurable via constructor for testing.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from app.core.constants import (
    EMERGENCY_DISPATCHED_EVENT,
    FALL_ACKNOWLEDGED_KEY,
    FALL_ACKNOWLEDGED_TTL_SECONDS,
    FALL_CONFIRMED_AT_KEY,
    FALL_COUNTDOWN_SECONDS,
    FALL_MONITORING_WINDOW_SECONDS,
    FALL_POLL_INTERVAL_SECONDS,
    FALL_POSSIBLE_AT_KEY,
    FALL_STATE_KEY,
)
from app.core.redis_client import RedisClient
from app.models.assessment import RiskAssessment
from app.models.escalation import ActionResult, ActionStatus
from app.models.reasoning import LLMReasoning
from app.models.vitals import ProcessedReading

if TYPE_CHECKING:
    from app.services.ems_service import EMSService
    from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)


class FallProtocol:
    """
    Manages the two-stage fall detection and EMS-dispatch state machine.
    Timing intervals are constructor-injectable for test speed-up.
    """

    def __init__(
        self,
        redis_client: RedisClient,
        ems_service: "EMSService",
        notification_service: "NotificationService",
        monitoring_window: float = FALL_MONITORING_WINDOW_SECONDS,
        countdown_seconds: float = FALL_COUNTDOWN_SECONDS,
        poll_interval: float = FALL_POLL_INTERVAL_SECONDS,
    ) -> None:
        self.redis             = redis_client
        self.ems               = ems_service
        self.notifications     = notification_service
        self._monitoring_window = monitoring_window
        self._countdown        = countdown_seconds
        self._poll             = poll_interval

    # ── Public entry ──────────────────────────────────────────────────────────

    async def handle(
        self,
        processed: ProcessedReading,
        assessment: RiskAssessment,
        reasoning: LLMReasoning,
    ) -> list[ActionResult]:
        """
        Called by EscalationEngine on POSSIBLE_FALL or CONFIRMED_FALL events.
        Returns list of ActionResults for the audit log.
        """
        pid = processed.original.patient_id
        actions: list[ActionResult] = []

        # ── Stage 1 — Motion monitoring window ────────────────────────────────
        logger.info(
            "FALL stage 1 — patient %s: monitoring %.0fs for motion",
            pid,
            self._monitoring_window,
        )

        rc = await self.redis.get_client()
        await rc.set(FALL_STATE_KEY.format(patient_id=pid), "POSSIBLE_FALL")
        await rc.set(FALL_POSSIBLE_AT_KEY.format(patient_id=pid), str(time.time()))

        await self.redis.publish_event(
            f"actions:{pid}",
            {
                "event": "POSSIBLE_FALL_DETECTED",
                "patient_id": pid,
                "reading_id": processed.original.reading_id,
            },
        )

        fall_confirmed = await self._monitor_for_motion(pid)

        if not fall_confirmed:
            # Motion detected — false positive
            logger.info(
                "FALL stage 1 — patient %s: motion detected → FALSE POSITIVE", pid
            )
            await rc.delete(FALL_STATE_KEY.format(patient_id=pid))
            await rc.delete(FALL_POSSIBLE_AT_KEY.format(patient_id=pid))
            await self.redis.publish_event(
                f"actions:{pid}",
                {"event": "FALL_FALSE_POSITIVE", "patient_id": pid},
            )
            actions.append(
                ActionResult(
                    action_type="FALL",
                    status=ActionStatus.SKIPPED,
                    latency_ms=0,
                    detail="Fall false positive — motion detected during monitoring window",
                )
            )
            return actions

        # ── Stage 2 — Confirmation + acknowledgement countdown ─────────────────
        logger.info(
            "FALL stage 2 — patient %s: CONFIRMED. Countdown %.0fs",
            pid,
            self._countdown,
        )

        await rc.set(FALL_STATE_KEY.format(patient_id=pid), "CONFIRMED_FALL")
        await rc.set(FALL_CONFIRMED_AT_KEY.format(patient_id=pid), str(time.time()))

        # Notify carers immediately
        sms_result = await self.notifications.send_critical_sms(
            processed, assessment, reasoning
        )
        fcm_result = await self.notifications.send_fcm_push(processed, assessment)
        actions.extend([sms_result, fcm_result])

        await self.redis.publish_event(
            f"actions:{pid}",
            {
                "event": "FALL_CONFIRMED",
                "patient_id": pid,
                "countdown_seconds": self._countdown,
            },
        )

        # Wait for acknowledgement within countdown window
        acknowledged = await self._wait_for_acknowledgement(pid)

        if acknowledged:
            logger.info(
                "FALL stage 2 — patient %s: acknowledged within countdown — EMS not dispatched",
                pid,
            )
            actions.append(
                ActionResult(
                    action_type="EMS",
                    status=ActionStatus.SKIPPED,
                    latency_ms=0,
                    detail="Fall acknowledged by carer — EMS not dispatched",
                )
            )
        else:
            logger.warning(
                "FALL stage 2 — patient %s: countdown expired → dispatching EMS", pid
            )
            ems_result = await self.ems.dispatch(processed, assessment, reasoning)
            actions.append(ems_result)
            await self.redis.publish_event(
                f"actions:{pid}",
                {
                    "event": EMERGENCY_DISPATCHED_EVENT,
                    "patient_id": pid,
                    "reason": "FALL_UNACKNOWLEDGED",
                },
            )

        # Cleanup Redis state
        for key_tpl in (FALL_STATE_KEY, FALL_POSSIBLE_AT_KEY, FALL_CONFIRMED_AT_KEY):
            await rc.delete(key_tpl.format(patient_id=pid))

        return actions

    async def acknowledge(self, patient_id: str) -> bool:
        """
        Called by POST /api/v1/fall/{patient_id}/acknowledge.
        Returns True if there was an active CONFIRMED_FALL to acknowledge.
        """
        rc = await self.redis.get_client()
        state_key = FALL_STATE_KEY.format(patient_id=patient_id)
        state = await rc.get(state_key)

        # Redis may return bytes or str depending on decode_responses setting
        if state not in (b"CONFIRMED_FALL", "CONFIRMED_FALL"):
            return False

        ack_key = FALL_ACKNOWLEDGED_KEY.format(patient_id=patient_id)
        await rc.set(ack_key, "1", ex=FALL_ACKNOWLEDGED_TTL_SECONDS)

        await self.redis.publish_event(
            f"actions:{patient_id}",
            {"event": "FALL_ACKNOWLEDGED", "patient_id": patient_id},
        )
        return True

    # ── Internal polling helpers ───────────────────────────────────────────────

    async def _monitor_for_motion(self, patient_id: str) -> bool:
        """
        Poll the steps_per_hour Redis window every poll_interval seconds.
        Returns True  (fall confirmed)  if no motion detected during window.
        Returns False (false positive)  if any recent reading shows steps > 0.
        """
        elapsed = 0.0
        while elapsed < self._monitoring_window:
            await asyncio.sleep(self._poll)
            elapsed += self._poll

            window = await self.redis.get_window(patient_id, "steps_per_hour")
            # Check the 3 most-recent readings (or all if fewer)
            recent = window[-3:] if len(window) >= 3 else window
            if recent and any(v > 0 for v in recent):
                return False  # motion detected

        return True  # no motion throughout window

    async def _wait_for_acknowledgement(self, patient_id: str) -> bool:
        """
        Poll Redis for acknowledgement flag every poll_interval seconds.
        Returns True if acknowledged within countdown, False if expired.
        """
        rc = await self.redis.get_client()
        ack_key = FALL_ACKNOWLEDGED_KEY.format(patient_id=patient_id)
        elapsed = 0.0

        while elapsed < self._countdown:
            await asyncio.sleep(self._poll)
            elapsed += self._poll

            raw = await rc.get(ack_key)
            if raw is not None:
                return True

        return False

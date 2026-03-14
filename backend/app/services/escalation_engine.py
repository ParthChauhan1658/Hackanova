"""
EscalationEngine — post-assessment action orchestrator.

CRITICAL  hard_override_active OR shal_band == CRITICAL
          → EMS + SMS + email + FCM dispatched in parallel (10 s timeout)

HIGH      shal_band == HIGH
          → appointment booking + SMS + email

FALL      POSSIBLE_FALL or CONFIRMED_FALL event (at any band below CRITICAL/HIGH)
          → FallProtocol two-stage state machine

All escalation paths write an immutable audit log entry.
NONE path (NOMINAL/ELEVATED/WARNING without fall) → no audit entry.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from app.core.constants import (
    EMERGENCY_DISPATCHED_EVENT,
    ESCALATION_CRITICAL_TIMEOUT_SECONDS,
)
from app.core.redis_client import RedisClient
from app.db.audit_repository import AuditRepository
from app.models.assessment import RiskAssessment, SHALBand
from app.models.escalation import ActionResult, ActionStatus, EscalationPath, EscalationResult
from app.models.reasoning import (
    DecisionSource,
    DifferentialDiagnosis,
    LLMReasoning,
    RecommendedAction,
)
from app.models.vitals import FallEvent, ProcessedReading
from app.services.appointment_service import AppointmentService
from app.services.ems_service import EMSService
from app.services.fall_protocol import FallProtocol
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)


class EscalationEngine:
    """Decides escalation path and coordinates all downstream actions."""

    def __init__(
        self,
        redis_client: RedisClient,
        notification_service: NotificationService,
        ems_service: EMSService,
        appointment_service: AppointmentService,
        fall_protocol: FallProtocol,
        audit_repo: AuditRepository,
        rule_fallback=None,  # RuleFallback — used when no LLM reasoning available
    ) -> None:
        self.redis         = redis_client
        self.notify        = notification_service
        self.ems           = ems_service
        self.appointment   = appointment_service
        self.fall_proto    = fall_protocol
        self.audit_repo    = audit_repo
        self.rule_fallback = rule_fallback

    # ── Public entry ──────────────────────────────────────────────────────────

    async def escalate(
        self,
        processed: ProcessedReading,
        assessment: RiskAssessment,
        reasoning: Optional[LLMReasoning] = None,
    ) -> EscalationResult:
        """
        Determine escalation path, execute all actions, write audit log.
        Never raises — exceptions are caught and logged.
        """
        start = time.monotonic()
        pid   = processed.original.patient_id
        fall_event = processed.original.fall_event

        # Ensure we always have a reasoning object for the audit log
        if reasoning is None:
            reasoning = self._generate_fallback_reasoning(processed, assessment)

        # ── Determine escalation path ─────────────────────────────────────────
        if assessment.hard_override_active or assessment.shal_band == SHALBand.CRITICAL:
            path = EscalationPath.CRITICAL
        elif assessment.shal_band == SHALBand.HIGH:
            path = EscalationPath.HIGH
        elif fall_event in (FallEvent.POSSIBLE_FALL, FallEvent.CONFIRMED_FALL):
            path = EscalationPath.FALL
        else:
            path = EscalationPath.NONE

        logger.info(
            "ESCALATION — patient %s band %s path %s score %.1f",
            pid,
            assessment.shal_band.value,
            path.value,
            assessment.final_score,
        )

        # ── Execute path ──────────────────────────────────────────────────────
        actions: list[ActionResult] = []
        try:
            if path == EscalationPath.CRITICAL:
                actions = await self._critical_path(processed, assessment, reasoning)
            elif path == EscalationPath.HIGH:
                actions = await self._high_path(processed, assessment, reasoning)
            elif path == EscalationPath.FALL:
                actions = await self.fall_proto.handle(processed, assessment, reasoning)
            # NONE: no actions
        except Exception as exc:
            logger.error(
                "Escalation path %s raised for patient %s: %s", path.value, pid, exc
            )

        total_latency = (time.monotonic() - start) * 1000
        all_succeeded = all(
            a.status in (ActionStatus.SUCCESS, ActionStatus.SKIPPED) for a in actions
        )

        result = EscalationResult(
            patient_id=pid,
            escalation_path=path,
            actions=actions,
            total_latency_ms=total_latency,
            all_succeeded=all_succeeded,
            escalated_at=datetime.now(timezone.utc),
        )

        # Write audit log for every non-NONE escalation
        if path != EscalationPath.NONE:
            try:
                entry = await self.audit_repo.build_entry(
                    reasoning=reasoning,
                    assessment=assessment,
                    processed=processed,
                    escalation_result=result,
                )
                await self.audit_repo.insert(entry)
                logger.info(
                    "Audit log written — patient %s path %s latency %.0fms",
                    pid,
                    path.value,
                    total_latency,
                )
            except Exception as exc:
                logger.error(
                    "Failed to write audit log for patient %s: %s", pid, exc
                )

        return result

    # ── Escalation paths ──────────────────────────────────────────────────────

    async def _critical_path(
        self,
        processed: ProcessedReading,
        assessment: RiskAssessment,
        reasoning: LLMReasoning,
    ) -> list[ActionResult]:
        """
        CRITICAL: EMS + SMS + email + FCM dispatched in parallel.
        Bounded by ESCALATION_CRITICAL_TIMEOUT_SECONDS (10 s).
        """
        pid = processed.original.patient_id
        logger.info("ESCALATION CRITICAL path — patient %s", pid)

        try:
            raw = await asyncio.wait_for(
                asyncio.gather(
                    self.ems.dispatch(processed, assessment, reasoning),
                    self.notify.send_critical_sms(processed, assessment, reasoning),
                    self.notify.send_critical_email(processed, assessment, reasoning),
                    self.notify.send_fcm_push(processed, assessment),
                    self.notify.send_critical_call(processed, assessment),
                    return_exceptions=True,
                ),
                timeout=ESCALATION_CRITICAL_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.error(
                "CRITICAL escalation timed out after %.0fs — patient %s",
                ESCALATION_CRITICAL_TIMEOUT_SECONDS,
                pid,
            )
            return [
                ActionResult(
                    action_type="ESCALATION",
                    status=ActionStatus.FAILED,
                    latency_ms=ESCALATION_CRITICAL_TIMEOUT_SECONDS * 1000,
                    detail="Critical escalation timed out",
                )
            ]

        actions: list[ActionResult] = []
        labels = ["EMS", "SMS", "EMAIL", "FCM", "CALL"]
        for label, item in zip(labels, raw):
            if isinstance(item, Exception):
                logger.warning("CRITICAL action %s raised: %s", label, item)
                actions.append(
                    ActionResult(
                        action_type=label,
                        status=ActionStatus.FAILED,
                        latency_ms=0,
                        detail=str(item),
                    )
                )
            else:
                actions.append(item)

        await self.redis.publish_event(
            f"actions:{pid}",
            {
                "event": EMERGENCY_DISPATCHED_EVENT,
                "patient_id": pid,
                "shal_band": assessment.shal_band.value,
                "final_score": assessment.final_score,
            },
        )
        return actions

    async def _high_path(
        self,
        processed: ProcessedReading,
        assessment: RiskAssessment,
        reasoning: LLMReasoning,
    ) -> list[ActionResult]:
        """HIGH: appointment booking (priority), then SMS + email in parallel."""
        pid = processed.original.patient_id
        logger.info("ESCALATION HIGH path — patient %s", pid)

        actions: list[ActionResult] = []

        # Appointment first — most important for HIGH escalation
        appt_result = await self.appointment.book_urgent_appointment(
            processed, assessment, reasoning
        )
        actions.append(appt_result)

        # SMS and email in parallel
        raw = await asyncio.gather(
            self.notify.send_critical_sms(processed, assessment, reasoning),
            self.notify.send_critical_email(processed, assessment, reasoning),
            return_exceptions=True,
        )
        for label, item in zip(["SMS", "EMAIL"], raw):
            if isinstance(item, Exception):
                logger.warning("HIGH action %s raised: %s", label, item)
                actions.append(
                    ActionResult(
                        action_type=label,
                        status=ActionStatus.FAILED,
                        latency_ms=0,
                        detail=str(item),
                    )
                )
            else:
                actions.append(item)

        return actions

    # ── Fallback reasoning builder ────────────────────────────────────────────

    def _generate_fallback_reasoning(
        self,
        processed: ProcessedReading,
        assessment: RiskAssessment,
    ) -> LLMReasoning:
        """Generate minimal rule-based reasoning for FALL events without LLM output."""
        if self.rule_fallback is not None:
            try:
                return self.rule_fallback.reason(processed, assessment)
            except Exception as exc:
                logger.warning(
                    "Rule fallback failed in escalation engine: %s", exc
                )

        # Absolute floor — never fails
        orig = processed.original
        now  = datetime.now(timezone.utc)
        return LLMReasoning(
            patient_id=orig.patient_id,
            session_id=orig.session_id,
            reading_id=orig.reading_id,
            timestamp=orig.timestamp,
            decision_source=DecisionSource.RULE_BASED,
            shal_band=assessment.shal_band.value,
            final_score=assessment.final_score,
            reasoning_summary=(
                f"Fall event detected — score {assessment.final_score}/100."
            ),
            differential_diagnoses=[
                DifferentialDiagnosis(
                    diagnosis="Fall with potential injury",
                    probability=0.70,
                    supporting_evidence=["Fall event reported by wearable"],
                    against_evidence=[],
                    clinical_source="SENTINEL fall protocol",
                )
            ],
            recommended_actions=[
                RecommendedAction(
                    action="Assess patient for fall-related injury",
                    urgency="IMMEDIATE",
                    rationale="Fall event confirmed",
                )
            ],
            confidence=0.65,
            considered_and_discarded=[],
            vitals_snapshot=dict(processed.validated_vitals),
            syndromes_fired=list(assessment.sl3.syndromes_fired),
            trends_fired=list(assessment.sl4.trends_fired),
            hard_override_type=assessment.hard_override_type,
            model_used=None,
            latency_ms=0.0,
            reasoned_at=now,
        )

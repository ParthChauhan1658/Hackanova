"""
AuditRepository — all database operations for AuditLogEntry.
Immutable: only INSERT, never UPDATE.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import AuditLogEntry
from app.models.assessment import RiskAssessment
from app.models.escalation import ActionStatus, EscalationResult
from app.models.reasoning import LLMReasoning, DecisionSource
from app.models.vitals import ProcessedReading

logger = logging.getLogger(__name__)


class AuditRepository:
    """Handles all DB writes and queries for AuditLogEntry."""

    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._session_factory = session_factory

    async def insert(self, entry: AuditLogEntry) -> AuditLogEntry:
        """
        Insert an immutable audit log entry.
        Never updates existing rows.
        """
        async with self._session_factory() as session:
            session.add(entry)
            await session.commit()
            await session.refresh(entry)
            return entry

    async def get_by_patient(
        self,
        patient_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AuditLogEntry]:
        """
        Retrieve audit entries for a patient, newest first.
        Uses ix_audit_patient_time index.
        """
        async with self._session_factory() as session:
            result = await session.execute(
                select(AuditLogEntry)
                .where(AuditLogEntry.patient_id == patient_id)
                .order_by(desc(AuditLogEntry.escalated_at))
                .limit(limit)
                .offset(offset)
            )
            return list(result.scalars().all())

    async def get_recent(self, limit: int = 100) -> list[AuditLogEntry]:
        """Retrieve most recent audit entries across all patients."""
        async with self._session_factory() as session:
            result = await session.execute(
                select(AuditLogEntry)
                .order_by(desc(AuditLogEntry.escalated_at))
                .limit(limit)
            )
            return list(result.scalars().all())

    async def get_by_id(self, entry_id: int) -> AuditLogEntry | None:
        """Retrieve a single AuditLogEntry by primary key."""
        async with self._session_factory() as session:
            result = await session.execute(
                select(AuditLogEntry).where(AuditLogEntry.id == entry_id)
            )
            return result.scalar_one_or_none()

    async def build_entry(
        self,
        reasoning: LLMReasoning,
        assessment: RiskAssessment,
        processed: ProcessedReading,
        escalation_result: EscalationResult,
    ) -> AuditLogEntry:
        """
        Build AuditLogEntry from all pipeline outputs.
        JSON-serialises dicts, lists, and complex objects.
        """
        actions = escalation_result.actions

        def _action_taken(action_type: str) -> bool:
            for a in actions:
                if a.action_type == action_type and a.status == ActionStatus.SUCCESS:
                    return True
            return False

        ems_code: int | None = None
        appt_id: str | None = None
        for a in actions:
            if a.action_type == "EMS" and a.detail:
                try:
                    ems_code = int(a.detail.split("HTTP ")[-1][:3])
                except Exception:
                    pass
            if a.action_type == "APPOINTMENT" and a.status == ActionStatus.SUCCESS and a.detail:
                appt_id = a.detail

        diag_json = json.dumps(
            [d.model_dump() for d in reasoning.differential_diagnoses],
            default=str,
        )
        vitals_json = json.dumps(processed.validated_vitals, default=str)
        syndromes_json = json.dumps(assessment.sl3.syndromes_fired)
        trends_json = json.dumps(assessment.sl4.trends_fired)

        fall_event_type = processed.original.fall_event.value

        return AuditLogEntry(
            patient_id=reasoning.patient_id,
            session_id=reasoning.session_id,
            reading_id=reasoning.reading_id,
            escalated_at=datetime.now(timezone.utc),
            final_score=assessment.final_score,
            shal_band=assessment.shal_band.value,
            hard_override_active=assessment.hard_override_active,
            hard_override_type=assessment.hard_override_type,
            decision_source=reasoning.decision_source.value,
            reasoning_summary=reasoning.reasoning_summary,
            llm_thinking_chain=reasoning.thinking_chain,
            differential_diagnoses=diag_json,
            confidence=reasoning.confidence,
            ems_dispatched=_action_taken("EMS"),
            sms_sent=_action_taken("SMS"),
            email_sent=_action_taken("EMAIL"),
            fcm_sent=_action_taken("FCM"),
            appointment_booked=_action_taken("APPOINTMENT"),
            ems_response_code=ems_code,
            appointment_id=appt_id,
            actions_latency_ms=escalation_result.total_latency_ms,
            vitals_snapshot=vitals_json,
            syndromes_fired=syndromes_json,
            trends_fired=trends_json,
            fall_event_type=fall_event_type,
        )

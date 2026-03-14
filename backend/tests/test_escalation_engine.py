"""
Pytest tests for SENTINEL Escalation Engine (Component 4).

Covers:
  EscalationEngine — CRITICAL, HIGH, NONE, FALL delegation, timeout,
                     audit log, hard override, partial failures
  FallProtocol     — false positive, acknowledged, unacknowledged
  Fallback         — reasoning generated when not available
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis
import pytest
import pytest_asyncio

from app.core.redis_client import RedisClient
from app.models.assessment import (
    MEWSResult,
    RiskAssessment,
    SHALBand,
    SL1Result,
    SL2Result,
    SL3Result,
    SL4Result,
    SL5Result,
)
from app.models.escalation import ActionResult, ActionStatus, EscalationPath
from app.models.reasoning import (
    DecisionSource,
    DifferentialDiagnosis,
    LLMReasoning,
    RecommendedAction,
)
from app.models.vitals import FallEvent, ProcessedReading, VitalReading
from app.services.escalation_engine import EscalationEngine
from app.services.fall_protocol import FallProtocol


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def redis_client():
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    client = RedisClient(client=fake)
    yield client
    await fake.aclose()


# ── Factory helpers ────────────────────────────────────────────────────────────

_NOW = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _make_reading(
    patient_id: str = "P001",
    fall_event: FallEvent = FallEvent.NONE,
) -> VitalReading:
    return VitalReading(
        reading_id="R001",
        patient_id=patient_id,
        session_id="S001",
        timestamp=_NOW,
        heart_rate=105.0,
        respiratory_rate=22.0,
        spo2=90.0,
        body_temperature=38.5,
        hrv_ms=25.0,
        fall_event=fall_event,
    )


def _make_processed(
    patient_id: str = "P001",
    fall_event: FallEvent = FallEvent.NONE,
) -> ProcessedReading:
    reading = _make_reading(patient_id=patient_id, fall_event=fall_event)
    return ProcessedReading(
        original=reading,
        validated_vitals={
            "heart_rate": 105.0,
            "respiratory_rate": 22.0,
            "spo2": 90.0,
            "body_temperature": 38.5,
            "hrv_ms": 25.0,
        },
        is_interpolated={},
        threshold_flags={},
        window_trends={},
        processed_at=_NOW,
    )


def _make_assessment(
    shal_band: SHALBand = SHALBand.CRITICAL,
    final_score: float = 85.0,
    hard_override_active: bool = False,
    hard_override_type: Optional[str] = None,
    syndromes: Optional[list[str]] = None,
) -> RiskAssessment:
    syndromes = syndromes or []
    return RiskAssessment(
        patient_id="P001",
        session_id="S001",
        reading_id="R001",
        timestamp=_NOW,
        final_score=final_score,
        shal_band=shal_band,
        hard_override_active=hard_override_active,
        hard_override_type=hard_override_type,
        sl1=SL1Result(
            raw_points=20.0,
            normalised_points=16.7,
            contributors=[],
            vital_scores={},
        ),
        sl2=SL2Result(
            additive_points=0.0,
            weight_multipliers_applied={},
            contributors=[],
        ),
        sl3=SL3Result(
            syndromes_fired=syndromes,
            total_points=sum(25.0 for _ in syndromes),
            contributors=[],
            qsofa_score=0,
            qsofa_criteria_met=[],
        ),
        sl4=SL4Result(trends_fired=[], total_points=0.0, contributors=[]),
        sl5=SL5Result(anomaly_score=0.3, points_added=0.0, xai_label=""),
        mews=MEWSResult(mews_score=2, mews_flag=False, review_flag_added=False),
        all_contributors=[],
        xai_narrative="Test narrative",
        assessed_at=_NOW,
    )


def _make_reasoning(patient_id: str = "P001") -> LLMReasoning:
    return LLMReasoning(
        patient_id=patient_id,
        session_id="S001",
        reading_id="R001",
        timestamp=_NOW,
        decision_source=DecisionSource.RULE_BASED,
        shal_band="CRITICAL",
        final_score=85.0,
        reasoning_summary="Test reasoning",
        differential_diagnoses=[
            DifferentialDiagnosis(
                diagnosis="Test condition",
                probability=0.8,
                supporting_evidence=[],
                against_evidence=[],
                clinical_source="SENTINEL",
            )
        ],
        recommended_actions=[
            RecommendedAction(
                action="Immediate review",
                urgency="IMMEDIATE",
                rationale="High risk",
            )
        ],
        confidence=0.8,
        considered_and_discarded=[],
        vitals_snapshot={},
        syndromes_fired=[],
        trends_fired=[],
        latency_ms=10.0,
        reasoned_at=_NOW,
    )


def _ok(action_type: str) -> ActionResult:
    return ActionResult(
        action_type=action_type, status=ActionStatus.SUCCESS, latency_ms=50.0
    )


def _skipped(action_type: str) -> ActionResult:
    return ActionResult(
        action_type=action_type,
        status=ActionStatus.SKIPPED,
        latency_ms=0.0,
        detail="Not configured",
    )


def _build_engine(
    redis_client: RedisClient,
    *,
    notify=None,
    ems=None,
    appointment=None,
    fall_proto=None,
    audit_repo=None,
) -> EscalationEngine:
    if notify is None:
        notify = AsyncMock()
        notify.send_critical_sms = AsyncMock(return_value=_ok("SMS"))
        notify.send_critical_email = AsyncMock(return_value=_ok("EMAIL"))
        notify.send_fcm_push = AsyncMock(return_value=_ok("FCM"))

    if ems is None:
        ems = AsyncMock()
        ems.dispatch = AsyncMock(return_value=_ok("EMS"))

    if appointment is None:
        appointment = AsyncMock()
        appointment.book_urgent_appointment = AsyncMock(
            return_value=_ok("APPOINTMENT")
        )

    if fall_proto is None:
        fall_proto = AsyncMock()
        fall_proto.handle = AsyncMock(return_value=[_ok("FALL")])

    if audit_repo is None:
        mock_entry = MagicMock()
        mock_entry.id = 1
        audit_repo = AsyncMock()
        audit_repo.build_entry = AsyncMock(return_value=mock_entry)
        audit_repo.insert = AsyncMock(return_value=mock_entry)

    return EscalationEngine(
        redis_client=redis_client,
        notification_service=notify,
        ems_service=ems,
        appointment_service=appointment,
        fall_protocol=fall_proto,
        audit_repo=audit_repo,
    )


# ── Tests: EscalationEngine ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_critical_path_dispatches_all_4_actions(redis_client):
    """CRITICAL band triggers EMS + SMS + email + FCM in parallel."""
    notify = AsyncMock()
    notify.send_critical_sms   = AsyncMock(return_value=_ok("SMS"))
    notify.send_critical_email = AsyncMock(return_value=_ok("EMAIL"))
    notify.send_fcm_push       = AsyncMock(return_value=_ok("FCM"))

    ems = AsyncMock()
    ems.dispatch = AsyncMock(return_value=_ok("EMS"))

    engine = _build_engine(redis_client, notify=notify, ems=ems)
    result = await engine.escalate(
        _make_processed(), _make_assessment(SHALBand.CRITICAL), _make_reasoning()
    )

    assert result.escalation_path == EscalationPath.CRITICAL
    action_types = {a.action_type for a in result.actions}
    assert {"EMS", "SMS", "EMAIL", "FCM"}.issubset(action_types)
    notify.send_critical_sms.assert_called_once()
    notify.send_critical_email.assert_called_once()
    notify.send_fcm_push.assert_called_once()
    ems.dispatch.assert_called_once()


@pytest.mark.asyncio
async def test_high_path_books_appointment_and_notifies(redis_client):
    """HIGH band → appointment booking + SMS + email (no EMS, no FCM)."""
    appointment = AsyncMock()
    appointment.book_urgent_appointment = AsyncMock(
        return_value=_ok("APPOINTMENT")
    )
    notify = AsyncMock()
    notify.send_critical_sms   = AsyncMock(return_value=_ok("SMS"))
    notify.send_critical_email = AsyncMock(return_value=_ok("EMAIL"))

    engine = _build_engine(redis_client, notify=notify, appointment=appointment)
    result = await engine.escalate(
        _make_processed(),
        _make_assessment(SHALBand.HIGH, final_score=72.0),
        _make_reasoning(),
    )

    assert result.escalation_path == EscalationPath.HIGH
    action_types = {a.action_type for a in result.actions}
    assert "APPOINTMENT" in action_types
    assert "SMS" in action_types
    assert "EMAIL" in action_types
    assert "EMS" not in action_types
    assert "FCM" not in action_types
    appointment.book_urgent_appointment.assert_called_once()


@pytest.mark.asyncio
async def test_none_path_no_actions_no_audit(redis_client):
    """NOMINAL band without fall event → NONE path, no actions, no audit write."""
    audit_repo = AsyncMock()
    audit_repo.build_entry = AsyncMock()
    audit_repo.insert      = AsyncMock()

    engine = _build_engine(redis_client, audit_repo=audit_repo)
    result = await engine.escalate(
        _make_processed(),
        _make_assessment(SHALBand.NOMINAL, final_score=10.0),
        _make_reasoning(),
    )

    assert result.escalation_path == EscalationPath.NONE
    assert result.actions == []
    audit_repo.insert.assert_not_called()


@pytest.mark.asyncio
async def test_audit_log_written_after_critical_escalation(redis_client):
    """Audit repository insert is called exactly once after CRITICAL escalation."""
    mock_entry = MagicMock()
    mock_entry.id = 42
    audit_repo = AsyncMock()
    audit_repo.build_entry = AsyncMock(return_value=mock_entry)
    audit_repo.insert      = AsyncMock(return_value=mock_entry)

    engine = _build_engine(redis_client, audit_repo=audit_repo)
    await engine.escalate(
        _make_processed(), _make_assessment(SHALBand.CRITICAL), _make_reasoning()
    )

    audit_repo.build_entry.assert_called_once()
    audit_repo.insert.assert_called_once_with(mock_entry)


@pytest.mark.asyncio
async def test_hard_override_forces_critical_path(redis_client):
    """hard_override_active=True at NOMINAL band → CRITICAL path regardless."""
    ems = AsyncMock()
    ems.dispatch = AsyncMock(return_value=_ok("EMS"))

    engine = _build_engine(redis_client, ems=ems)

    # NOMINAL band but override active — should still CRITICAL dispatch
    assessment = _make_assessment(
        shal_band=SHALBand.NOMINAL,
        final_score=100.0,
        hard_override_active=True,
        hard_override_type="SPO2_CRITICAL",
    )
    result = await engine.escalate(_make_processed(), assessment, _make_reasoning())

    assert result.escalation_path == EscalationPath.CRITICAL
    ems.dispatch.assert_called_once()


@pytest.mark.asyncio
async def test_high_path_appointment_failure_still_sends_sms(redis_client):
    """If appointment booking fails, SMS and email are still sent."""
    appointment = AsyncMock()
    appointment.book_urgent_appointment = AsyncMock(
        return_value=ActionResult(
            action_type="APPOINTMENT",
            status=ActionStatus.FAILED,
            latency_ms=200.0,
            detail="Cal.com 503",
        )
    )
    notify = AsyncMock()
    notify.send_critical_sms   = AsyncMock(return_value=_ok("SMS"))
    notify.send_critical_email = AsyncMock(return_value=_ok("EMAIL"))

    engine = _build_engine(redis_client, notify=notify, appointment=appointment)
    result = await engine.escalate(
        _make_processed(),
        _make_assessment(SHALBand.HIGH, final_score=72.0),
        _make_reasoning(),
    )

    action_statuses = {a.action_type: a.status for a in result.actions}
    assert action_statuses["APPOINTMENT"] == ActionStatus.FAILED
    assert action_statuses["SMS"] == ActionStatus.SUCCESS
    assert action_statuses["EMAIL"] == ActionStatus.SUCCESS
    assert result.all_succeeded is False


@pytest.mark.asyncio
async def test_reasoning_generated_when_none_for_fall(redis_client):
    """When reasoning=None (fall event at low band), fallback reasoning is generated."""
    fall_proto = AsyncMock()
    fall_proto.handle = AsyncMock(return_value=[_ok("FALL")])

    audit_repo = AsyncMock()
    audit_repo.build_entry = AsyncMock(return_value=MagicMock())
    audit_repo.insert      = AsyncMock()

    engine = _build_engine(
        redis_client, fall_proto=fall_proto, audit_repo=audit_repo
    )
    assessment = _make_assessment(SHALBand.NOMINAL, final_score=15.0)
    processed  = _make_processed(fall_event=FallEvent.POSSIBLE_FALL)

    # Pass reasoning=None — engine must generate it internally
    result = await engine.escalate(processed, assessment, reasoning=None)

    assert result.escalation_path == EscalationPath.FALL
    # audit build_entry was called with an auto-generated reasoning
    build_call_kwargs = audit_repo.build_entry.call_args
    assert build_call_kwargs is not None
    reasoning_arg = build_call_kwargs.kwargs.get("reasoning") or build_call_kwargs.args[0]
    assert reasoning_arg is not None


@pytest.mark.asyncio
async def test_fall_delegation_to_fall_protocol(redis_client):
    """POSSIBLE_FALL at NOMINAL band → delegates to fall_protocol.handle()."""
    fall_proto = AsyncMock()
    fall_proto.handle = AsyncMock(return_value=[_ok("FALL")])

    engine = _build_engine(redis_client, fall_proto=fall_proto)
    processed = _make_processed(fall_event=FallEvent.POSSIBLE_FALL)
    assessment = _make_assessment(SHALBand.NOMINAL, final_score=15.0)

    result = await engine.escalate(processed, assessment, _make_reasoning())

    assert result.escalation_path == EscalationPath.FALL
    fall_proto.handle.assert_called_once()


# ── Tests: FallProtocol ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fall_false_positive_motion_detected(redis_client):
    """
    FallProtocol stage 1: steps > 0 found in Redis window during monitoring →
    false positive, returns SKIPPED with no EMS.
    """
    # Pre-load the steps window with non-zero motion
    rc = await redis_client.get_client()
    await rc.rpush("vitals:P001:steps_per_hour:window", "150.0")

    ems = AsyncMock()
    ems.dispatch = AsyncMock(return_value=_ok("EMS"))

    notify = AsyncMock()
    notify.send_critical_sms = AsyncMock(return_value=_skipped("SMS"))
    notify.send_fcm_push     = AsyncMock(return_value=_skipped("FCM"))

    fall_protocol = FallProtocol(
        redis_client=redis_client,
        ems_service=ems,
        notification_service=notify,
        monitoring_window=0.15,  # very short for test
        countdown_seconds=0.15,
        poll_interval=0.05,
    )

    processed  = _make_processed(fall_event=FallEvent.POSSIBLE_FALL)
    assessment = _make_assessment(SHALBand.NOMINAL)
    reasoning  = _make_reasoning()

    actions = await fall_protocol.handle(processed, assessment, reasoning)

    assert len(actions) == 1
    assert actions[0].action_type == "FALL"
    assert actions[0].status == ActionStatus.SKIPPED
    assert "false positive" in actions[0].detail.lower()
    ems.dispatch.assert_not_called()


@pytest.mark.asyncio
async def test_fall_confirmed_and_acknowledged_no_ems(redis_client):
    """
    FallProtocol stage 2: no motion → CONFIRMED_FALL, carer acknowledges within
    countdown → EMS SKIPPED.
    """
    ems = AsyncMock()
    ems.dispatch = AsyncMock(return_value=_ok("EMS"))

    notify = AsyncMock()
    notify.send_critical_sms = AsyncMock(return_value=_ok("SMS"))
    notify.send_fcm_push     = AsyncMock(return_value=_ok("FCM"))

    fall_protocol = FallProtocol(
        redis_client=redis_client,
        ems_service=ems,
        notification_service=notify,
        monitoring_window=0.1,
        countdown_seconds=0.3,
        poll_interval=0.05,
    )

    processed  = _make_processed(fall_event=FallEvent.POSSIBLE_FALL)
    assessment = _make_assessment(SHALBand.NOMINAL)
    reasoning  = _make_reasoning()

    # Acknowledge after a short delay (before countdown expires)
    async def _acknowledge():
        await asyncio.sleep(0.15)
        await fall_protocol.acknowledge("P001")

    asyncio.create_task(_acknowledge())
    actions = await fall_protocol.handle(processed, assessment, reasoning)

    ems_actions = [a for a in actions if a.action_type == "EMS"]
    assert len(ems_actions) == 1
    assert ems_actions[0].status == ActionStatus.SKIPPED
    ems.dispatch.assert_not_called()


@pytest.mark.asyncio
async def test_fall_confirmed_unacknowledged_dispatches_ems(redis_client):
    """
    FallProtocol stage 2: no motion → CONFIRMED_FALL, nobody acknowledges →
    EMS dispatched after countdown expires.
    """
    ems = AsyncMock()
    ems.dispatch = AsyncMock(return_value=_ok("EMS"))

    notify = AsyncMock()
    notify.send_critical_sms = AsyncMock(return_value=_ok("SMS"))
    notify.send_fcm_push     = AsyncMock(return_value=_ok("FCM"))

    fall_protocol = FallProtocol(
        redis_client=redis_client,
        ems_service=ems,
        notification_service=notify,
        monitoring_window=0.1,
        countdown_seconds=0.15,
        poll_interval=0.05,
    )

    processed  = _make_processed(fall_event=FallEvent.POSSIBLE_FALL)
    assessment = _make_assessment(SHALBand.NOMINAL)
    reasoning  = _make_reasoning()

    actions = await fall_protocol.handle(processed, assessment, reasoning)

    ems_actions = [a for a in actions if a.action_type == "EMS"]
    assert len(ems_actions) == 1
    assert ems_actions[0].status == ActionStatus.SUCCESS
    ems.dispatch.assert_called_once()


@pytest.mark.asyncio
async def test_acknowledge_returns_false_when_no_active_fall(redis_client):
    """FallProtocol.acknowledge returns False if no CONFIRMED_FALL is in Redis."""
    ems = AsyncMock()
    notify = AsyncMock()

    fall_protocol = FallProtocol(
        redis_client=redis_client,
        ems_service=ems,
        notification_service=notify,
    )

    result = await fall_protocol.acknowledge("P_NO_FALL")
    assert result is False

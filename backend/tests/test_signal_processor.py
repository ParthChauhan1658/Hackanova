"""
Unit tests for SignalProcessor.
Uses fakeredis.aioredis for in-memory Redis — no real Redis instance needed.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
import fakeredis.aioredis as fake_aioredis
from datetime import datetime, timezone

from app.core.redis_client import RedisClient
from app.models.vitals import (
    ActivityLevel,
    ECGRhythm,
    FallEvent,
    VitalReading,
)
from app.services.signal_processor import SignalProcessor


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def redis_client():
    """Fresh in-memory fakeredis instance per test."""
    fake = fake_aioredis.FakeRedis(decode_responses=True)
    client = RedisClient(client=fake)
    yield client
    await fake.aclose()


@pytest_asyncio.fixture
async def processor(redis_client):
    return SignalProcessor(redis_client=redis_client)


def make_reading(**overrides) -> VitalReading:
    """Build a minimal valid VitalReading, applying keyword overrides."""
    defaults = dict(
        reading_id="test-001",
        patient_id="P_TEST",
        session_id="SES-TEST-001",
        timestamp=datetime(2025, 1, 15, 8, 0, 0, tzinfo=timezone.utc),
        heart_rate=72.0,
        respiratory_rate=15.0,
        spo2=98.0,
        ecg_rhythm=ECGRhythm.NORMAL,
        ecg_st_deviation_mm=0.1,
        ecg_qtc_ms=400.0,
        body_temperature=36.6,
        sleep_efficiency=88.0,
        deep_sleep_pct=20.0,
        rem_pct=22.0,
        hrv_ms=45.0,
        stress_score=25.0,
        fall_event=FallEvent.NONE,
        steps_per_hour=300.0,
        activity_context=ActivityLevel.RESTING,
        age=35,
        gender="M",
        weight_kg=72.0,
        has_chronic_condition=False,
        latitude=19.076,
        longitude=72.877,
        location_stale=False,
        source="synthetic_dataset",
        signal_quality=95.0,
    )
    defaults.update(overrides)
    return VitalReading(**defaults)


# ── Test 1 — Implausible HR discarded and interpolated ───────────────────────

@pytest.mark.asyncio
async def test_implausible_hr_discarded_and_interpolated(processor, redis_client):
    """HR=300 is outside (20, 250) → discarded; last valid from Redis substituted."""
    # Seed a valid last-valid HR in Redis
    await redis_client.set_last_valid("P_TEST", "heart_rate", 70.0)

    reading = make_reading(heart_rate=300.0)
    result = await processor.process(reading)

    assert result.validated_vitals["heart_rate"] == 70.0, "Should interpolate from last valid"
    assert result.is_interpolated["heart_rate"] is True
    assert result.low_signal_quality is False


# ── Test 2 — SpO₂ < 85 fires SPO2_CRITICAL ───────────────────────────────────

@pytest.mark.asyncio
async def test_spo2_critical_hard_override(processor):
    reading = make_reading(spo2=84.0)
    result = await processor.process(reading)

    assert result.hard_override is not None
    assert result.hard_override.override_type == "SPO2_CRITICAL"
    assert result.hard_override.triggered_value == pytest.approx(84.0)


# ── Test 3 — Two consecutive HR > 150 fires HR_SEVERE_TACHY ─────────────────

@pytest.mark.asyncio
async def test_hr_severe_tachy_sustained(processor, redis_client):
    """Two readings with HR=155 → second reading fires HR_SEVERE_TACHY."""
    r1 = make_reading(reading_id="r1", heart_rate=155.0)
    await processor.process(r1)

    r2 = make_reading(reading_id="r2", heart_rate=156.0)
    result = await processor.process(r2)

    assert result.hard_override is not None
    assert result.hard_override.override_type == "HR_SEVERE_TACHY"


# ── Test 4 — CONFIRMED_FALL + zero steps fires FALL_UNRESPONSIVE ─────────────

@pytest.mark.asyncio
async def test_fall_unresponsive_override(processor):
    """Two CONFIRMED_FALL readings with steps=0 → FALL_UNRESPONSIVE."""
    r1 = make_reading(
        reading_id="fall-1",
        fall_event=FallEvent.CONFIRMED_FALL,
        steps_per_hour=0.0,
    )
    await processor.process(r1)

    r2 = make_reading(
        reading_id="fall-2",
        fall_event=FallEvent.CONFIRMED_FALL,
        steps_per_hour=0.0,
    )
    result = await processor.process(r2)

    assert result.hard_override is not None
    assert result.hard_override.override_type == "FALL_UNRESPONSIVE"


# ── Test 5 — Low signal quality gates everything ─────────────────────────────

@pytest.mark.asyncio
async def test_low_signal_quality(processor):
    """signal_quality=10 → low_signal_quality=True, no HardOverride (even with bad ECG)."""
    reading = make_reading(
        signal_quality=10.0,
        ecg_rhythm=ECGRhythm.VT,   # would normally fire ECG_LETHAL_RHYTHM
        spo2=70.0,                  # would normally fire SPO2_CRITICAL
    )
    result = await processor.process(reading)

    assert result.low_signal_quality is True
    assert result.hard_override is None
    # All vitals marked as interpolated (spec: "for all vitals")
    for field, flag in result.is_interpolated.items():
        assert flag is True, f"Expected is_interpolated[{field}]=True for low-signal reading"


# ── Test 6 — ECG VT fires ECG_LETHAL_RHYTHM first (highest priority) ─────────

@pytest.mark.asyncio
async def test_ecg_lethal_rhythm_priority(processor):
    """VT + SpO₂=70% → ECG_LETHAL_RHYTHM fires before SPO2_CRITICAL (priority 1 > 3)."""
    reading = make_reading(
        ecg_rhythm=ECGRhythm.VT,
        spo2=70.0,
    )
    result = await processor.process(reading)

    assert result.hard_override is not None
    assert result.hard_override.override_type == "ECG_LETHAL_RHYTHM"


# ── Test 7 — HRV acute drop detected ────────────────────────────────────────

@pytest.mark.asyncio
async def test_hrv_acute_drop(processor, redis_client):
    """Baseline=50ms; current=25ms (< 60% of 50=30ms) → hrv_acute_drop=True."""
    # Seed a baseline via multiple readings
    for _ in range(5):
        r = make_reading(hrv_ms=50.0)
        await processor.process(r)

    # Send a low HRV reading
    low_hrv_reading = make_reading(hrv_ms=25.0)
    result = await processor.process(low_hrv_reading)

    assert result.hrv_acute_drop is True


# ── Test 8 — VIGOROUS activity sets suppressor flag ──────────────────────────

@pytest.mark.asyncio
async def test_vigorous_activity_flag(processor):
    reading = make_reading(activity_context=ActivityLevel.VIGOROUS)
    result = await processor.process(reading)

    assert result.apply_hr_vigorous_suppressor is True
    assert result.apply_hr_sedentary_amplifier is False


# ── Test 9 — Valid location → LocationSnapshot populated ─────────────────────

@pytest.mark.asyncio
async def test_location_snapshot_populated(processor):
    reading = make_reading(
        latitude=19.076,
        longitude=72.877,
        location_stale=False,
    )
    result = await processor.process(reading)

    assert result.location is not None
    assert result.location.latitude == pytest.approx(19.076)
    assert result.location.longitude == pytest.approx(72.877)


# ── Test 10 — Stale location → location is None ──────────────────────────────

@pytest.mark.asyncio
async def test_stale_location_is_none(processor):
    reading = make_reading(
        latitude=19.076,
        longitude=72.877,
        location_stale=True,
    )
    result = await processor.process(reading)

    assert result.location is None

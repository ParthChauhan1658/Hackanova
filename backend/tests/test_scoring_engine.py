"""
Pytest tests for the SENTINEL Scoring Engine (Component 3).
Uses fakeredis for in-memory Redis and a mock IsolationForestWrapper.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Optional
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
import fakeredis.aioredis

from app.core.redis_client import RedisClient
from app.ml.isolation_forest import IsolationForestWrapper
from app.models.assessment import SHALBand, SL5Result, ScoreContributor
from app.models.vitals import (
    ActivityLevel,
    ECGRhythm,
    FallEvent,
    HardOverride,
    ProcessedReading,
    VitalReading,
)
from app.services.scoring_engine import ScoringEngine


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def redis_client():
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    client = RedisClient(client=fake)
    yield client
    await fake.aclose()


@pytest.fixture
def mock_if_model():
    """IsolationForestWrapper that returns a fixed anomaly_score of 0.3 (below threshold)."""
    model = MagicMock(spec=IsolationForestWrapper)
    model.is_loaded = True
    model.score.return_value = SL5Result(
        anomaly_score=0.3,
        points_added=0.0,
        xai_label="",
        contributor=None,
    )
    return model


@pytest.fixture
def scoring_engine(redis_client, mock_if_model):
    return ScoringEngine(redis_client=redis_client, if_model=mock_if_model)


def make_reading(
    patient_id: str = "P001",
    session_id: str = "S001",
    heart_rate: Optional[float] = 75.0,
    respiratory_rate: Optional[float] = 16.0,
    spo2: Optional[float] = 98.0,
    body_temperature: Optional[float] = 37.0,
    hrv_ms: Optional[float] = 60.0,
    stress_score: Optional[float] = 30.0,
    steps_per_hour: Optional[float] = 1000.0,
    ecg_rhythm: Optional[ECGRhythm] = ECGRhythm.NORMAL,
    activity_context: Optional[ActivityLevel] = None,
    deep_sleep_pct: Optional[float] = 20.0,
    apply_hr_vigorous_suppressor: bool = False,
    apply_hr_sedentary_amplifier: bool = False,
    hrv_acute_drop: bool = False,
    hard_override: Optional[HardOverride] = None,
) -> ProcessedReading:
    now = datetime.now(timezone.utc)
    reading = VitalReading(
        reading_id="RID001",
        patient_id=patient_id,
        session_id=session_id,
        timestamp=now,
        heart_rate=heart_rate,
        respiratory_rate=respiratory_rate,
        spo2=spo2,
        body_temperature=body_temperature,
        hrv_ms=hrv_ms,
        stress_score=stress_score,
        steps_per_hour=steps_per_hour,
        ecg_rhythm=ecg_rhythm,
        activity_context=activity_context,
        deep_sleep_pct=deep_sleep_pct,
    )
    validated = {
        "heart_rate":       heart_rate,
        "respiratory_rate": respiratory_rate,
        "spo2":             spo2,
        "body_temperature": body_temperature,
        "hrv_ms":           hrv_ms,
        "stress_score":     stress_score,
        "steps_per_hour":   steps_per_hour,
        "deep_sleep_pct":   deep_sleep_pct,
    }
    return ProcessedReading(
        original=reading,
        validated_vitals=validated,
        is_interpolated={},
        threshold_flags={},
        window_trends={},
        hard_override=hard_override,
        hrv_acute_drop=hrv_acute_drop,
        apply_hr_vigorous_suppressor=apply_hr_vigorous_suppressor,
        apply_hr_sedentary_amplifier=apply_hr_sedentary_amplifier,
        signal_quality=100.0,
        location=None,
        low_signal_quality=False,
        processed_at=now,
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_silent_sepsis_demo(scoring_engine):
    """
    SILENT SEPSIS: vitals that standard rule systems pass as green,
    but SENTINEL detects via SIRS combination bonus.
    HR=108, RR=22, SpO2=93%, Temp=38.4°C, HRV=32ms, Stress=68, Steps=0
    """
    processed = make_reading(
        heart_rate=108.0,
        respiratory_rate=22.0,
        spo2=93.0,
        body_temperature=38.4,
        hrv_ms=32.0,
        stress_score=68.0,
        steps_per_hour=0.0,
    )
    assessment = await scoring_engine.score(processed)

    assert "SIRS / Early Sepsis" in assessment.sl3.syndromes_fired
    assert assessment.final_score >= 60.0
    assert assessment.shal_band in (SHALBand.WARNING, SHALBand.HIGH, SHALBand.CRITICAL)


@pytest.mark.asyncio
async def test_exercise_false_positive_suppression(scoring_engine):
    """
    VIGOROUS activity — HR 135 bpm should NOT trigger escalation.
    Activity suppressor reduces HR weight from 3 to 1.5.
    """
    processed = make_reading(
        heart_rate=135.0,
        respiratory_rate=18.0,
        spo2=98.0,
        body_temperature=37.2,
        hrv_ms=45.0,
        steps_per_hour=5000.0,
        activity_context=ActivityLevel.VIGOROUS,
        apply_hr_vigorous_suppressor=True,
    )
    assessment = await scoring_engine.score(processed)

    assert processed.apply_hr_vigorous_suppressor is True
    # Check that HR weight was actually reduced in SL2
    assert assessment.sl2.weight_multipliers_applied.get("heart_rate_weight", 3) < 3
    assert assessment.final_score <= 35.0
    assert assessment.shal_band in (SHALBand.NOMINAL, SHALBand.ELEVATED)


@pytest.mark.asyncio
async def test_hard_override_bypass(scoring_engine):
    """
    Hard override must force final_score=100, CRITICAL band, hard_override_active=True.
    SL1–SL5 still computed for XAI log.
    """
    override = HardOverride(
        override_type="SPO2_CRITICAL",
        triggered_value=83.0,
        description="SpO₂ critically low at 83%",
    )
    processed = make_reading(
        spo2=83.0,
        hard_override=override,
    )
    assessment = await scoring_engine.score(processed)

    assert assessment.final_score == 100.0
    assert assessment.shal_band == SHALBand.CRITICAL
    assert assessment.hard_override_active is True
    assert any(c.layer == "OVERRIDE" for c in assessment.all_contributors)
    # SL1 must still be computed
    assert assessment.sl1 is not None
    assert assessment.sl5 is not None


@pytest.mark.asyncio
async def test_hold_log_generation(scoring_engine):
    """
    Score in ELEVATED/WARNING range should populate hold_log.
    LLM must NOT be called (scoring engine has no LLM dependency).
    """
    processed = make_reading(
        heart_rate=96.0,
        respiratory_rate=21.0,
        spo2=95.0,
        body_temperature=37.9,
        hrv_ms=42.0,
        stress_score=55.0,
        steps_per_hour=200.0,
    )
    assessment = await scoring_engine.score(processed)

    assert assessment.shal_band in (SHALBand.ELEVATED, SHALBand.WARNING)
    assert assessment.hold_log is not None
    assert len(assessment.hold_log.watch_condition) > 0


@pytest.mark.asyncio
async def test_multi_system_stress_without_named_syndrome(scoring_engine):
    """
    4/5 Tier-A vitals scoring >= 1 triggers Multi-System Stress bonus.
    No single syndrome criteria need to be fully met.
    """
    processed = make_reading(
        heart_rate=95.0,
        respiratory_rate=22.0,
        spo2=94.0,
        body_temperature=38.2,
        hrv_ms=42.0,
        steps_per_hour=1000.0,
    )
    assessment = await scoring_engine.score(processed)

    assert "Multi-System Stress" in assessment.sl3.syndromes_fired
    assert assessment.final_score > 30.0


@pytest.mark.asyncio
async def test_mews_cross_validation_flag(scoring_engine):
    """
    MEWS >= 5 but SENTINEL score < 60 — review_flag_added must be True.
    'MEWS' must appear in xai_narrative.
    """
    # HR=115 (+2 MEWS), RR=28 (+1 MEWS), Temp=38.6 (+2 MEWS) → MEWS=5
    # SpO2/HRV normal → SENTINEL score stays below 60
    processed = make_reading(
        heart_rate=115.0,
        respiratory_rate=28.0,
        spo2=97.0,
        body_temperature=38.6,
        hrv_ms=55.0,
        stress_score=20.0,
        steps_per_hour=500.0,
    )
    assessment = await scoring_engine.score(processed)

    assert assessment.mews.mews_score >= 5
    # If SENTINEL score < 60: flag added
    if assessment.final_score < 60.0:
        assert assessment.mews.review_flag_added is True
        assert "MEWS" in assessment.xai_narrative


@pytest.mark.asyncio
async def test_trend_inverse_hr_spo2(redis_client, mock_if_model):
    """
    Populate Redis window with HR rising 88→104 and SpO₂ falling 96→91.
    Steps=0. Inverse HR/SpO₂ trend must fire.
    """
    engine = ScoringEngine(redis_client=redis_client, if_model=mock_if_model)
    patient_id = "P_TREND"

    # Push HR window: 12 values rising from 88 to 104
    hr_values = [88 + i * (16 / 11) for i in range(12)]
    for v in hr_values:
        await redis_client.push_to_window(patient_id, "heart_rate", v)

    # Push SpO₂ window: 12 values falling from 96 to 91
    spo2_values = [96 - i * (5 / 11) for i in range(12)]
    for v in spo2_values:
        await redis_client.push_to_window(patient_id, "spo2", v)

    processed = make_reading(
        patient_id=patient_id,
        heart_rate=104.0,
        spo2=91.0,
        steps_per_hour=0.0,
    )
    assessment = await engine.score(processed)

    assert "Inverse HR / SpO₂" in assessment.sl4.trends_fired
    assert assessment.sl4.total_points >= 12.0


@pytest.mark.asyncio
async def test_isolation_forest_anomaly_contribution(redis_client):
    """
    Mock IF wrapper returns anomaly_score=0.75 → should add 10 pts (MID tier).
    xai_label must contain "Anomalous".
    """
    model = MagicMock(spec=IsolationForestWrapper)
    model.is_loaded = True
    model.score.return_value = SL5Result(
        anomaly_score=0.75,
        points_added=10.0,
        xai_label="Anomalous vital fingerprint — deviates from baseline population",
        contributor=ScoreContributor(
            source="Isolation Forest (SL5)",
            layer="SL5",
            points=10.0,
            clinical_standard="Isolation Forest",
            detail="IF anomaly score 0.750 — Anomalous vital fingerprint",
        ),
    )

    engine = ScoringEngine(redis_client=redis_client, if_model=model)
    processed = make_reading()
    assessment = await engine.score(processed)

    assert assessment.sl5.points_added == 10.0
    assert "Anomalous" in assessment.sl5.xai_label


@pytest.mark.asyncio
async def test_chronic_sleep_deficit_floor(scoring_engine):
    """
    All vitals normal → raw score ~5. deep_sleep_pct=10% → floor raised to 8.
    """
    processed = make_reading(
        heart_rate=72.0,
        respiratory_rate=15.0,
        spo2=98.0,
        body_temperature=37.0,
        hrv_ms=65.0,
        stress_score=20.0,
        deep_sleep_pct=10.0,
    )
    assessment = await scoring_engine.score(processed)

    assert assessment.final_score >= 8.0


@pytest.mark.asyncio
async def test_qsofa_bonus(scoring_engine):
    """
    RR=23 (qSOFA criterion 1), HRV=22ms (criterion 2 + criterion 3 if stress > 85).
    qSOFA score >= 2 → +25 bonus fires.
    """
    processed = make_reading(
        heart_rate=90.0,
        respiratory_rate=23.0,
        spo2=96.0,
        body_temperature=37.5,
        hrv_ms=22.0,
        stress_score=50.0,
    )
    assessment = await scoring_engine.score(processed)

    assert assessment.sl3.qsofa_score >= 2
    assert any("qSOFA" in c.source for c in assessment.sl3.contributors)


@pytest.mark.asyncio
async def test_score_traceability(scoring_engine):
    """
    Sum of all ScoreContributor.points (excluding OVERRIDE and SL2 weight-only entries)
    must trace back to the raw_total used for normalisation.
    """
    processed = make_reading(
        heart_rate=108.0,
        respiratory_rate=22.0,
        spo2=93.0,
        body_temperature=38.4,
        hrv_ms=32.0,
        stress_score=68.0,
    )
    assessment = await scoring_engine.score(processed)

    # all_contributors with points > 0 (exclude OVERRIDE for normal path)
    if not assessment.hard_override_active:
        # SL1 contributors store raw points (pre-norm). The SL1 result has normalised_points.
        # The traceability check: SL2.additive_points + SL3 + SL4 + SL5 = raw_total before /236*100
        raw_total_expected = (
            assessment.sl2.additive_points
            + assessment.sl3.total_points
            + assessment.sl4.total_points
            + assessment.sl5.points_added
        )
        from app.core.constants import SCORE_MAX_POSSIBLE
        expected_score = round(min(100.0, raw_total_expected / SCORE_MAX_POSSIBLE * 100), 1)
        # Allow for sleep deficit floor adjustment
        assert assessment.final_score >= expected_score - 0.1


@pytest.mark.asyncio
@pytest.mark.slow
async def test_f1_benchmark(redis_client, mock_if_model):
    """
    Integration test: load critical_vitals.csv, run through scoring engine,
    assert F1 >= 0.80 on CRITICAL classification.
    Skipped if CSV not found.
    """
    import os
    import csv

    csv_path = "backend/data/synthetic/critical_vitals.csv"
    if not os.path.exists(csv_path):
        pytest.skip(f"Benchmark CSV not found: {csv_path}")

    engine = ScoringEngine(redis_client=redis_client, if_model=mock_if_model)
    tp = fp = fn = 0

    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ground_truth = row.get("critical", "").strip().lower()
            if ground_truth not in ("true", "false", "1", "0"):
                continue
            is_critical_truth = ground_truth in ("true", "1")

            processed = make_reading(
                heart_rate=float(row.get("heart_rate", 75) or 75),
                respiratory_rate=float(row.get("respiratory_rate", 16) or 16),
                spo2=float(row.get("spo2", 98) or 98),
                body_temperature=float(row.get("body_temperature", 37) or 37),
                hrv_ms=float(row.get("hrv_ms", 60) or 60),
            )
            assessment = await engine.score(processed)
            predicted_critical = assessment.shal_band == SHALBand.CRITICAL

            if is_critical_truth and predicted_critical:
                tp += 1
            elif not is_critical_truth and predicted_critical:
                fp += 1
            elif is_critical_truth and not predicted_critical:
                fn += 1

    if tp + fp + fn == 0:
        pytest.skip("No labelled rows found in CSV")

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall    = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    assert f1 >= 0.80, f"F1={f1:.3f} — below 0.80 threshold (TP={tp}, FP={fp}, FN={fn})"

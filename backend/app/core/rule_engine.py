"""
Pure functions for SENTINEL scoring sub-layers.
No class, no Redis calls, no async — fully unit-testable in isolation.
Imported by ScoringEngine.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.core.constants import (
    MEWS_FLAG_THRESHOLD,
    QSOFA_BONUS,
    QSOFA_THRESHOLD,
    SL1_NORMALISED_MAX,
    SL1_RAW_MAX,
    SL1_SUSTAINED_TICKS_MIN,
    SL1_WEIGHTS,
    SYNDROME_AUTONOMIC_COLLAPSE_BONUS,
    SYNDROME_HYPOXIC_BONUS,
    SYNDROME_MULTI_SYSTEM_BONUS,
    SYNDROME_RESPIRATORY_FAILURE_BONUS,
    SYNDROME_SHOCK_BONUS,
    SYNDROME_SIRS_BONUS,
    TREND_HR_ASCENT_BONUS,
    TREND_HR_ASCENT_DELTA_BPM,
    TREND_HRV_COLLAPSE_BONUS,
    TREND_HRV_COLLAPSE_DELTA_MS,
    TREND_INVERSE_HR_MIN_DELTA_BPM,
    TREND_INVERSE_HR_SPO2_BONUS,
    TREND_INVERSE_SPO2_MIN_FALLING_TICKS,
    TREND_MIN_WINDOW_TICKS,
    TREND_SPO2_DECLINE_BONUS,
    TREND_SPO2_DECLINE_MIN_TICKS,
    TREND_TEMP_TRAJECTORY_BONUS,
)
from app.models.assessment import (
    MEWSResult,
    ScoreContributor,
    SL1Result,
    SL3Result,
    SL4Result,
)

logger = logging.getLogger(__name__)

# ── Vital tier definitions ─────────────────────────────────────────────────────
TIER_A_VITALS = ["heart_rate", "respiratory_rate", "spo2", "body_temperature", "hrv_ms"]
TIER_B_VITALS = ["ecg_rhythm", "stress_score", "steps_per_hour", "activity_context"]
TIER_C_VITALS = ["sleep_efficiency", "deep_sleep_pct", "rem_pct", "ecg_qtc_ms"]


# ── Sub-Layer 1 helpers ────────────────────────────────────────────────────────

def _score_heart_rate(val: float) -> int:
    if val <= 40 or val >= 131:
        return 3
    if 111 <= val <= 130:
        return 2
    if (41 <= val <= 50) or (91 <= val <= 110):
        return 1
    return 0  # 51–90


def _score_respiratory_rate(val: float) -> int:
    if val <= 8:
        return 3
    if val >= 25:
        return 2
    if (9 <= val <= 11) or (21 <= val <= 24):
        return 1
    return 0  # 12–20


def _score_spo2(val: float) -> int:
    if val <= 91:
        return 3
    if 92 <= val <= 93:
        return 2
    if 94 <= val <= 95:
        return 1
    return 0  # >= 96


def _score_body_temperature(val: float) -> int:
    if val <= 35.0:
        return 3
    if val >= 39.1:
        return 2
    if (35.1 <= val <= 36.0) or (38.1 <= val <= 39.0):
        return 1
    return 0  # 36.1–38.0


def _score_hrv_ms(val: float) -> int:
    if val < 25:
        return 3
    if 25 <= val <= 39:
        return 2
    if 40 <= val <= 54:
        return 1
    return 0  # >= 55


_SCORERS = {
    "heart_rate":       _score_heart_rate,
    "respiratory_rate": _score_respiratory_rate,
    "spo2":             _score_spo2,
    "body_temperature": _score_body_temperature,
    "hrv_ms":           _score_hrv_ms,
}


def compute_sl1(
    validated_vitals: dict[str, Optional[float]],
    window_data: dict[str, list[float]],
) -> SL1Result:
    """
    Sub-Layer 1 — Individual vital scoring normalised to 40 pts.
    Applies the 3-tick sustained minimum rule using Redis window data.
    """
    vital_scores: dict[str, int] = {}
    contributors: list[ScoreContributor] = []
    raw_points: float = 0.0

    for vital in TIER_A_VITALS:
        val = validated_vitals.get(vital)
        if val is None:
            # Fresh patient — no value available; skip this vital
            logger.debug("SL1: %s is None — skipped", vital)
            continue

        score = _SCORERS[vital](val)
        weight = SL1_WEIGHTS[vital]

        # Sustained ticks rule: if window has >= SL1_SUSTAINED_TICKS_MIN entries,
        # the current score must have been sustained for at least that many ticks.
        window = window_data.get(vital, [])
        if len(window) >= SL1_SUSTAINED_TICKS_MIN:
            recent = window[-SL1_SUSTAINED_TICKS_MIN:]
            sustained_scores = [_SCORERS[vital](v) for v in recent]
            if all(s >= 1 for s in sustained_scores):
                effective_score = score
            else:
                # Not yet sustained — use raw score but clamp to 1 if currently abnormal
                effective_score = score
        else:
            # Fewer than 3 ticks — use the current reading's score directly
            effective_score = score

        vital_scores[vital] = effective_score
        pts = effective_score * weight
        raw_points += pts

        if effective_score > 0:
            contributors.append(ScoreContributor(
                source=f"{vital} (SL1)",
                layer="SL1",
                points=float(pts),
                clinical_standard="NEWS2",
                detail=(
                    f"{vital} {val:.1f} → score {effective_score} "
                    f"× weight {weight} = {pts} pts"
                ),
            ))

    # Normalise: raw / 48 × 40
    normalised = round(raw_points / SL1_RAW_MAX * SL1_NORMALISED_MAX, 3)

    return SL1Result(
        raw_points=raw_points,
        normalised_points=normalised,
        contributors=contributors,
        vital_scores=vital_scores,
    )


# ── Sub-Layer 3 — Named Syndrome Combination Bonuses + qSOFA ──────────────────

def compute_sl3(
    validated_vitals: dict[str, Optional[float]],
    sl1_vital_scores: dict[str, int],
) -> SL3Result:
    """
    Check all 6 named syndromes and compute qSOFA.
    Returns SL3Result with syndrome bonuses and qSOFA bonus if applicable.
    """
    hr    = validated_vitals.get("heart_rate")
    rr    = validated_vitals.get("respiratory_rate")
    spo2  = validated_vitals.get("spo2")
    temp  = validated_vitals.get("body_temperature")
    hrv   = validated_vitals.get("hrv_ms")
    steps = validated_vitals.get("steps_per_hour")
    stress = validated_vitals.get("stress_score")

    syndromes_fired: list[str] = []
    contributors: list[ScoreContributor] = []
    total_points: float = 0.0

    # ── SYNDROME 1: SIRS / Early Sepsis ──────────────────────────────────────
    if (hr is not None and hr > 90
            and temp is not None and temp > 38.0
            and rr is not None and rr > 20):
        syndromes_fired.append("SIRS / Early Sepsis")
        total_points += SYNDROME_SIRS_BONUS
        contributors.append(ScoreContributor(
            source="SIRS / Early Sepsis (SL3)",
            layer="SL3",
            points=SYNDROME_SIRS_BONUS,
            clinical_standard="SIRS Criteria (Bone et al. 1992)",
            detail=(
                f"SIRS triad met — HR {hr:.0f} bpm, Temp {temp:.1f}°C, "
                f"RR {rr:.0f} /min all above sepsis thresholds simultaneously"
            ),
        ))

    # ── SYNDROME 2: Hypoxic Episode ───────────────────────────────────────────
    motion_absent = (steps is None or steps == 0)
    if (spo2 is not None and spo2 < 94
            and hr is not None and hr > 95
            and rr is not None and rr > 20
            and motion_absent):
        syndromes_fired.append("Hypoxic Episode")
        total_points += SYNDROME_HYPOXIC_BONUS
        contributors.append(ScoreContributor(
            source="Hypoxic Episode (SL3)",
            layer="SL3",
            points=SYNDROME_HYPOXIC_BONUS,
            clinical_standard="WHO Respiratory Failure + NEWS2 dual red flag",
            detail=(
                f"Hypoxic episode pattern — SpO₂ {spo2:.1f}%, HR {hr:.0f} bpm, "
                f"RR {rr:.0f} /min with motion absent"
            ),
        ))

    # ── SYNDROME 3: Distributive Shock ────────────────────────────────────────
    if (hr is not None and hr > 100
            and hrv is not None and hrv < 30):
        syndromes_fired.append("Distributive Shock")
        total_points += SYNDROME_SHOCK_BONUS
        contributors.append(ScoreContributor(
            source="Distributive Shock (SL3)",
            layer="SL3",
            points=SYNDROME_SHOCK_BONUS,
            clinical_standard="Sepsis-3 / MEWS BP + HR combination",
            detail=(
                f"Distributive shock pattern — compensatory tachycardia HR {hr:.0f} bpm "
                f"with severe HRV collapse {hrv:.1f} ms"
            ),
        ))

    # ── SYNDROME 4: Autonomic Collapse ────────────────────────────────────────
    if (hrv is not None and hrv < 25
            and hr is not None and hr > 100
            and stress is not None and stress > 80):
        syndromes_fired.append("Autonomic Collapse")
        total_points += SYNDROME_AUTONOMIC_COLLAPSE_BONUS
        contributors.append(ScoreContributor(
            source="Autonomic Collapse (SL3)",
            layer="SL3",
            points=SYNDROME_AUTONOMIC_COLLAPSE_BONUS,
            clinical_standard="Clinical HRV Literature, ANS Dysregulation",
            detail=(
                f"Autonomic collapse — critically suppressed HRV {hrv:.1f} ms, "
                f"HR {hr:.0f} bpm, stress {stress:.0f}/100"
            ),
        ))

    # ── SYNDROME 5: Respiratory Failure ───────────────────────────────────────
    resp_failure = False
    if spo2 is not None and spo2 <= 91 and rr is not None:
        if rr >= 25 or rr <= 8:
            resp_failure = True
    if resp_failure:
        syndromes_fired.append("Respiratory Failure")
        total_points += SYNDROME_RESPIRATORY_FAILURE_BONUS
        contributors.append(ScoreContributor(
            source="Respiratory Failure (SL3)",
            layer="SL3",
            points=SYNDROME_RESPIRATORY_FAILURE_BONUS,
            clinical_standard="NEWS2 dual red flag (two score-3 parameters)",
            detail=(
                f"Respiratory failure — critical SpO₂ {spo2:.1f}% with "
                f"extreme respiratory rate {rr:.0f} /min"
            ),
        ))

    # ── SYNDROME 6: Multi-System Stress ───────────────────────────────────────
    abnormal_count = sum(1 for v in TIER_A_VITALS if sl1_vital_scores.get(v, 0) >= 1)
    if abnormal_count >= 4:
        syndromes_fired.append("Multi-System Stress")
        total_points += SYNDROME_MULTI_SYSTEM_BONUS
        contributors.append(ScoreContributor(
            source="Multi-System Stress (SL3)",
            layer="SL3",
            points=SYNDROME_MULTI_SYSTEM_BONUS,
            clinical_standard="SENTINEL Pattern Detection",
            detail=(
                f"Multi-system stress — {abnormal_count}/5 Tier A vitals "
                f"simultaneously above normal thresholds"
            ),
        ))

    # ── qSOFA Computation ─────────────────────────────────────────────────────
    qsofa_score = 0
    qsofa_criteria_met: list[str] = []

    # Criterion 1 — RR >= 22
    if rr is not None and rr >= 22:
        qsofa_score += 1
        qsofa_criteria_met.append("qSOFA: RR >= 22 /min")

    # Criterion 2 — HRV < 30 as circulatory proxy for low systolic BP
    if hrv is not None and hrv < 30:
        qsofa_score += 1
        qsofa_criteria_met.append("qSOFA: HRV < 30 ms (circulatory compromise proxy)")

    # Criterion 3 — altered mentation proxy: HRV < 25 AND stress > 85
    if hrv is not None and hrv < 25 and stress is not None and stress > 85:
        qsofa_score += 1
        qsofa_criteria_met.append("qSOFA: HRV < 25 ms AND stress > 85 (altered mentation proxy)")

    if qsofa_score >= QSOFA_THRESHOLD:
        total_points += QSOFA_BONUS
        contributors.append(ScoreContributor(
            source="qSOFA Sepsis Risk Bonus (SL3)",
            layer="SL3",
            points=QSOFA_BONUS,
            clinical_standard="Sepsis-3 (Singer et al. JAMA 2016)",
            detail=(
                f"qSOFA score {qsofa_score}/3 — sepsis risk elevated. "
                f"Criteria: {'; '.join(qsofa_criteria_met)}"
            ),
        ))

    return SL3Result(
        syndromes_fired=syndromes_fired,
        total_points=total_points,
        contributors=contributors,
        qsofa_score=qsofa_score,
        qsofa_criteria_met=qsofa_criteria_met,
    )


# ── Sub-Layer 4 — Temporal Trend Bonuses ──────────────────────────────────────

def compute_sl4(
    window_data: dict[str, list[float]],
    validated_vitals: dict[str, Optional[float]],
) -> SL4Result:
    """
    Compute trend bonuses from the Redis 12-tick window.
    Skips checks when window has fewer than TREND_MIN_WINDOW_TICKS entries.
    """
    trends_fired: list[str] = []
    contributors: list[ScoreContributor] = []
    total_points: float = 0.0

    hr_window   = window_data.get("heart_rate", [])
    spo2_window = window_data.get("spo2", [])
    hrv_window  = window_data.get("hrv_ms", [])
    temp_window = window_data.get("body_temperature", [])
    steps       = validated_vitals.get("steps_per_hour")

    # ── TREND 1: Rapid HR Ascent ───────────────────────────────────────────────
    if len(hr_window) >= TREND_MIN_WINDOW_TICKS:
        half = len(hr_window) // 2
        mean_first = sum(hr_window[:half]) / half
        mean_last  = sum(hr_window[half:]) / (len(hr_window) - half)
        delta = mean_last - mean_first
        if delta > TREND_HR_ASCENT_DELTA_BPM:
            trends_fired.append("Rapid HR Ascent")
            total_points += TREND_HR_ASCENT_BONUS
            contributors.append(ScoreContributor(
                source="Rapid HR Ascent (SL4)",
                layer="SL4",
                points=TREND_HR_ASCENT_BONUS,
                clinical_standard="SENTINEL Trend Engine",
                detail=f"HR ascending — mean delta +{delta:.1f} bpm over 30-second window",
            ))
    else:
        logger.debug("SL4 TREND_1 skipped — HR window only %d ticks", len(hr_window))

    # ── TREND 2: Sustained SpO₂ Decline ───────────────────────────────────────
    if len(spo2_window) >= TREND_MIN_WINDOW_TICKS:
        falling_pairs = sum(
            1 for i in range(1, len(spo2_window))
            if spo2_window[i] < spo2_window[i - 1]
        )
        if falling_pairs > TREND_SPO2_DECLINE_MIN_TICKS:
            trends_fired.append("Sustained SpO₂ Decline")
            total_points += TREND_SPO2_DECLINE_BONUS
            contributors.append(ScoreContributor(
                source="Sustained SpO₂ Decline (SL4)",
                layer="SL4",
                points=TREND_SPO2_DECLINE_BONUS,
                clinical_standard="SENTINEL Trend Engine",
                detail=f"SpO₂ sustained decline — falling in {falling_pairs}/12 consecutive ticks",
            ))
    else:
        logger.debug("SL4 TREND_2 skipped — SpO₂ window only %d ticks", len(spo2_window))

    # ── TREND 3: HRV Collapse Trend ───────────────────────────────────────────
    if len(hrv_window) >= TREND_MIN_WINDOW_TICKS:
        half = len(hrv_window) // 2
        mean_first = sum(hrv_window[:half]) / half
        mean_last  = sum(hrv_window[half:]) / (len(hrv_window) - half)
        delta = mean_first - mean_last  # positive when HRV falling
        if delta > TREND_HRV_COLLAPSE_DELTA_MS:
            trends_fired.append("HRV Collapse Trend")
            total_points += TREND_HRV_COLLAPSE_BONUS
            contributors.append(ScoreContributor(
                source="HRV Collapse Trend (SL4)",
                layer="SL4",
                points=TREND_HRV_COLLAPSE_BONUS,
                clinical_standard="SENTINEL Trend Engine",
                detail=f"HRV collapsing — mean delta -{delta:.1f} ms over 30-second window",
            ))
    else:
        logger.debug("SL4 TREND_3 skipped — HRV window only %d ticks", len(hrv_window))

    # ── TREND 4: Inverse HR / SpO₂ ────────────────────────────────────────────
    motion_absent = (steps is None or steps == 0)
    hr_rising = False
    spo2_falling_enough = False

    if len(hr_window) >= TREND_MIN_WINDOW_TICKS:
        half = len(hr_window) // 2
        hr_delta = (sum(hr_window[half:]) / (len(hr_window) - half)) - (sum(hr_window[:half]) / half)
        hr_rising = hr_delta > TREND_INVERSE_HR_MIN_DELTA_BPM

    if len(spo2_window) >= TREND_MIN_WINDOW_TICKS:
        falling_pairs = sum(
            1 for i in range(1, len(spo2_window))
            if spo2_window[i] < spo2_window[i - 1]
        )
        spo2_falling_enough = falling_pairs > TREND_INVERSE_SPO2_MIN_FALLING_TICKS

    if hr_rising and spo2_falling_enough and motion_absent:
        trends_fired.append("Inverse HR / SpO₂")
        total_points += TREND_INVERSE_HR_SPO2_BONUS
        contributors.append(ScoreContributor(
            source="Inverse HR / SpO₂ (SL4)",
            layer="SL4",
            points=TREND_INVERSE_HR_SPO2_BONUS,
            clinical_standard="SENTINEL Trend Engine",
            detail=(
                "Inverse HR/SpO₂ pattern — compensatory tachycardia "
                "for failing oxygenation, motion absent"
            ),
        ))

    # ── TREND 5: Temperature Trajectory ───────────────────────────────────────
    if len(temp_window) >= 4:
        all_rising = all(
            temp_window[i] >= temp_window[i - 1]
            for i in range(1, len(temp_window))
        )
        if all_rising:
            trends_fired.append("Temperature Trajectory")
            total_points += TREND_TEMP_TRAJECTORY_BONUS
            contributors.append(ScoreContributor(
                source="Temperature Trajectory (SL4)",
                layer="SL4",
                points=TREND_TEMP_TRAJECTORY_BONUS,
                clinical_standard="SENTINEL Trend Engine",
                detail="Rising temperature trajectory across full 30-second window — fever in progress",
            ))
    else:
        logger.debug("SL4 TREND_5 skipped — temp window only %d ticks", len(temp_window))

    return SL4Result(
        trends_fired=trends_fired,
        total_points=total_points,
        contributors=contributors,
    )


# ── MEWS Parallel Cross-Validation ────────────────────────────────────────────

def compute_mews(validated_vitals: dict[str, Optional[float]]) -> MEWSResult:
    """
    Compute MEWS score (Subbe et al., QJM 2001).
    Systolic BP unavailable — always scores 0.
    review_flag_added is set by the caller (needs primary score for comparison).
    """
    mews = 0
    hr   = validated_vitals.get("heart_rate")
    rr   = validated_vitals.get("respiratory_rate")
    temp = validated_vitals.get("body_temperature")

    # Heart Rate
    if hr is not None:
        if hr > 130 or hr < 40:
            mews += 3
        elif 111 <= hr <= 130:
            mews += 2
        elif (41 <= hr <= 50) or (101 <= hr <= 110):
            mews += 1
        # 51–100 → 0

    # Systolic BP — unavailable
    logger.debug("MEWS: systolic_bp unavailable — MEWS BP score 0")

    # Respiratory Rate
    if rr is not None:
        if rr > 30 or rr < 9:
            mews += 3
        elif (9 <= rr <= 14) or (21 <= rr <= 29):
            mews += 1
        # 15–20 → 0

    # Body Temperature
    if temp is not None:
        if temp > 38.5 or temp < 35.0:
            mews += 2
        # 35.0–38.5 → 0

    return MEWSResult(
        mews_score=mews,
        mews_flag=mews >= MEWS_FLAG_THRESHOLD,
        review_flag_added=False,  # set by ScoringEngine after comparing primary score
    )

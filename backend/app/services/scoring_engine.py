"""
ScoringEngine — Component 3 of SENTINEL.
Receives a ProcessedReading and returns a fully-traceable RiskAssessment.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from app.core.constants import (
    ACTIVITY_SEDENTARY_HR_WEIGHT_MULTIPLIER,
    ACTIVITY_VIGOROUS_HR_WEIGHT_MULTIPLIER,
    ACTIVITY_VIGOROUS_HRV_WEIGHT_MULTIPLIER,
    DEEP_SLEEP_DEFICIT_FLOOR_SCORE,
    DEEP_SLEEP_DEFICIT_THRESHOLD_PCT,
    ECG_ARRHYTHMIA_HR_WEIGHT_MULTIPLIER,
    HOLD_LOG_HISTORY_KEY,
    HOLD_LOG_HISTORY_MAX,
    HOLD_LOG_LATEST_KEY,
    HRV_ACUTE_DROP_ADDITIVE_POINTS,
    MEWS_FLAG_THRESHOLD,
    SHAL_ELEVATED_MAX,
    SHAL_HIGH_MAX,
    SHAL_NOMINAL_MAX,
    SHAL_WARNING_MAX,
    SL1_NORMALISED_MAX,
    SL1_RAW_MAX,
    SL1_WEIGHTS,
    STRESS_SCORE_ADDITIVE_POINTS,
    STRESS_SCORE_MODIFIER_THRESHOLD,
    TIER_A_VITALS,
)
from app.core.redis_client import RedisClient
from app.core.rule_engine import (
    TIER_A_VITALS as RE_TIER_A,
    compute_mews,
    compute_sl1,
    compute_sl3,
    compute_sl4,
    _SCORERS,
)
from app.ml.isolation_forest import IsolationForestWrapper
from app.models.assessment import (
    HOLDLogEntry,
    MEWSResult,
    RiskAssessment,
    ScoreContributor,
    SHALBand,
    SL1Result,
    SL2Result,
    SL3Result,
    SL4Result,
    SL5Result,
)
from app.models.vitals import ECGRhythm, ProcessedReading

logger = logging.getLogger(__name__)


def _classify_band(score: float) -> SHALBand:
    if score <= SHAL_NOMINAL_MAX:
        return SHALBand.NOMINAL
    if score <= SHAL_ELEVATED_MAX:
        return SHALBand.ELEVATED
    if score <= SHAL_WARNING_MAX:
        return SHALBand.WARNING
    if score <= SHAL_HIGH_MAX:
        return SHALBand.HIGH
    return SHALBand.CRITICAL


def _build_watch_condition(
    validated_vitals: dict[str, Optional[float]],
    sl3: SL3Result,
    sl1_scores: dict[str, int],
) -> str:
    """
    Generate a clinically meaningful HOLD watch condition sentence.
    Finds the Tier-A vital closest to its next threshold boundary.
    """
    # Nearest-threshold logic per vital
    thresholds = {
        "heart_rate":       [(90.0, "HR > 90 bpm"), (100.0, "HR > 100 bpm"), (130.0, "HR > 130 bpm")],
        "spo2":             [(95.0, "SpO₂ < 95%"), (93.0, "SpO₂ < 93%"), (91.0, "SpO₂ < 91%")],
        "respiratory_rate": [(20.0, "RR > 20 /min"), (24.0, "RR > 24 /min"), (30.0, "RR > 30 /min")],
        "body_temperature": [(37.5, "Temp > 37.5°C"), (38.0, "Temp > 38.0°C"), (39.0, "Temp > 39.0°C")],
        "hrv_ms":           [(55.0, "HRV < 55 ms"), (40.0, "HRV < 40 ms"), (25.0, "HRV < 25 ms")],
    }

    watch_parts: list[str] = []
    for vital, val in validated_vitals.items():
        if val is None or vital not in thresholds:
            continue
        for threshold, label in thresholds[vital]:
            if vital == "spo2" or vital == "hrv_ms":
                # lower is worse
                if val > threshold:
                    watch_parts.append(f"{vital} {val:.1f} approaching {label}")
                    break
            else:
                if val < threshold:
                    watch_parts.append(f"{vital} {val:.1f} approaching {label}")
                    break

    # Syndrome almost-fired detection
    almost_syndromes: list[str] = []
    hr    = validated_vitals.get("heart_rate")
    rr    = validated_vitals.get("respiratory_rate")
    temp  = validated_vitals.get("body_temperature")
    spo2  = validated_vitals.get("spo2")
    hrv   = validated_vitals.get("hrv_ms")
    stress = validated_vitals.get("stress_score")

    # SIRS: check if 2/3 criteria met
    sirs_count = sum([
        hr is not None and hr > 90,
        temp is not None and temp > 38.0,
        rr is not None and rr > 20,
    ])
    if sirs_count == 2 and "SIRS / Early Sepsis" not in sl3.syndromes_fired:
        missing = []
        if hr is None or hr <= 90:    missing.append(f"HR > 90 (currently {hr:.0f})" if hr else "HR > 90")
        if temp is None or temp <= 38: missing.append(f"Temp > 38.0°C (currently {temp:.1f}°C)" if temp else "Temp > 38.0°C")
        if rr is None or rr <= 20:    missing.append(f"RR > 20 (currently {rr:.0f})" if rr else "RR > 20")
        almost_syndromes.append(f"SIRS triad not yet complete — missing {'; '.join(missing)}")

    condition_parts = watch_parts[:2] + almost_syndromes[:1]
    if condition_parts:
        base = ". ".join(condition_parts)
        return f"{base}. Will escalate if thresholds exceeded within 5 minutes."
    return "Monitoring all Tier-A vitals. Will escalate if any critical threshold is breached."


def _build_xai_narrative(
    all_contributors: list[ScoreContributor],
    sl3: SL3Result,
    sl4: SL4Result,
    sl5: SL5Result,
    mews: MEWSResult,
    final_score: float,
    shal_band: SHALBand,
    hard_override: bool,
    override_type: Optional[str],
) -> str:
    parts: list[str] = []

    if hard_override and override_type:
        parts.append(f"HARD OVERRIDE triggered: {override_type} — automatic CRITICAL escalation.")

    # Highest-scoring non-override contributors
    non_override = [c for c in all_contributors if c.layer != "OVERRIDE"]
    if non_override:
        top = max(non_override, key=lambda c: c.points)
        parts.append(f"Top contributor: {top.source} (+{top.points:.0f} pts) — {top.detail}")

    if sl3.syndromes_fired:
        parts.append(
            f"Named syndromes fired: {', '.join(sl3.syndromes_fired)}."
        )

    if sl4.trends_fired:
        parts.append(
            f"Temporal trends detected: {', '.join(sl4.trends_fired)}."
        )

    if sl5.points_added > 0:
        parts.append(
            f"Isolation Forest anomaly score {sl5.anomaly_score:.2f} — {sl5.xai_label} "
            f"(+{sl5.points_added:.0f} pts)."
        )

    band_meanings = {
        SHALBand.NOMINAL:  "Routine monitoring.",
        SHALBand.ELEVATED: "Increased vigilance recommended.",
        SHALBand.WARNING:  "Clinical review within 30 minutes.",
        SHALBand.HIGH:     "Urgent clinical review required.",
        SHALBand.CRITICAL: "Autonomous escalation triggered.",
    }
    parts.append(
        f"Final score: {final_score:.1f}/100 — {shal_band.value} band. "
        f"{band_meanings[shal_band]}"
    )

    if mews.review_flag_added:
        parts.append(
            "MEWS ≥ 5 — manual clinical review recommended despite primary score "
            "(86% sensitivity for ICU admission, Subbe et al. QJM 2001)."
        )

    return " ".join(parts)


class ScoringEngine:
    """
    Main scoring orchestrator for SENTINEL.
    Injected with RedisClient and IsolationForestWrapper.
    """

    def __init__(
        self,
        redis_client: RedisClient,
        if_model: IsolationForestWrapper,
    ) -> None:
        self.redis    = redis_client
        self.if_model = if_model

    async def score(self, processed: ProcessedReading) -> RiskAssessment:
        now = datetime.now(timezone.utc)
        patient_id = processed.original.patient_id
        session_id = processed.original.session_id
        reading_id = processed.original.reading_id
        validated  = processed.validated_vitals

        # ── Step 1: Retrieve Redis windows ────────────────────────────────────
        window_data: dict[str, list[float]] = {}
        for vital in RE_TIER_A:
            window_data[vital] = await self.redis.get_window(patient_id, vital)

        # ── Step 2: Compute SL1 ───────────────────────────────────────────────
        sl1 = compute_sl1(validated, window_data)

        # ── Step 3: Compute SL2 (weight modifiers + additive bonuses) ─────────
        sl2 = self._compute_sl2(processed, validated, sl1)

        # ── Step 4: Compute SL3 (syndromes + qSOFA) ───────────────────────────
        sl3 = compute_sl3(validated, sl1.vital_scores)

        # ── Step 5: Compute SL4 (trend bonuses) ───────────────────────────────
        sl4 = compute_sl4(window_data, validated)

        # ── Step 6: Compute SL5 (Isolation Forest) ────────────────────────────
        sl5 = self.if_model.score(validated)

        # ── Step 7: MEWS cross-validation ─────────────────────────────────────
        mews_result = compute_mews(validated)

        # ── Step 8: Final score assembly ──────────────────────────────────────
        # modified_sl1_points is the SL1 contribution AFTER SL2 weight modifiers
        modified_sl1_points = sl2.additive_points  # SL2 already includes SL1 re-weighted sum
        raw_total = modified_sl1_points + sl3.total_points + sl4.total_points + sl5.points_added
        # Points from SL3/SL4/SL5 are already on the 0-100 scale (each bonus is a
        # direct final-score contribution).  SL1/SL2 contribute up to ~50 pts.
        # Cap at 100 — no division by MAX_POSSIBLE.
        final_score = round(min(100.0, raw_total), 1)

        # Sleep deficit baseline floor
        deep_sleep = validated.get("deep_sleep_pct")
        if deep_sleep is not None and deep_sleep < DEEP_SLEEP_DEFICIT_THRESHOLD_PCT:
            if final_score < DEEP_SLEEP_DEFICIT_FLOOR_SCORE:
                final_score = DEEP_SLEEP_DEFICIT_FLOOR_SCORE

        # MEWS review flag
        if mews_result.mews_score >= MEWS_FLAG_THRESHOLD and final_score < 60.0:
            mews_result = MEWSResult(
                mews_score=mews_result.mews_score,
                mews_flag=mews_result.mews_flag,
                review_flag_added=True,
            )

        shal_band = _classify_band(final_score)

        # ── Flat contributor list ──────────────────────────────────────────────
        all_contributors: list[ScoreContributor] = []
        all_contributors.extend(sl1.contributors)
        all_contributors.extend(sl2.contributors)
        all_contributors.extend(sl3.contributors)
        all_contributors.extend(sl4.contributors)
        if sl5.contributor:
            all_contributors.append(sl5.contributor)

        # ── Hard Override fast path ────────────────────────────────────────────
        hard_override_active = False
        hard_override_type: Optional[str] = None

        if processed.hard_override is not None:
            hard_override_active = True
            hard_override_type = processed.hard_override.override_type
            final_score = 100.0
            shal_band   = SHALBand.CRITICAL
            all_contributors.append(ScoreContributor(
                source=f"Hard Override: {processed.hard_override.override_type}",
                layer="OVERRIDE",
                points=100.0,
                clinical_standard="SENTINEL Hard Override",
                detail=processed.hard_override.description,
            ))

        # ── HOLD log ──────────────────────────────────────────────────────────
        hold_log: Optional[HOLDLogEntry] = None
        if shal_band in (SHALBand.ELEVATED, SHALBand.WARNING) and not hard_override_active:
            watch_cond = _build_watch_condition(validated, sl3, sl1.vital_scores)
            hold_log = HOLDLogEntry(
                patient_id=patient_id,
                session_id=session_id,
                timestamp=now,
                shal_band=shal_band,
                score=final_score,
                watch_condition=watch_cond,
                vitals_snapshot={k: v for k, v in validated.items()},
                contributors=all_contributors[:],
            )
            await self._store_hold_log(patient_id, hold_log)

        # ── XAI narrative ─────────────────────────────────────────────────────
        xai = _build_xai_narrative(
            all_contributors=all_contributors,
            sl3=sl3,
            sl4=sl4,
            sl5=sl5,
            mews=mews_result,
            final_score=final_score,
            shal_band=shal_band,
            hard_override=hard_override_active,
            override_type=hard_override_type,
        )

        return RiskAssessment(
            patient_id=patient_id,
            session_id=session_id,
            reading_id=reading_id,
            timestamp=processed.original.timestamp,
            final_score=final_score,
            shal_band=shal_band,
            hard_override_active=hard_override_active,
            hard_override_type=hard_override_type,
            sl1=sl1,
            sl2=sl2,
            sl3=sl3,
            sl4=sl4,
            sl5=sl5,
            mews=mews_result,
            all_contributors=all_contributors,
            hold_log=hold_log,
            xai_narrative=xai,
            assessed_at=now,
        )

    # ── SL2 computation (weight modifiers + additive bonuses) ─────────────────

    def _compute_sl2(
        self,
        processed: ProcessedReading,
        validated: dict[str, Optional[float]],
        sl1: SL1Result,
    ) -> SL2Result:
        contributors: list[ScoreContributor] = []
        weight_multipliers_applied: dict[str, float] = {}

        # Start with base SL1 weights
        weights = dict(SL1_WEIGHTS)

        ecg_rhythm = processed.original.ecg_rhythm
        vigorous   = processed.apply_hr_vigorous_suppressor
        sedentary  = processed.apply_hr_sedentary_amplifier

        # Modifier precedence: Activity Suppressor > ECG Amplifier > Sedentary Amplifier
        if vigorous:
            weights["heart_rate"] = round(SL1_WEIGHTS["heart_rate"] * ACTIVITY_VIGOROUS_HR_WEIGHT_MULTIPLIER, 3)
            weights["hrv_ms"]     = round(SL1_WEIGHTS["hrv_ms"]     * ACTIVITY_VIGOROUS_HRV_WEIGHT_MULTIPLIER, 3)
            weight_multipliers_applied["heart_rate_weight"] = weights["heart_rate"]
            weight_multipliers_applied["hrv_ms_weight"]     = weights["hrv_ms"]
            contributors.append(ScoreContributor(
                source="Activity Suppressor (SL2)",
                layer="SL2",
                points=0.0,
                clinical_standard="SENTINEL Contextual Modifier",
                detail="Vigorous activity detected — HR and HRV weights suppressed",
            ))
        elif ecg_rhythm in (ECGRhythm.AFIB, ECGRhythm.VT):
            weights["heart_rate"] = round(SL1_WEIGHTS["heart_rate"] * ECG_ARRHYTHMIA_HR_WEIGHT_MULTIPLIER, 3)
            weight_multipliers_applied["heart_rate_weight"] = weights["heart_rate"]
            contributors.append(ScoreContributor(
                source="ECG Arrhythmia Amplifier (SL2)",
                layer="SL2",
                points=0.0,
                clinical_standard="SENTINEL Contextual Modifier",
                detail=f"ECG arrhythmia {ecg_rhythm} detected — HR weight amplified ×1.5",
            ))
        elif sedentary:
            weights["heart_rate"] = round(SL1_WEIGHTS["heart_rate"] * ACTIVITY_SEDENTARY_HR_WEIGHT_MULTIPLIER, 3)
            weight_multipliers_applied["heart_rate_weight"] = weights["heart_rate"]
            contributors.append(ScoreContributor(
                source="Sedentary HR Amplifier (SL2)",
                layer="SL2",
                points=0.0,
                clinical_standard="SENTINEL Contextual Modifier",
                detail="Sedentary + elevated HR — HR weight amplified ×1.25",
            ))

        # Recompute weighted SL1 sum with modified weights
        weighted_sum: float = 0.0
        for vital, score in sl1.vital_scores.items():
            w = weights.get(vital, SL1_WEIGHTS.get(vital, 1))
            weighted_sum += score * w

        # Normalise (mirrors SL1 normalisation formula)
        # SL1_RAW_MAX uses original weights; here we use the modified weighted sum directly
        normalised_sl1 = round(weighted_sum / SL1_RAW_MAX * SL1_NORMALISED_MAX, 3)

        # Additive bonuses
        additive: float = normalised_sl1

        stress = validated.get("stress_score")
        if stress is not None and stress > STRESS_SCORE_MODIFIER_THRESHOLD:
            additive += STRESS_SCORE_ADDITIVE_POINTS
            contributors.append(ScoreContributor(
                source="High Stress Score (SL2)",
                layer="SL2",
                points=STRESS_SCORE_ADDITIVE_POINTS,
                clinical_standard="SENTINEL Contextual Modifier",
                detail=f"Stress score {stress:.0f}/100 > threshold {STRESS_SCORE_MODIFIER_THRESHOLD:.0f} — +{STRESS_SCORE_ADDITIVE_POINTS:.0f} pts",
            ))

        if processed.hrv_acute_drop:
            additive += HRV_ACUTE_DROP_ADDITIVE_POINTS
            contributors.append(ScoreContributor(
                source="HRV Acute Drop (SL2)",
                layer="SL2",
                points=HRV_ACUTE_DROP_ADDITIVE_POINTS,
                clinical_standard="SENTINEL Contextual Modifier",
                detail=f"HRV acute drop detected — autonomic stress signal — +{HRV_ACUTE_DROP_ADDITIVE_POINTS:.0f} pts",
            ))

        # Sleep deficit floor is applied AFTER full assembly — just log here
        deep_sleep = validated.get("deep_sleep_pct")
        if deep_sleep is not None and deep_sleep < DEEP_SLEEP_DEFICIT_THRESHOLD_PCT:
            contributors.append(ScoreContributor(
                source="Chronic Sleep Deficit (SL2)",
                layer="SL2",
                points=0.0,
                clinical_standard="SENTINEL Contextual Modifier",
                detail=f"Deep sleep {deep_sleep:.1f}% < {DEEP_SLEEP_DEFICIT_THRESHOLD_PCT:.0f}% — baseline floor raised to {DEEP_SLEEP_DEFICIT_FLOOR_SCORE:.0f}",
            ))

        return SL2Result(
            additive_points=round(additive, 3),
            weight_multipliers_applied=weight_multipliers_applied,
            contributors=contributors,
        )

    # ── HOLD log Redis storage ─────────────────────────────────────────────────

    async def _store_hold_log(self, patient_id: str, entry: HOLDLogEntry) -> None:
        payload = entry.model_dump(mode="json")
        latest_key  = HOLD_LOG_LATEST_KEY.format(patient_id=patient_id)
        history_key = HOLD_LOG_HISTORY_KEY.format(patient_id=patient_id)
        try:
            client = await self.redis.get_client()
            await client.set(latest_key, json.dumps(payload, default=str))
            await client.lpush(history_key, json.dumps(payload, default=str))
            await client.ltrim(history_key, 0, HOLD_LOG_HISTORY_MAX - 1)
        except Exception as exc:
            logger.warning("Failed to store HOLD log for %s: %s", patient_id, exc)

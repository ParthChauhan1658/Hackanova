"""
SignalProcessor — stateless per call, all mutable state stored in Redis.
Steps A–I as defined in prompt1.txt.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import numpy as np

from app.core.constants import (
    ECG_ST_ELEVATION_THRESHOLD_MM,
    FALL_UNRESPONSIVE_ZERO_MOTION_TICKS,
    HR_TACHYCARDIA_SUSTAINED_BPM,
    HR_TACHYCARDIA_SUSTAINED_TICKS,
    HRV_ACUTE_DROP_THRESHOLD,
    HYPERTHERMIA_THRESHOLD_C,
    NUMERIC_VITAL_FIELDS,
    PLAUSIBILITY_BOUNDS,
    RESP_COMBINED_SPO2_THRESHOLD,
    RESP_CRITICAL_RATE,
    SIGNAL_QUALITY_MINIMUM_THRESHOLD,
    THRESHOLD_RULES,
    TIER_A_VITALS,
)
from app.core.redis_client import RedisClient
from app.models.vitals import (
    ActivityLevel,
    ECGRhythm,
    FallEvent,
    HardOverride,
    LocationSnapshot,
    ProcessedReading,
    ThresholdFlag,
    VitalReading,
)

logger = logging.getLogger(__name__)


class SignalProcessor:
    """
    Processes a single VitalReading through validation, Redis windowing,
    threshold flagging, trend computation, and hard-override detection.
    """

    def __init__(self, redis_client: RedisClient) -> None:
        self.redis = redis_client

    # ── Public entry point ────────────────────────────────────────────────────

    async def process(self, reading: VitalReading) -> ProcessedReading:
        validated: dict[str, Optional[float]] = {}
        is_interpolated: dict[str, bool] = {}
        low_signal = False

        # Step A — Signal quality gate
        if (
            reading.signal_quality is not None
            and reading.signal_quality < SIGNAL_QUALITY_MINIMUM_THRESHOLD
        ):
            low_signal = True
            logger.warning(
                "[%s] Low signal quality: %.1f — all vitals marked unreliable",
                reading.patient_id,
                reading.signal_quality,
            )
            for field in NUMERIC_VITAL_FIELDS:
                last = await self.redis.get_last_valid(reading.patient_id, field)
                validated[field] = last
                is_interpolated[field] = True  # mark ALL as unreliable per spec

        else:
            # Step B — Plausibility validation + interpolation
            for field in NUMERIC_VITAL_FIELDS:
                raw = getattr(reading, field, None)
                lo, hi = PLAUSIBILITY_BOUNDS[field]

                if raw is not None and (raw < lo or raw >= hi):
                    logger.warning(
                        "[%s] Implausible %s=%.2f (bounds [%.1f, %.1f)) — discarding",
                        reading.patient_id, field, raw, lo, hi,
                    )
                    raw = None  # discard

                if raw is not None:
                    validated[field] = raw
                    is_interpolated[field] = False
                else:
                    # Attempt interpolation from Redis
                    last = await self.redis.get_last_valid(reading.patient_id, field)
                    if last is not None:
                        validated[field] = last
                        is_interpolated[field] = True
                    else:
                        validated[field] = None
                        is_interpolated[field] = False

        # Step C — Update Redis windows (skip if low-signal; we don't trust the values)
        if not low_signal:
            for field in NUMERIC_VITAL_FIELDS:
                val = validated.get(field)
                if val is not None:
                    await self.redis.push_to_window(reading.patient_id, field, val)
                    await self.redis.set_last_valid(reading.patient_id, field, val)

            hrv = validated.get("hrv_ms")
            if hrv is not None:
                await self.redis.update_session_hrv_baseline(
                    reading.patient_id, reading.session_id, hrv
                )

        # Step D — Threshold flags (Tier-A only, skip if low-signal)
        threshold_flags: dict[str, ThresholdFlag] = {}
        if not low_signal:
            for field in TIER_A_VITALS:
                val = validated.get(field)
                if val is not None:
                    threshold_flags[field] = _classify_threshold(field, val)

        # Step E — Window trends (delta per minute over 12-tick window)
        window_trends: dict[str, Optional[float]] = {}
        for field in TIER_A_VITALS:
            window = await self.redis.get_window(reading.patient_id, field)
            if len(window) < 3:
                window_trends[field] = None
            else:
                x = np.arange(len(window), dtype=float)
                slope = float(np.polyfit(x, window, 1)[0])
                # Each tick = 0.5 s → 120 ticks per minute
                window_trends[field] = slope * 120.0

        # Step F — HardOverride detection (skip if low-signal)
        hard_override: Optional[HardOverride] = None
        if not low_signal:
            hard_override = await self._detect_hard_override(reading, validated)

        # Step G — HRV acute drop
        hrv_acute_drop = await self._check_hrv_acute_drop(
            reading.patient_id, reading.session_id, validated.get("hrv_ms")
        )

        # Step H — Activity context flags
        apply_vigorous = False
        apply_sedentary = False
        if reading.activity_context == ActivityLevel.VIGOROUS:
            apply_vigorous = True
        elif (
            reading.activity_context == ActivityLevel.SEDENTARY
            and threshold_flags.get("heart_rate") == ThresholdFlag.WARNING_HIGH
        ):
            apply_sedentary = True

        # Step I — Location snapshot
        location: Optional[LocationSnapshot] = None
        if (
            not reading.location_stale
            and reading.latitude is not None
            and reading.longitude is not None
        ):
            location = LocationSnapshot(
                latitude=reading.latitude,
                longitude=reading.longitude,
                captured_at=reading.timestamp,
            )

        return ProcessedReading(
            original=reading,
            validated_vitals=validated,
            is_interpolated=is_interpolated,
            threshold_flags=threshold_flags,
            window_trends=window_trends,
            hard_override=hard_override,
            hrv_acute_drop=hrv_acute_drop,
            apply_hr_vigorous_suppressor=apply_vigorous,
            apply_hr_sedentary_amplifier=apply_sedentary,
            signal_quality=reading.signal_quality,
            location=location,
            low_signal_quality=low_signal,
            processed_at=datetime.now(timezone.utc),
        )

    # ── HardOverride detection ────────────────────────────────────────────────

    async def _detect_hard_override(
        self, reading: VitalReading, validated: dict[str, Optional[float]]
    ) -> Optional[HardOverride]:
        """
        Check all 7 conditions in strict priority order.
        Returns the first one that fires; None if none apply.
        """

        # P1 — ECG lethal rhythm
        if reading.ecg_rhythm in (ECGRhythm.VT, ECGRhythm.VF):
            return HardOverride(
                override_type="ECG_LETHAL_RHYTHM",
                triggered_value=None,
                description=f"ECG rhythm {reading.ecg_rhythm.value} detected",
            )

        # P2 — ST elevation
        st = validated.get("ecg_st_deviation_mm")
        if st is not None and st > ECG_ST_ELEVATION_THRESHOLD_MM:
            return HardOverride(
                override_type="ECG_ST_ELEVATION",
                triggered_value=st,
                description=f"ST deviation {st:.2f} mm > {ECG_ST_ELEVATION_THRESHOLD_MM} mm",
            )

        # P3 — SpO₂ critical
        spo2 = validated.get("spo2")
        if spo2 is not None and spo2 < 85.0:
            return HardOverride(
                override_type="SPO2_CRITICAL",
                triggered_value=spo2,
                description=f"SpO₂ {spo2:.1f}% below critical threshold 85%",
            )

        # P4 — Sustained tachycardia (last 2 HR window values both > 150)
        hr_window = await self.redis.get_window(reading.patient_id, "heart_rate")
        if (
            len(hr_window) >= HR_TACHYCARDIA_SUSTAINED_TICKS
            and all(v > HR_TACHYCARDIA_SUSTAINED_BPM for v in hr_window[-HR_TACHYCARDIA_SUSTAINED_TICKS:])
        ):
            return HardOverride(
                override_type="HR_SEVERE_TACHY",
                triggered_value=validated.get("heart_rate"),
                description=f"HR > {HR_TACHYCARDIA_SUSTAINED_BPM} bpm sustained for last {HR_TACHYCARDIA_SUSTAINED_TICKS} readings",
            )

        # P5 — Hyperthermia
        temp = validated.get("body_temperature")
        if temp is not None and temp > HYPERTHERMIA_THRESHOLD_C:
            return HardOverride(
                override_type="HYPERTHERMIA_CRITICAL",
                triggered_value=temp,
                description=f"Body temperature {temp:.1f}°C above {HYPERTHERMIA_THRESHOLD_C}°C",
            )

        # P6 — Resp + SpO₂ combined
        rr = validated.get("respiratory_rate")
        if (
            rr is not None
            and spo2 is not None
            and rr > RESP_CRITICAL_RATE
            and spo2 < RESP_COMBINED_SPO2_THRESHOLD
        ):
            return HardOverride(
                override_type="RESP_SPO2_COMBINED",
                triggered_value=rr,
                description=f"RR {rr:.1f} > {RESP_CRITICAL_RATE} AND SpO₂ {spo2:.1f}% < {RESP_COMBINED_SPO2_THRESHOLD}%",
            )

        # P7 — Fall unresponsive
        if reading.fall_event == FallEvent.CONFIRMED_FALL:
            steps_window = await self.redis.get_window(reading.patient_id, "steps_per_hour")
            if (
                len(steps_window) >= FALL_UNRESPONSIVE_ZERO_MOTION_TICKS
                and all(v == 0.0 for v in steps_window[-FALL_UNRESPONSIVE_ZERO_MOTION_TICKS:])
            ):
                return HardOverride(
                    override_type="FALL_UNRESPONSIVE",
                    triggered_value=None,
                    description=f"CONFIRMED_FALL with zero motion for last {FALL_UNRESPONSIVE_ZERO_MOTION_TICKS} readings",
                )

        return None

    # ── HRV acute drop ────────────────────────────────────────────────────────

    async def _check_hrv_acute_drop(
        self, patient_id: str, session_id: str, hrv_val: Optional[float]
    ) -> bool:
        if hrv_val is None:
            return False
        baseline = await self.redis.get_session_hrv_baseline(patient_id, session_id)
        if baseline is None:
            return False
        return hrv_val < baseline * HRV_ACUTE_DROP_THRESHOLD


# ── Module-level helper ───────────────────────────────────────────────────────

def _classify_threshold(field: str, value: float) -> ThresholdFlag:
    """Return the ThresholdFlag for a Tier-A vital using THRESHOLD_RULES."""
    for upper_bound, flag in THRESHOLD_RULES[field]:
        if value < upper_bound:
            return flag
    return THRESHOLD_RULES[field][-1][1]

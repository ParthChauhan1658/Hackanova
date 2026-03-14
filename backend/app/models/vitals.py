"""
Shared Pydantic v2 data models for SENTINEL.
All components consume these models — do not duplicate definitions elsewhere.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ── Enumerations ──────────────────────────────────────────────────────────────

class ECGRhythm(str, Enum):
    NORMAL = "NORMAL"
    AFIB = "AFIB"
    VT = "VT"
    VF = "VF"
    UNKNOWN = "UNKNOWN"


class FallEvent(str, Enum):
    NONE = "NONE"
    POSSIBLE_FALL = "POSSIBLE_FALL"
    CONFIRMED_FALL = "CONFIRMED_FALL"


class ActivityLevel(str, Enum):
    RESTING = "RESTING"
    SEDENTARY = "SEDENTARY"
    ACTIVE = "ACTIVE"
    VIGOROUS = "VIGOROUS"


class ThresholdFlag(str, Enum):
    CRITICAL_LOW = "CRITICAL_LOW"
    WARNING_LOW = "WARNING_LOW"
    NORMAL = "NORMAL"
    WARNING_HIGH = "WARNING_HIGH"
    CRITICAL_HIGH = "CRITICAL_HIGH"


# ── Sub-models ────────────────────────────────────────────────────────────────

class HardOverride(BaseModel):
    """Represents a single critical condition that forces CRITICAL risk level."""
    override_type: str  # ECG_LETHAL_RHYTHM | ECG_ST_ELEVATION | SPO2_CRITICAL |
                        # HR_SEVERE_TACHY | HYPERTHERMIA_CRITICAL |
                        # RESP_SPO2_COMBINED | FALL_UNRESPONSIVE
    triggered_value: Optional[float] = None
    description: str


class LocationSnapshot(BaseModel):
    """Patient location captured at reading time — only set when location_stale is False."""
    latitude: float
    longitude: float
    captured_at: datetime


# ── Primary models ────────────────────────────────────────────────────────────

class VitalReading(BaseModel):
    """
    Raw input model — direct mapping from one CSV row.
    Internal field names differ from CSV column names (see simulator._map_row for mapping).
    """
    model_config = ConfigDict(populate_by_name=True)

    # Identity
    reading_id: str
    patient_id: str
    session_id: str
    timestamp: datetime

    # Channel 1 — Heart Rate  (CSV: heart_rate_bpm)
    heart_rate: Optional[float] = None

    # Channel 2 — Respiratory Rate  (CSV: respiratory_rate)
    respiratory_rate: Optional[float] = None

    # Channel 3 — SpO₂  (CSV: spo2_percent)
    spo2: Optional[float] = None

    # Channel 4 — ECG  (CSV: ecg_rhythm / ecg_st_deviation_mm / ecg_qtc_ms)
    ecg_rhythm: Optional[ECGRhythm] = None
    ecg_st_deviation_mm: Optional[float] = None
    ecg_qtc_ms: Optional[float] = None

    # Channel 5 — Temperature  (CSV: temperature_celsius)
    body_temperature: Optional[float] = None

    # Channel 6 — Sleep  (CSV: sleep_efficiency_pct / deep_sleep_pct / rem_pct)
    sleep_efficiency: Optional[float] = None
    deep_sleep_pct: Optional[float] = None
    rem_pct: Optional[float] = None

    # Channel 7 — HRV  (CSV: hrv_rmssd_ms)
    hrv_ms: Optional[float] = None

    # Channel 8 — Stress  (CSV: stress_score)
    stress_score: Optional[float] = None

    # Channel 9 — Fall Detection  (CSV: fall_event)
    fall_event: FallEvent = FallEvent.NONE

    # Channel 10 — Activity  (CSV: steps_per_hour / activity_level)
    steps_per_hour: Optional[float] = None
    activity_context: Optional[ActivityLevel] = None  # CSV: activity_level

    # Patient metadata
    age: Optional[int] = None
    gender: Optional[str] = None
    weight_kg: Optional[float] = None
    has_chronic_condition: Optional[bool] = None

    # Location
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    location_stale: bool = True

    # Source metadata
    source: str = "synthetic_dataset"
    signal_quality: Optional[float] = None  # CSV: signal_quality_pct


class ProcessedReading(BaseModel):
    """Output of SignalProcessor — enriched reading with flags, trends, and override."""

    original: VitalReading

    # Post-validation numeric vital values (internal field names → value or None)
    validated_vitals: dict[str, Optional[float]]

    # True for fields whose value was substituted from Redis (interpolated from last valid)
    is_interpolated: dict[str, bool]

    # ThresholdFlag per Tier-A vital (heart_rate, spo2, respiratory_rate, body_temperature, hrv_ms)
    threshold_flags: dict[str, ThresholdFlag]

    # Linear regression slope (delta per minute) over the 12-tick Redis window per vital
    window_trends: dict[str, Optional[float]]

    # At most one HardOverride per reading; None if no critical condition detected
    hard_override: Optional[HardOverride] = None

    # HRV dropped below 60 % of session running mean
    hrv_acute_drop: bool = False

    # Activity context modifiers for the scoring engine
    apply_hr_vigorous_suppressor: bool = False
    apply_hr_sedentary_amplifier: bool = False

    # Pass-through from input
    signal_quality: Optional[float] = None

    # Only populated when location_stale is False and coords are present
    location: Optional[LocationSnapshot] = None

    # True when signal_quality_pct < SIGNAL_QUALITY_MINIMUM_THRESHOLD
    low_signal_quality: bool = False

    processed_at: datetime

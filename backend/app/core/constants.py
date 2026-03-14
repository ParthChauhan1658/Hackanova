"""
All clinical thresholds and system-wide configuration constants.
No magic numbers anywhere else in the codebase — import from here.
"""

from app.models.vitals import ThresholdFlag

# ── Plausibility bounds (internal field name → (min_inclusive, max_exclusive)) ─
# Values outside [min, max) are considered sensor artifacts and discarded.
PLAUSIBILITY_BOUNDS: dict[str, tuple[float, float]] = {
    "heart_rate":          (20.0,   250.0),   # bpm
    "respiratory_rate":    (4.0,    60.0),    # breaths/min
    "spo2":                (50.0,   100.1),   # %  (100.1 keeps 100 % valid)
    "body_temperature":    (32.0,   43.0),    # °C
    "hrv_ms":              (5.0,    200.0),   # ms
    "ecg_st_deviation_mm": (-5.0,   5.0),     # mm  (symmetric)
    "ecg_qtc_ms":          (200.0,  700.0),   # ms
    "stress_score":        (0.0,    100.1),   # 0–100 (100.1 keeps 100 valid)
    "signal_quality":      (0.0,    100.1),   # 0–100
    "steps_per_hour":      (0.0,    40000.0), # steps
    "sleep_efficiency":    (0.0,    100.1),   # %
    "deep_sleep_pct":      (0.0,    100.1),   # %
    "rem_pct":             (0.0,    100.1),   # %
}

# ── Threshold rules (NEWS2 / MEWS derived) ────────────────────────────────────
# Each entry: ordered list of (upper_bound_exclusive, ThresholdFlag).
# Classify by finding the first upper_bound where value < upper_bound.
THRESHOLD_RULES: dict[str, list[tuple[float, ThresholdFlag]]] = {
    "heart_rate": [
        (40.0,        ThresholdFlag.CRITICAL_LOW),
        (51.0,        ThresholdFlag.WARNING_LOW),
        (91.0,        ThresholdFlag.NORMAL),
        (111.0,       ThresholdFlag.WARNING_HIGH),
        (float("inf"),ThresholdFlag.CRITICAL_HIGH),
    ],
    "spo2": [
        (85.0,        ThresholdFlag.CRITICAL_LOW),
        (92.0,        ThresholdFlag.WARNING_LOW),
        (float("inf"),ThresholdFlag.NORMAL),
    ],
    "respiratory_rate": [
        (8.0,         ThresholdFlag.CRITICAL_LOW),
        (12.0,        ThresholdFlag.WARNING_LOW),
        (21.0,        ThresholdFlag.NORMAL),
        (25.0,        ThresholdFlag.WARNING_HIGH),
        (float("inf"),ThresholdFlag.CRITICAL_HIGH),
    ],
    "body_temperature": [
        (35.0,        ThresholdFlag.CRITICAL_LOW),
        (36.0,        ThresholdFlag.WARNING_LOW),
        (38.0,        ThresholdFlag.NORMAL),
        (39.0,        ThresholdFlag.WARNING_HIGH),
        (float("inf"),ThresholdFlag.CRITICAL_HIGH),
    ],
    "hrv_ms": [
        (15.0,        ThresholdFlag.CRITICAL_LOW),
        (26.0,        ThresholdFlag.WARNING_LOW),
        (float("inf"),ThresholdFlag.NORMAL),
    ],
}

# ── Redis window settings ─────────────────────────────────────────────────────
REDIS_WINDOW_SIZE: int = 12          # ticks stored per patient per vital
REDIS_TREND_TICKS: int = 12          # ticks used for slope computation

# ── Clinical decision constants ───────────────────────────────────────────────
HRV_ACUTE_DROP_THRESHOLD: float = 0.60          # current HRV < 60 % of session mean
HR_TACHYCARDIA_SUSTAINED_BPM: float = 150.0     # bpm
HR_TACHYCARDIA_SUSTAINED_TICKS: int = 2         # consecutive readings required
ECG_ST_ELEVATION_THRESHOLD_MM: float = 1.0      # mm
HYPERTHERMIA_THRESHOLD_C: float = 40.0          # °C
RESP_CRITICAL_RATE: float = 30.0                # breaths/min
RESP_COMBINED_SPO2_THRESHOLD: float = 92.0      # %
FALL_UNRESPONSIVE_ZERO_MOTION_TICKS: int = 2    # consecutive zero-steps readings

# ── Signal quality ────────────────────────────────────────────────────────────
SIGNAL_QUALITY_MINIMUM_THRESHOLD: float = 20.0  # below this → all vitals unreliable

# ── Simulator ─────────────────────────────────────────────────────────────────
SIMULATOR_DEFAULT_INTERVAL_SECONDS: float = 0.5  # seconds between ticks

# ── Tier-A vitals (have threshold rules + trend computation) ──────────────────
TIER_A_VITALS: list[str] = [
    "heart_rate",
    "spo2",
    "respiratory_rate",
    "body_temperature",
    "hrv_ms",
]

# ── All numeric vitals subject to plausibility validation ─────────────────────
# Excludes signal_quality (handled separately as metadata)
NUMERIC_VITAL_FIELDS: list[str] = [
    "heart_rate",
    "respiratory_rate",
    "spo2",
    "body_temperature",
    "hrv_ms",
    "ecg_st_deviation_mm",
    "ecg_qtc_ms",
    "stress_score",
    "steps_per_hour",
    "sleep_efficiency",
    "deep_sleep_pct",
    "rem_pct",
]

# ── Scoring Engine — Sub-Layer 1 weights ──────────────────────────────────────
SL1_WEIGHTS: dict[str, int] = {
    "heart_rate":       3,
    "respiratory_rate": 4,
    "spo2":             4,
    "body_temperature": 2,
    "hrv_ms":           3,
}
SL1_RAW_MAX: int = 48
SL1_NORMALISED_MAX: int = 40

# ── Sub-Layer 2 ────────────────────────────────────────────────────────────────
STRESS_SCORE_MODIFIER_THRESHOLD: float = 70.0
STRESS_SCORE_ADDITIVE_POINTS: float = 8.0
HRV_ACUTE_DROP_ADDITIVE_POINTS: float = 2.0
ECG_ARRHYTHMIA_HR_WEIGHT_MULTIPLIER: float = 1.5
ACTIVITY_VIGOROUS_HR_WEIGHT_MULTIPLIER: float = 0.5
ACTIVITY_VIGOROUS_HRV_WEIGHT_MULTIPLIER: float = 0.333
ACTIVITY_SEDENTARY_HR_WEIGHT_MULTIPLIER: float = 1.25
DEEP_SLEEP_DEFICIT_THRESHOLD_PCT: float = 15.0
DEEP_SLEEP_DEFICIT_FLOOR_SCORE: float = 8.0

# ── Sub-Layer 3 syndrome bonus points ─────────────────────────────────────────
SYNDROME_SIRS_BONUS: float = 25.0
SYNDROME_HYPOXIC_BONUS: float = 25.0
SYNDROME_SHOCK_BONUS: float = 30.0
SYNDROME_AUTONOMIC_COLLAPSE_BONUS: float = 20.0
SYNDROME_RESPIRATORY_FAILURE_BONUS: float = 25.0
SYNDROME_MULTI_SYSTEM_BONUS: float = 20.0
QSOFA_BONUS: float = 25.0
QSOFA_THRESHOLD: int = 2

# ── Sub-Layer 4 trend bonus points ────────────────────────────────────────────
TREND_HR_ASCENT_BONUS: float = 10.0
TREND_SPO2_DECLINE_BONUS: float = 10.0
TREND_HRV_COLLAPSE_BONUS: float = 8.0
TREND_INVERSE_HR_SPO2_BONUS: float = 12.0
TREND_TEMP_TRAJECTORY_BONUS: float = 6.0
TREND_HR_ASCENT_DELTA_BPM: float = 10.0
TREND_HRV_COLLAPSE_DELTA_MS: float = 12.0
TREND_SPO2_DECLINE_MIN_TICKS: int = 8
TREND_INVERSE_HR_MIN_DELTA_BPM: float = 5.0
TREND_INVERSE_SPO2_MIN_FALLING_TICKS: int = 6
TREND_MIN_WINDOW_TICKS: int = 6

# ── Sub-Layer 5 ────────────────────────────────────────────────────────────────
IF_SCORE_LOW_THRESHOLD: float = 0.5
IF_SCORE_MID_THRESHOLD: float = 0.6
IF_SCORE_HIGH_THRESHOLD: float = 0.8
IF_POINTS_LOW: float = 5.0
IF_POINTS_MID: float = 10.0
IF_POINTS_HIGH: float = 15.0

# ── MEWS ──────────────────────────────────────────────────────────────────────
MEWS_FLAG_THRESHOLD: int = 5

# ── Final assembly ────────────────────────────────────────────────────────────
SCORE_MAX_POSSIBLE: float = 236.0
SHAL_NOMINAL_MAX: int = 29
SHAL_ELEVATED_MAX: int = 49
SHAL_WARNING_MAX: int = 69
SHAL_HIGH_MAX: int = 79

# ── HOLD log Redis keys ────────────────────────────────────────────────────────
HOLD_LOG_LATEST_KEY: str = "hold:{patient_id}:latest"
HOLD_LOG_HISTORY_KEY: str = "hold:{patient_id}:history"
HOLD_LOG_HISTORY_MAX: int = 50

# ── Sustained ticks rule ──────────────────────────────────────────────────────
SL1_SUSTAINED_TICKS_MIN: int = 3

# ── LLM Reasoning Engine ──────────────────────────────────────────────────────
ANTHROPIC_API_KEY_ENV: str = "ANTHROPIC_API_KEY"
GEMINI_API_KEY_ENV: str = "GEMINI_API_KEY"
CLAUDE_MODEL: str = "claude-opus-4-5"
CLAUDE_TIMEOUT_SECONDS: float = 8.0
CLAUDE_MAX_TOKENS: int = 16000
CLAUDE_THINKING_BUDGET_TOKENS: int = 10000
GEMINI_MODEL: str = "gemini-2.0-flash"
GEMINI_TIMEOUT_SECONDS: float = 6.0
LLM_CONFIDENCE_THRESHOLD: float = 0.55
REASONING_HISTORY_MAX: int = 20

# Redis keys — reasoning
REASONING_LATEST_KEY: str = "reasoning:{patient_id}:latest"
REASONING_HISTORY_KEY: str = "reasoning:{patient_id}:history"

# ── Escalation Engine ──────────────────────────────────────────────────────────
EMS_API_URL_ENV: str = "EMS_API_URL"
EMS_MOCK_URL: str = "https://mock-ems.sentinel.local/dispatch"
EMS_TIMEOUT_SECONDS: float = 5.0
EMS_MAX_RETRIES: int = 3
EMS_RETRY_BACKOFF_SECONDS: list[float] = [0, 2, 4]
ESCALATION_CRITICAL_TIMEOUT_SECONDS: float = 10.0

# Twilio
TWILIO_ACCOUNT_SID_ENV: str = "TWILIO_ACCOUNT_SID"
TWILIO_AUTH_TOKEN_ENV: str = "TWILIO_AUTH_TOKEN"
TWILIO_FROM_NUMBER_ENV: str = "TWILIO_FROM_NUMBER"
TWILIO_API_BASE: str = "https://api.twilio.com/2010-04-01/Accounts"
TWILIO_CALLS_ENDPOINT: str = "/Calls.json"
TWILIO_MESSAGES_ENDPOINT: str = "/Messages.json"

# Resend (replaces SendGrid)
RESEND_API_KEY_ENV: str = "RESEND_API_KEY"
RESEND_API_URL: str = "https://api.resend.com/emails"
RESEND_FROM_EMAIL_ENV: str = "RESEND_FROM_EMAIL"
RESEND_FROM_EMAIL_DEFAULT: str = "SENTINEL <onboarding@resend.dev>"

# SendGrid (kept for backwards compat — no longer used)
SENDGRID_API_KEY_ENV: str = "SENDGRID_API_KEY"
SENDGRID_API_URL: str = "https://api.sendgrid.com/v3/mail/send"
SENDGRID_FROM_EMAIL_ENV: str = "SENDGRID_FROM_EMAIL"

# Firebase FCM
FIREBASE_CREDENTIALS_JSON_ENV: str = "FIREBASE_CREDENTIALS_JSON"
FCM_DEVICE_TOKEN_KEY: str = "device:{patient_id}:fcm_token"

# Cal.com
CAL_COM_API_KEY_ENV: str = "CAL_COM_API_KEY"
CAL_COM_EVENT_TYPE_ID_ENV: str = "CAL_COM_EVENT_TYPE_ID"
CAL_COM_API_BASE: str = "https://api.cal.com/v2"
APPOINTMENT_RETRY_DELAY_SECONDS: float = 60.0

# Fall protocol
FALL_STATE_KEY: str = "fall:{patient_id}:state"
FALL_POSSIBLE_AT_KEY: str = "fall:{patient_id}:possible_fall_at"
FALL_CONFIRMED_AT_KEY: str = "fall:{patient_id}:confirmed_at"
FALL_ACKNOWLEDGED_KEY: str = "fall:{patient_id}:acknowledged"
FALL_MONITORING_WINDOW_SECONDS: float = 30.0
FALL_COUNTDOWN_SECONDS: float = 60.0
FALL_POLL_INTERVAL_SECONDS: float = 2.0
FALL_ACKNOWLEDGED_TTL_SECONDS: int = 120
FALL_EMS_SLA_SECONDS: float = 5.0

# PostgreSQL
DATABASE_URL_ENV: str = "DATABASE_URL"
DATABASE_URL_DEFAULT: str = (
    "postgresql+asyncpg://sentinel:sentinel@localhost:5432/sentinel"
)
AUDIT_QUERY_LIMIT_DEFAULT: int = 50

# Redis additional events
EMERGENCY_DISPATCHED_EVENT: str = "EMERGENCY_DISPATCHED"

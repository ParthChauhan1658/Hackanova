"""
Output models for the SENTINEL Scoring Engine.
All scoring sub-layer results and the final RiskAssessment are defined here.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel


# ── SHAL Band ─────────────────────────────────────────────────────────────────

class SHALBand(str, Enum):
    NOMINAL  = "NOMINAL"   # 0–29
    ELEVATED = "ELEVATED"  # 30–49
    WARNING  = "WARNING"   # 50–69
    HIGH     = "HIGH"      # 70–79
    CRITICAL = "CRITICAL"  # 80–100


# ── Score contributor (XAI unit) ──────────────────────────────────────────────

class ScoreContributor(BaseModel):
    source: str            # e.g. "Respiratory Rate (SL1)", "SIRS Bonus (SL3)"
    layer: str             # "SL1" | "SL2" | "SL3" | "SL4" | "SL5" | "OVERRIDE"
    points: float          # raw points contributed (before normalisation for SL1)
    clinical_standard: str # e.g. "NEWS2", "qSOFA", "SIRS Criteria"
    detail: str            # one-sentence explanation


# ── Sub-layer result models ───────────────────────────────────────────────────

class SL1Result(BaseModel):
    raw_points: float                  # sum before normalisation (max 48)
    normalised_points: float           # raw_points / 48 × 40 (max 40)
    contributors: list[ScoreContributor]
    vital_scores: dict[str, int]       # e.g. {"heart_rate": 1, "spo2": 2}


class SL2Result(BaseModel):
    additive_points: float
    weight_multipliers_applied: dict[str, float]   # e.g. {"heart_rate_weight": 4.5}
    contributors: list[ScoreContributor]


class SL3Result(BaseModel):
    syndromes_fired: list[str]
    total_points: float
    contributors: list[ScoreContributor]
    qsofa_score: int                   # 0, 1, 2, or 3
    qsofa_criteria_met: list[str]      # which qSOFA criteria were met


class SL4Result(BaseModel):
    trends_fired: list[str]
    total_points: float
    contributors: list[ScoreContributor]


class SL5Result(BaseModel):
    anomaly_score: float               # raw IF anomaly score 0.0–1.0
    points_added: float                # 0, 5, 10, or 15
    xai_label: str                     # log label for this tier
    contributor: Optional[ScoreContributor] = None


class MEWSResult(BaseModel):
    mews_score: int
    mews_flag: bool                    # True if MEWS >= 5
    review_flag_added: bool            # True if MEWS >= 5 but primary score < 60


# ── HOLD log entry (ELEVATED / WARNING bands) ─────────────────────────────────

class HOLDLogEntry(BaseModel):
    patient_id: str
    session_id: str
    timestamp: datetime
    shal_band: SHALBand
    score: float
    watch_condition: str               # "Will escalate if [X] within [Y minutes]"
    vitals_snapshot: dict[str, Optional[float]]
    contributors: list[ScoreContributor]


# ── Main output model ─────────────────────────────────────────────────────────

class RiskAssessment(BaseModel):
    patient_id: str
    session_id: str
    reading_id: str
    timestamp: datetime
    final_score: float                 # 0.0–100.0, hard capped at 100
    shal_band: SHALBand
    hard_override_active: bool
    hard_override_type: Optional[str] = None
    sl1: SL1Result
    sl2: SL2Result
    sl3: SL3Result
    sl4: SL4Result
    sl5: SL5Result
    mews: MEWSResult
    all_contributors: list[ScoreContributor]   # flat list of ALL contributors
    hold_log: Optional[HOLDLogEntry] = None    # populated if ELEVATED or WARNING
    xai_narrative: str                         # plain English scoring summary
    assessed_at: datetime

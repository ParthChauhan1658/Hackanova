"""
Output models for the SENTINEL LLM Reasoning Engine.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel


class DecisionSource(str, Enum):
    LLM_CLAUDE          = "LLM_CLAUDE"
    LLM_GEMINI          = "LLM_GEMINI"
    RULE_BASED          = "RULE_BASED"
    LLM_LOW_CONFIDENCE  = "LLM_LOW_CONFIDENCE"  # Claude returned confidence < 0.55


class DifferentialDiagnosis(BaseModel):
    diagnosis: str
    probability: float                      # 0.0–1.0
    supporting_evidence: list[str]
    against_evidence: list[str]
    clinical_source: str


class RecommendedAction(BaseModel):
    action: str
    urgency: str                            # "IMMEDIATE" | "URGENT" | "MONITOR"
    rationale: str


class LLMReasoning(BaseModel):
    patient_id: str
    session_id: str
    reading_id: str
    timestamp: datetime
    decision_source: DecisionSource
    shal_band: str                          # pass-through from RiskAssessment
    final_score: float                      # pass-through from RiskAssessment
    thinking_chain: Optional[str] = None   # only populated for LLM_CLAUDE
    reasoning_summary: str
    differential_diagnoses: list[DifferentialDiagnosis]
    recommended_actions: list[RecommendedAction]
    confidence: float                       # 0.0–1.0
    considered_and_discarded: list[str]
    vitals_snapshot: dict[str, Optional[float]]
    syndromes_fired: list[str]
    trends_fired: list[str]
    hard_override_type: Optional[str] = None
    model_used: Optional[str] = None       # e.g. "claude-sonnet-4-20250514"
    latency_ms: float = 0.0
    reasoned_at: datetime

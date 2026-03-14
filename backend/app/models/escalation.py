"""
Pydantic v2 models for escalation engine outputs.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel


class EscalationPath(str, Enum):
    CRITICAL = "CRITICAL"   # full parallel dispatch: EMS + SMS + email + FCM
    HIGH     = "HIGH"       # appointment + contacts
    FALL     = "FALL"       # fall two-stage protocol
    NONE     = "NONE"       # no action


class ActionStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED  = "FAILED"
    SKIPPED = "SKIPPED"
    PENDING = "PENDING"


class ActionResult(BaseModel):
    action_type: str                # "EMS" | "SMS" | "EMAIL" | "FCM" | "APPOINTMENT"
    status: ActionStatus
    latency_ms: float
    detail: Optional[str] = None    # success detail or error message
    retry_count: int = 0            # how many attempts were made


class EscalationResult(BaseModel):
    patient_id: str
    escalation_path: EscalationPath
    actions: list[ActionResult]
    total_latency_ms: float
    all_succeeded: bool
    escalated_at: datetime

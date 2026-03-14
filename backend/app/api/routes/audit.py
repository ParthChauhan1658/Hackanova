"""
Audit log query routes.

GET  /api/v1/audit                         — paginated list of recent entries
GET  /api/v1/audit/{entry_id}              — single entry by primary key
GET  /api/v1/audit/patient/{patient_id}/latest — most recent entries for a patient
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.core.constants import AUDIT_QUERY_LIMIT_DEFAULT

router = APIRouter()


def _serialize(entry) -> dict:
    """Convert AuditLogEntry ORM object to a plain serialisable dict."""
    return {
        "id":                   entry.id,
        "patient_id":           entry.patient_id,
        "session_id":           entry.session_id,
        "reading_id":           entry.reading_id,
        "escalated_at":         entry.escalated_at.isoformat() if entry.escalated_at else None,
        "final_score":          entry.final_score,
        "shal_band":            entry.shal_band,
        "hard_override_active": entry.hard_override_active,
        "hard_override_type":   entry.hard_override_type,
        "decision_source":      entry.decision_source,
        "reasoning_summary":    entry.reasoning_summary,
        "llm_thinking_chain":   entry.llm_thinking_chain,
        "differential_diagnoses": entry.differential_diagnoses,  # JSON string
        "confidence":           entry.confidence,
        "ems_dispatched":       entry.ems_dispatched,
        "sms_sent":             entry.sms_sent,
        "email_sent":           entry.email_sent,
        "fcm_sent":             entry.fcm_sent,
        "appointment_booked":   entry.appointment_booked,
        "ems_response_code":    entry.ems_response_code,
        "appointment_id":       entry.appointment_id,
        "actions_latency_ms":   entry.actions_latency_ms,
        "vitals_snapshot":      entry.vitals_snapshot,   # JSON string
        "syndromes_fired":      entry.syndromes_fired,   # JSON string
        "trends_fired":         entry.trends_fired,      # JSON string
        "fall_event_type":      entry.fall_event_type,
    }


@router.get("/api/v1/audit")
async def list_audit(
    request: Request,
    limit: int = AUDIT_QUERY_LIMIT_DEFAULT,
    offset: int = 0,
):
    """Return the most recent audit log entries across all patients (newest first)."""
    audit_repo = request.app.state.audit_repo
    entries = await audit_repo.get_recent(limit=limit)
    return {"count": len(entries), "entries": [_serialize(e) for e in entries]}


@router.get("/api/v1/audit/patient/{patient_id}/latest")
async def patient_audit_latest(
    patient_id: str,
    request: Request,
    limit: int = 10,
    offset: int = 0,
):
    """Return the most recent audit entries for a specific patient (newest first)."""
    audit_repo = request.app.state.audit_repo
    entries = await audit_repo.get_by_patient(
        patient_id, limit=limit, offset=offset
    )
    return {
        "patient_id": patient_id,
        "count": len(entries),
        "entries": [_serialize(e) for e in entries],
    }


@router.get("/api/v1/audit/{entry_id}")
async def get_audit_entry(entry_id: int, request: Request):
    """Return a single audit log entry by primary key."""
    audit_repo = request.app.state.audit_repo
    entry = await audit_repo.get_by_id(entry_id)
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail=f"Audit entry {entry_id} not found",
        )
    return _serialize(entry)

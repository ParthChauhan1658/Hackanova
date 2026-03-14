"""
SQLAlchemy 2.0 ORM models for SENTINEL.
AuditLogEntry is immutable — only INSERT, never UPDATE.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class AuditLogEntry(Base):
    """Immutable audit record written after every escalation."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Identifiers
    patient_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    session_id: Mapped[str] = mapped_column(String(100), nullable=False)
    reading_id: Mapped[str] = mapped_column(String(100), nullable=False)

    # Timing
    escalated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    # Risk assessment
    final_score: Mapped[float] = mapped_column(Float, nullable=False)
    shal_band: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    hard_override_active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    hard_override_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # LLM reasoning
    decision_source: Mapped[str] = mapped_column(String(30), nullable=False)
    reasoning_summary: Mapped[str] = mapped_column(Text, nullable=False)
    llm_thinking_chain: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    differential_diagnoses: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON
    confidence: Mapped[float] = mapped_column(Float, nullable=False)

    # Actions taken
    ems_dispatched: Mapped[bool] = mapped_column(Boolean, default=False)
    sms_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    email_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    fcm_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    appointment_booked: Mapped[bool] = mapped_column(Boolean, default=False)

    # Action results
    ems_response_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    appointment_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    actions_latency_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Snapshots stored as JSON strings
    vitals_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    syndromes_fired: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    trends_fired: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Fall protocol
    fall_event_type: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)

    __table_args__ = (
        Index("ix_audit_patient_time", "patient_id", "escalated_at"),
    )

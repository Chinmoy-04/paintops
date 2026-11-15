"""SQLAlchemy ORM models for PaintOps business records."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.database.session import Base


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_uuid() -> str:
    return str(uuid4())


class InspectionEvent(Base):
    """Persisted synthetic inspection event."""

    __tablename__ = "inspection_events"

    event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    plant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    production_line: Mapped[str] = mapped_column(String(64), nullable=False)
    booth_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    body_id: Mapped[str] = mapped_column(String(64), nullable=False)
    defect_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    model_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    telemetry_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(64), default="synthetic_cv_inspection")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)

    investigation: Mapped[Investigation | None] = relationship(
        back_populates="event", uselist=False
    )


class Investigation(Base):
    """Investigation record linked to one inspection event."""

    __tablename__ = "investigations"
    __table_args__ = (UniqueConstraint("event_id", name="uq_investigation_event_id"),)

    investigation_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=new_uuid
    )
    event_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("inspection_events.event_id"), nullable=False
    )
    thread_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="processing", index=True)
    recurrence_count: Mapped[int] = mapped_column(Integer, default=1)
    severity: Mapped[str | None] = mapped_column(String(16), nullable=True)
    suspected_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_json: Mapped[list[Any] | dict[str, Any] | None] = mapped_column(
        JSON, nullable=True
    )
    sop_references_json: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    proposed_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    analysis_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ticket_draft_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    reviewer: Mapped[str | None] = mapped_column(String(128), nullable=True)
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    findings_json: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    revision_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utc_now, onupdate=_utc_now
    )

    event: Mapped[InspectionEvent] = relationship(back_populates="investigation")
    ticket: Mapped[ActionTicket | None] = relationship(
        back_populates="investigation", uselist=False
    )
    audit_events: Mapped[list[AuditEvent]] = relationship(back_populates="investigation")


class ActionTicket(Base):
    """Human-approved action ticket. Created only after approval."""

    __tablename__ = "action_tickets"
    __table_args__ = (
        UniqueConstraint("investigation_id", name="uq_ticket_investigation_id"),
    )

    ticket_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    investigation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("investigations.investigation_id"), nullable=False
    )
    event_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("inspection_events.event_id"), nullable=False
    )
    ticket_type: Mapped[str] = mapped_column(String(64), nullable=False)
    priority: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    sop_references_json: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="open")
    approved_by: Mapped[str] = mapped_column(String(128), nullable=False)
    approved_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)

    investigation: Mapped[Investigation] = relationship(back_populates="ticket")


class AuditEvent(Base):
    """Auditable workflow / API step record."""

    __tablename__ = "audit_events"

    audit_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    investigation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("investigations.investigation_id"), index=True
    )
    node_name: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    details_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)

    investigation: Mapped[Investigation] = relationship(back_populates="audit_events")


# ---------------------------------------------------------------------------
# Synthetic plant context (v2). Read by specialist agents' tools.
# ---------------------------------------------------------------------------


class Booth(Base):
    """A synthetic paint booth on one of the plant's lines."""

    __tablename__ = "booths"

    booth_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    plant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    production_line: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    booth_type: Mapped[str] = mapped_column(String(16), nullable=False)  # primer|base|clear


class TelemetryReading(Base):
    """Synthetic booth environment reading (one row per booth per interval)."""

    __tablename__ = "telemetry_readings"

    reading_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    booth_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("booths.booth_id"), nullable=False, index=True
    )
    ts: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    temperature_c: Mapped[float] = mapped_column(Float, nullable=False)
    humidity_pct: Mapped[float] = mapped_column(Float, nullable=False)
    airflow_m_s: Mapped[float] = mapped_column(Float, nullable=False)
    filter_dp_pa: Mapped[float] = mapped_column(Float, nullable=False)


class MaintenanceLog(Base):
    """Synthetic maintenance record for booth equipment."""

    __tablename__ = "maintenance_logs"

    log_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    booth_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("booths.booth_id"), nullable=False, index=True
    )
    ts: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    component: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    technician: Mapped[str] = mapped_column(String(64), nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="")


class MaterialBatch(Base):
    """Synthetic paint material batch loaded into a booth."""

    __tablename__ = "material_batches"

    batch_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    booth_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("booths.booth_id"), nullable=False, index=True
    )
    material: Mapped[str] = mapped_column(String(64), nullable=False)
    supplier: Mapped[str] = mapped_column(String(64), nullable=False)
    viscosity_s: Mapped[float] = mapped_column(Float, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)


class InvestigationStep(Base):
    """One streamed graph step, stored so a run can be replayed in the UI."""

    __tablename__ = "investigation_steps"
    __table_args__ = (
        UniqueConstraint("investigation_id", "seq", name="uq_step_investigation_seq"),
    )

    step_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    investigation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("investigations.investigation_id"), nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    node: Mapped[str] = mapped_column(String(64), nullable=False)
    namespace: Mapped[str] = mapped_column(String(256), default="")
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)

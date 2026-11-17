"""Data-access helpers for events, investigations, tickets, and audit."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database.models import (
    ActionTicket,
    AuditEvent,
    Booth,
    InspectionEvent,
    Investigation,
    InvestigationStep,
    MaintenanceLog,
    MaterialBatch,
    NotificationOutbox,
    TelemetryReading,
    new_uuid,
)
from app.schemas.event import InspectionEventCreate


def create_inspection_event(
    session: Session, payload: InspectionEventCreate
) -> tuple[InspectionEvent, bool]:
    """
    Insert an inspection event.

    Returns (event, created) where created is False if the event_id already existed.
    """
    existing = session.get(InspectionEvent, payload.event_id)
    if existing is not None:
        return existing, False

    telemetry = (
        payload.telemetry.model_dump()
        if hasattr(payload.telemetry, "model_dump")
        else dict(payload.telemetry)
    )
    event = InspectionEvent(
        event_id=payload.event_id,
        timestamp=payload.timestamp.replace(tzinfo=None)
        if payload.timestamp.tzinfo
        else payload.timestamp,
        plant_id=payload.plant_id,
        production_line=payload.production_line,
        booth_id=payload.booth_id,
        body_id=payload.body_id,
        defect_type=payload.defect_type,
        model_confidence=payload.model_confidence,
        telemetry_json=telemetry,
        source=payload.source,
    )
    session.add(event)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        existing = session.get(InspectionEvent, payload.event_id)
        if existing is None:
            raise
        return existing, False
    return event, True


def get_event(session: Session, event_id: str) -> InspectionEvent | None:
    return session.get(InspectionEvent, event_id)


def get_investigation_by_event(
    session: Session, event_id: str
) -> Investigation | None:
    stmt: Select[tuple[Investigation]] = select(Investigation).where(
        Investigation.event_id == event_id
    )
    return session.scalars(stmt).first()


def get_investigation(
    session: Session, investigation_id: str
) -> Investigation | None:
    return session.get(Investigation, investigation_id)


def create_investigation(
    session: Session,
    *,
    event_id: str,
    investigation_id: str | None = None,
) -> Investigation:
    inv_id = investigation_id or new_uuid()
    investigation = Investigation(
        investigation_id=inv_id,
        event_id=event_id,
        thread_id=inv_id,
        status="processing",
    )
    session.add(investigation)
    session.flush()
    return investigation


def update_investigation(session: Session, investigation: Investigation, **fields: Any) -> Investigation:
    for key, value in fields.items():
        if hasattr(investigation, key):
            setattr(investigation, key, value)
    session.add(investigation)
    session.flush()
    return investigation


def list_investigations(
    session: Session, status: str | None = None, limit: int = 50
) -> list[Investigation]:
    stmt = select(Investigation).order_by(Investigation.created_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(Investigation.status == status)
    return list(session.scalars(stmt).all())


def fetch_recent_events(
    session: Session,
    *,
    booth_id: str,
    defect_type: str,
    as_of: datetime,
    window_minutes: int,
) -> list[InspectionEvent]:
    """Return matching booth/defect events within the rolling window ending at as_of."""
    start = as_of - timedelta(minutes=window_minutes)
    as_of_naive = as_of.replace(tzinfo=None) if as_of.tzinfo else as_of
    start_naive = start.replace(tzinfo=None) if start.tzinfo else start
    stmt = (
        select(InspectionEvent)
        .where(InspectionEvent.booth_id == booth_id)
        .where(InspectionEvent.defect_type == defect_type)
        .where(InspectionEvent.timestamp >= start_naive)
        .where(InspectionEvent.timestamp <= as_of_naive)
        .order_by(InspectionEvent.timestamp.asc())
    )
    return list(session.scalars(stmt).all())


def create_action_ticket(
    session: Session,
    *,
    investigation_id: str,
    event_id: str,
    ticket_type: str,
    priority: str,
    title: str,
    description: str,
    sop_references: list[dict[str, Any]] | None,
    approved_by: str,
    ticket_id: str | None = None,
) -> ActionTicket:
    """Insert a ticket idempotently (unique on investigation_id)."""
    existing = session.scalars(
        select(ActionTicket).where(ActionTicket.investigation_id == investigation_id)
    ).first()
    if existing is not None:
        return existing

    ticket = ActionTicket(
        ticket_id=ticket_id or new_uuid(),
        investigation_id=investigation_id,
        event_id=event_id,
        ticket_type=ticket_type,
        priority=priority,
        title=title,
        description=description,
        sop_references_json=sop_references or [],
        status="open",
        approved_by=approved_by,
    )
    session.add(ticket)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        existing = session.scalars(
            select(ActionTicket).where(ActionTicket.investigation_id == investigation_id)
        ).first()
        if existing is None:
            raise
        return existing
    return ticket


def list_tickets(session: Session, status: str | None = None, limit: int = 100) -> list[ActionTicket]:
    stmt = select(ActionTicket).order_by(ActionTicket.created_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(ActionTicket.status == status)
    return list(session.scalars(stmt).all())


def get_ticket_for_investigation(
    session: Session, investigation_id: str
) -> ActionTicket | None:
    return session.scalars(
        select(ActionTicket).where(ActionTicket.investigation_id == investigation_id)
    ).first()


def add_audit_event(
    session: Session,
    *,
    investigation_id: str,
    node_name: str,
    action: str,
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    record = AuditEvent(
        investigation_id=investigation_id,
        node_name=node_name,
        action=action,
        details_json=details or {},
    )
    session.add(record)
    session.flush()
    return record


def list_audit_events(session: Session, investigation_id: str) -> list[AuditEvent]:
    stmt = (
        select(AuditEvent)
        .where(AuditEvent.investigation_id == investigation_id)
        .order_by(AuditEvent.created_at.asc())
    )
    return list(session.scalars(stmt).all())


# ---------------------------------------------------------------------------
# Plant context queries (v2) — used by specialist agent tools.
# ---------------------------------------------------------------------------


def _naive(ts: datetime) -> datetime:
    return ts.replace(tzinfo=None) if ts.tzinfo else ts


def list_booths(session: Session) -> list[Booth]:
    return list(session.scalars(select(Booth).order_by(Booth.booth_id)).all())


def fetch_telemetry(
    session: Session, *, booth_id: str, start: datetime, end: datetime
) -> list[TelemetryReading]:
    """Telemetry readings for one booth in [start, end], oldest first."""
    stmt = (
        select(TelemetryReading)
        .where(TelemetryReading.booth_id == booth_id)
        .where(TelemetryReading.ts >= _naive(start))
        .where(TelemetryReading.ts <= _naive(end))
        .order_by(TelemetryReading.ts.asc())
    )
    return list(session.scalars(stmt).all())


def fetch_maintenance_logs(
    session: Session, *, booth_id: str, before: datetime, limit: int = 10
) -> list[MaintenanceLog]:
    """Most recent maintenance entries for a booth at or before a time."""
    stmt = (
        select(MaintenanceLog)
        .where(MaintenanceLog.booth_id == booth_id)
        .where(MaintenanceLog.ts <= _naive(before))
        .order_by(MaintenanceLog.ts.desc())
        .limit(limit)
    )
    return list(session.scalars(stmt).all())


def get_active_batch(
    session: Session, *, booth_id: str, as_of: datetime
) -> MaterialBatch | None:
    """The batch most recently started in a booth at or before as_of."""
    stmt = (
        select(MaterialBatch)
        .where(MaterialBatch.booth_id == booth_id)
        .where(MaterialBatch.started_at <= _naive(as_of))
        .order_by(MaterialBatch.started_at.desc())
    )
    return session.scalars(stmt).first()


def fetch_booth_events(
    session: Session, *, booth_id: str, start: datetime, end: datetime
) -> list[InspectionEvent]:
    """All inspection events (any defect type) for a booth in a window."""
    stmt = (
        select(InspectionEvent)
        .where(InspectionEvent.booth_id == booth_id)
        .where(InspectionEvent.timestamp >= _naive(start))
        .where(InspectionEvent.timestamp <= _naive(end))
        .order_by(InspectionEvent.timestamp.asc())
    )
    return list(session.scalars(stmt).all())


def add_investigation_step(
    session: Session,
    *,
    investigation_id: str,
    node: str,
    kind: str,
    payload: dict[str, Any] | None = None,
    namespace: str = "",
) -> InvestigationStep:
    """Append a streamed step with the next sequence number for the investigation."""
    last = session.scalars(
        select(InvestigationStep.seq)
        .where(InvestigationStep.investigation_id == investigation_id)
        .order_by(InvestigationStep.seq.desc())
    ).first()
    step = InvestigationStep(
        investigation_id=investigation_id,
        seq=(last or 0) + 1,
        node=node,
        namespace=namespace,
        kind=kind,
        payload_json=payload or {},
    )
    session.add(step)
    session.flush()
    return step


def list_investigation_steps(
    session: Session, investigation_id: str
) -> list[InvestigationStep]:
    stmt = (
        select(InvestigationStep)
        .where(InvestigationStep.investigation_id == investigation_id)
        .order_by(InvestigationStep.seq.asc())
    )
    return list(session.scalars(stmt).all())


def enqueue_notification(
    session: Session,
    *,
    investigation_id: str,
    kind: str,
    payload: dict[str, Any] | None = None,
) -> NotificationOutbox:
    """Add one pending notification, unless the same kind is already queued for it."""
    existing = session.scalars(
        select(NotificationOutbox)
        .where(NotificationOutbox.investigation_id == investigation_id)
        .where(NotificationOutbox.kind == kind)
    ).first()
    if existing is not None:
        return existing
    row = NotificationOutbox(investigation_id=investigation_id, kind=kind, payload_json=payload or {})
    session.add(row)
    session.flush()
    return row


def list_notifications(session: Session, investigation_id: str) -> list[NotificationOutbox]:
    stmt = (
        select(NotificationOutbox)
        .where(NotificationOutbox.investigation_id == investigation_id)
        .order_by(NotificationOutbox.notification_id.asc())
    )
    return list(session.scalars(stmt).all())

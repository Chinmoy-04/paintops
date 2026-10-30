"""Data-access helpers for events, investigations, tickets, and audit."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database.models import ActionTicket, AuditEvent, InspectionEvent, Investigation, new_uuid
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

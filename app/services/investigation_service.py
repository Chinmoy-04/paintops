"""Orchestration: start investigations and resume approvals."""

from __future__ import annotations

import logging
from typing import Any

from langgraph.types import Command
from sqlalchemy.orm import Session

from app.database.models import new_uuid
from app.database.repository import (
    add_audit_event,
    create_inspection_event,
    create_investigation,
    get_investigation,
    get_investigation_by_event,
    get_ticket_for_investigation,
    list_investigations,
    update_investigation,
)
from app.graph.builder import get_compiled_graph
from app.schemas.decision import DecisionRequest, DecisionResponse
from app.schemas.event import InspectionEventCreate

logger = logging.getLogger(__name__)


def start_investigation(
    session: Session, payload: InspectionEventCreate
) -> dict[str, Any]:
    """
    Validate/store event and run the LangGraph workflow until interrupt or end.

    Idempotent on event_id: returns existing investigation if already present.
    """
    event, created = create_inspection_event(session, payload)
    existing_inv = get_investigation_by_event(session, event.event_id)
    if existing_inv is not None:
        session.commit()
        return {
            "event_id": event.event_id,
            "investigation_id": existing_inv.investigation_id,
            "thread_id": existing_inv.thread_id,
            "status": existing_inv.status,
            "message": "Existing investigation returned (idempotent replay).",
            "created": False,
        }

    investigation = create_investigation(session, event_id=event.event_id)
    add_audit_event(
        session,
        investigation_id=investigation.investigation_id,
        node_name="api",
        action="event_received",
        details={"event_id": event.event_id, "new_event": created},
    )
    session.commit()

    graph = get_compiled_graph()
    event_dict = payload.model_dump(mode="json")
    config = {"configurable": {"thread_id": investigation.thread_id}}
    initial_state = {
        "event": event_dict,
        "investigation_id": investigation.investigation_id,
        "thread_id": investigation.thread_id,
        "errors": [],
    }

    try:
        result = graph.invoke(initial_state, config=config)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Graph failed for %s", investigation.investigation_id)
        inv = get_investigation(session, investigation.investigation_id)
        if inv:
            update_investigation(session, inv, status="failed")
            add_audit_event(
                session,
                investigation_id=investigation.investigation_id,
                node_name="api",
                action="investigation_failed",
                details={"error": str(exc)},
            )
            session.commit()
        raise

    # Refresh status from DB (nodes update it).
    session.expire_all()
    inv = get_investigation(session, investigation.investigation_id)
    status = inv.status if inv else "processing"

    # If graph interrupted, status should already be awaiting_approval.
    # Detect interrupt via graph state next nodes.
    snapshot = graph.get_state(config)
    if snapshot and snapshot.next:
        status = "awaiting_approval"
        if inv and inv.status != "awaiting_approval":
            update_investigation(session, inv, status="awaiting_approval")
            session.commit()

    message = {
        "awaiting_approval": "Investigation completed and is waiting for human review.",
        "monitored": "Investigation recorded as monitor-only; no ticket created.",
        "approved": "Investigation already approved.",
        "rejected": "Investigation already rejected.",
        "failed": "Investigation failed.",
        "invalid": "Event failed validation; investigation closed without analysis.",
    }.get(status, f"Investigation status: {status}")

    return {
        "event_id": event.event_id,
        "investigation_id": investigation.investigation_id,
        "thread_id": investigation.thread_id,
        "status": status,
        "message": message,
        "created": True,
        "result_keys": list(result.keys()) if isinstance(result, dict) else [],
    }


def apply_decision(
    session: Session, investigation_id: str, decision: DecisionRequest
) -> DecisionResponse:
    """Resume a paused graph thread with an approve/reject decision (idempotent)."""
    inv = get_investigation(session, investigation_id)
    if inv is None:
        raise LookupError(f"Investigation not found: {investigation_id}")

    if inv.status in {"approved", "rejected"}:
        ticket = get_ticket_for_investigation(session, investigation_id)
        return DecisionResponse(
            investigation_id=investigation_id,
            status=inv.status,
            ticket_id=ticket.ticket_id if ticket else None,
            message="Decision already recorded; returning existing outcome.",
        )

    if inv.status != "awaiting_approval":
        raise ValueError(
            f"Investigation {investigation_id} is not awaiting approval "
            f"(status={inv.status})."
        )

    graph = get_compiled_graph()
    config = {"configurable": {"thread_id": inv.thread_id}}
    resume_payload = {
        "decision": decision.decision,
        "reviewer": decision.reviewer,
        "comment": decision.comment,
    }
    try:
        graph.invoke(Command(resume=resume_payload), config=config)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Resume failed for %s", investigation_id)
        session.rollback()
        session.expire_all()
        failed = get_investigation(session, investigation_id)
        if failed:
            update_investigation(session, failed, status="failed")
            add_audit_event(
                session,
                investigation_id=investigation_id,
                node_name="api",
                action="resume_failed",
                details={"error": str(exc), "decision": decision.decision},
            )
            session.commit()
        raise

    session.expire_all()
    inv = get_investigation(session, investigation_id)
    assert inv is not None
    ticket = get_ticket_for_investigation(session, investigation_id)
    return DecisionResponse(
        investigation_id=investigation_id,
        status=inv.status,
        ticket_id=ticket.ticket_id if ticket else None,
        message=(
            "Approved; ticket created."
            if decision.decision == "approved"
            else "Rejected; no ticket created."
        ),
    )


def investigation_detail(session: Session, investigation_id: str) -> dict[str, Any]:
    inv = get_investigation(session, investigation_id)
    if inv is None:
        raise LookupError(investigation_id)
    ticket = get_ticket_for_investigation(session, investigation_id)
    event = inv.event
    return {
        "investigation_id": inv.investigation_id,
        "thread_id": inv.thread_id,
        "status": inv.status,
        "recurrence_count": inv.recurrence_count,
        "severity": inv.severity,
        "suspected_cause": inv.suspected_cause,
        "evidence": inv.evidence_json,
        "sop_references": inv.sop_references_json,
        "proposed_action": inv.proposed_action,
        "analysis_provider": inv.analysis_provider,
        "ticket_draft": inv.ticket_draft_json,
        "reviewer": inv.reviewer,
        "review_comment": inv.review_comment,
        "created_at": inv.created_at.isoformat() if inv.created_at else None,
        "updated_at": inv.updated_at.isoformat() if inv.updated_at else None,
        "event": {
            "event_id": event.event_id,
            "timestamp": event.timestamp.isoformat(),
            "plant_id": event.plant_id,
            "production_line": event.production_line,
            "booth_id": event.booth_id,
            "body_id": event.body_id,
            "defect_type": event.defect_type,
            "model_confidence": event.model_confidence,
            "telemetry": event.telemetry_json,
            "source": event.source,
        }
        if event
        else None,
        "ticket": {
            "ticket_id": ticket.ticket_id,
            "title": ticket.title,
            "status": ticket.status,
            "priority": ticket.priority,
            "approved_by": ticket.approved_by,
            "approved_at": ticket.approved_at.isoformat() if ticket.approved_at else None,
        }
        if ticket
        else None,
    }


def investigation_summaries(
    session: Session, status: str | None = None
) -> list[dict[str, Any]]:
    rows = list_investigations(session, status=status)
    out: list[dict[str, Any]] = []
    for inv in rows:
        event = inv.event
        out.append(
            {
                "investigation_id": inv.investigation_id,
                "event_id": inv.event_id,
                "status": inv.status,
                "severity": inv.severity,
                "recurrence_count": inv.recurrence_count,
                "booth_id": event.booth_id if event else None,
                "defect_type": event.defect_type if event else None,
                "created_at": inv.created_at.isoformat() if inv.created_at else None,
            }
        )
    return out

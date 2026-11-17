"""Orchestration: accept events, hand runs to the RunManager, apply reviewer decisions."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.database.repository import (
    add_audit_event,
    create_inspection_event,
    create_investigation,
    get_investigation,
    get_investigation_by_event,
    get_ticket_for_investigation,
    list_investigations,
)
from app.graph.routing import MAX_REVISIONS
from app.schemas.decision import DecisionRequest, DecisionResponse
from app.schemas.event import InspectionEventCreate
from app.services.run_manager import RunManager

logger = logging.getLogger(__name__)


def accept_event(session: Session, payload: InspectionEventCreate) -> dict[str, Any]:
    """Store the event and create its investigation. Does not run the graph.

    Idempotent on event_id: an event that already has an investigation returns it with
    `created=False`. When `created` is True the result carries `initial_state`, and the
    caller starts the run with `RunManager.start` (see `submit_event`).
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
    return {
        "event_id": event.event_id,
        "investigation_id": investigation.investigation_id,
        "thread_id": investigation.thread_id,
        "status": investigation.status,
        "message": "Investigation accepted and running; follow it on the stream URL.",
        "created": True,
        "initial_state": {
            "event": payload.model_dump(mode="json"),
            "investigation_id": investigation.investigation_id,
            "thread_id": investigation.thread_id,
            "errors": [],
        },
    }


def submit_event(session: Session, payload: InspectionEventCreate, manager: RunManager) -> dict[str, Any]:
    """Accept an event and, if it is new, start its run in the background."""
    result = accept_event(session, payload)
    if result["created"]:
        manager.start(result["investigation_id"], result["thread_id"], result.pop("initial_state"))
    return result


async def apply_decision(
    session: Session,
    investigation_id: str,
    decision: DecisionRequest,
    manager: RunManager,
) -> DecisionResponse:
    """Resume a paused graph thread with an approve / reject / revise decision.

    Idempotent for approved and rejected. The resumed run is short (create the ticket
    and queue the notification, or draft a revision), so this waits for it; its steps
    still stream to subscribers. `shield` keeps the run going if the client disconnects.
    """
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

    if inv.status != "awaiting_approval" or manager.is_active(investigation_id):
        raise ValueError(
            f"Investigation {investigation_id} is not awaiting approval "
            f"(status={inv.status})."
        )
    if decision.decision == "revise" and (inv.revision_count or 0) >= MAX_REVISIONS:
        raise ValueError(
            f"Investigation {investigation_id} already used its {MAX_REVISIONS} revisions; "
            "approve or reject it."
        )

    resume_payload = {
        "decision": decision.decision,
        "reviewer": decision.reviewer,
        "comment": decision.comment,
    }
    status = await asyncio.shield(manager.resume(investigation_id, inv.thread_id, resume_payload))
    if status == "failed":
        raise RuntimeError(f"Resuming investigation {investigation_id} failed; see its audit log.")

    session.expire_all()
    inv = get_investigation(session, investigation_id)
    assert inv is not None
    ticket = get_ticket_for_investigation(session, investigation_id)
    message = {
        "approved": "Approved; ticket created.",
        "rejected": "Rejected; no ticket created.",
        "revise": "Revision requested; a new draft is awaiting review.",
    }[decision.decision]
    return DecisionResponse(
        investigation_id=investigation_id,
        status=inv.status,
        ticket_id=ticket.ticket_id if ticket else None,
        message=message,
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
        "findings": inv.findings_json or [],
        "revision_count": inv.revision_count or 0,
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

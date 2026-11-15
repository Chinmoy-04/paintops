"""LangGraph node implementations for PaintOps."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from langgraph.types import interrupt

from app.database.repository import (
    add_audit_event,
    get_investigation,
    update_investigation,
)
from app.database.session import get_session_factory
from app.graph.routing import decide_route
from app.graph.state import PaintOpsState
from app.schemas.event import DEFECT_TYPES, InspectionEventCreate
from app.services.analysis_service import analyse_deviation
from app.services.ticket_service import build_ticket_draft, persist_approved_ticket
from app.tools.quality_history import get_recent_booth_defects
from app.tools.sop_search import search_sops

logger = logging.getLogger(__name__)


def _session():
    return get_session_factory()()


def validate_event(state: PaintOpsState) -> dict[str, Any]:
    """Validate event schema and supported defect type."""
    event = state.get("event") or {}
    errors: list[str] = []
    try:
        parsed = InspectionEventCreate.model_validate(event)
        if parsed.defect_type not in DEFECT_TYPES:
            errors.append(f"Unsupported defect_type: {parsed.defect_type}")
        normalised = parsed.model_dump(mode="json")
    except Exception as exc:  # noqa: BLE001
        errors.append(str(exc))
        normalised = event

    investigation_id = state.get("investigation_id")
    if investigation_id and not errors:
        session = _session()
        try:
            add_audit_event(
                session,
                investigation_id=investigation_id,
                node_name="validate_event",
                action="event_validated",
                details={"event_id": normalised.get("event_id")},
            )
            session.commit()
        finally:
            session.close()

    result: dict[str, Any] = {"event": normalised}
    if errors:
        result["errors"] = list(state.get("errors") or []) + errors
    return result


def fetch_line_context(state: PaintOpsState) -> dict[str, Any]:
    """Query recent same-booth/same-defect events."""
    event = state.get("event") or {}
    ts_raw = event.get("timestamp")
    if isinstance(ts_raw, str):
        as_of = datetime.fromisoformat(ts_raw.replace("Z", "+00:00")).replace(tzinfo=None)
    elif isinstance(ts_raw, datetime):
        as_of = ts_raw.replace(tzinfo=None) if ts_raw.tzinfo else ts_raw
    else:
        as_of = datetime.now(UTC).replace(tzinfo=None)

    session = _session()
    try:
        recent, count = get_recent_booth_defects(
            session,
            booth_id=str(event.get("booth_id")),
            defect_type=str(event.get("defect_type")),
            as_of=as_of,
        )
        investigation_id = state.get("investigation_id")
        if investigation_id:
            inv = get_investigation(session, investigation_id)
            if inv:
                update_investigation(session, inv, recurrence_count=count)
            add_audit_event(
                session,
                investigation_id=investigation_id,
                node_name="fetch_line_context",
                action="history_queried",
                details={"recurrence_count": count},
            )
        session.commit()
    finally:
        session.close()

    return {"recent_events": recent, "recurrence_count": count}


def retrieve_sop(state: PaintOpsState) -> dict[str, Any]:
    """Retrieve top-k synthetic SOP chunks."""
    event = state.get("event") or {}
    defect = str(event.get("defect_type", ""))
    results = search_sops(defect_type=defect, extra_context="paint booth quality")
    investigation_id = state.get("investigation_id")
    if investigation_id:
        session = _session()
        try:
            add_audit_event(
                session,
                investigation_id=investigation_id,
                node_name="retrieve_sop",
                action="sop_retrieved",
                details={
                    "count": len(results),
                    "doc_ids": [r.get("doc_id") for r in results],
                },
            )
            session.commit()
        finally:
            session.close()
    return {"sop_results": results}


def analyse_deviation_node(state: PaintOpsState) -> dict[str, Any]:
    """Produce structured analysis via demo rules or LLM adapter."""
    event = state.get("event") or {}
    recent = state.get("recent_events") or []
    sops = state.get("sop_results") or []
    recurrence = int(state.get("recurrence_count") or 0)
    analysis = analyse_deviation(
        event=event,
        recent_events=recent,
        sop_results=sops,
        recurrence_count=recurrence,
    )
    payload = analysis.model_dump()
    investigation_id = state.get("investigation_id")
    if investigation_id:
        session = _session()
        try:
            inv = get_investigation(session, investigation_id)
            if inv:
                update_investigation(
                    session,
                    inv,
                    severity=analysis.severity,
                    suspected_cause=analysis.suspected_cause,
                    evidence_json=analysis.evidence,
                    sop_references_json=analysis.sop_references,
                    analysis_provider=analysis.analysis_provider,
                )
            add_audit_event(
                session,
                investigation_id=investigation_id,
                node_name="analyse_deviation",
                action="analysis_completed",
                details={
                    "severity": analysis.severity,
                    "analysis_provider": analysis.analysis_provider,
                },
            )
            session.commit()
        finally:
            session.close()
    return {"analysis": payload, "severity": analysis.severity}


def route_decision(state: PaintOpsState) -> dict[str, Any]:
    """Apply deterministic Python routing policy."""
    route = decide_route(
        recurrence_count=int(state.get("recurrence_count") or 0),
        severity=str(state.get("severity") or "low"),
    )
    investigation_id = state.get("investigation_id")
    if investigation_id:
        session = _session()
        try:
            add_audit_event(
                session,
                investigation_id=investigation_id,
                node_name="route_decision",
                action="route_selected",
                details={"route": route},
            )
            session.commit()
        finally:
            session.close()
    return {"route": route}


def draft_ticket(state: PaintOpsState) -> dict[str, Any]:
    """Create a structured ticket draft for human review."""
    draft = build_ticket_draft(
        event=state.get("event") or {},
        analysis=state.get("analysis") or {},
        sop_results=state.get("sop_results") or [],
    )
    payload = draft.model_dump()
    investigation_id = state.get("investigation_id")
    if investigation_id:
        session = _session()
        try:
            inv = get_investigation(session, investigation_id)
            if inv:
                update_investigation(
                    session,
                    inv,
                    status="awaiting_approval",
                    proposed_action=draft.title,
                    ticket_draft_json=payload,
                )
            add_audit_event(
                session,
                investigation_id=investigation_id,
                node_name="draft_ticket",
                action="ticket_drafted",
                details={"title": draft.title},
            )
            session.commit()
        finally:
            session.close()
    return {"ticket_draft": payload}


def human_review(state: PaintOpsState) -> dict[str, Any]:
    """
    Pause for human approval via LangGraph interrupt().

    Important: interrupt is called before side effects. On resume, code before
    interrupt may re-run — keep it free of irreversible writes.
    """
    decision = interrupt(
        {
            "type": "approval_required",
            "investigation_id": state.get("investigation_id"),
            "ticket_draft": state.get("ticket_draft"),
            "evidence_summary": (state.get("analysis") or {}).get("evidence"),
            "sop_references": (state.get("analysis") or {}).get("sop_references"),
            "message": (
                "Approve or reject this SYNTHETIC action ticket. "
                "Not for real production decisions."
            ),
        }
    )
    # Expected resume payload: {decision, reviewer, comment?}
    if not isinstance(decision, dict):
        decision = {"decision": "rejected", "reviewer": "unknown", "comment": str(decision)}

    status = decision.get("decision", "rejected")
    if status not in {"approved", "rejected"}:
        status = "rejected"
    return {
        "approval_decision": decision,
        "approval_status": status,
        "reviewer": decision.get("reviewer", "unknown"),
        "review_comment": decision.get("comment") or "",
    }


def create_ticket(state: PaintOpsState) -> dict[str, Any]:
    """Insert exactly one action ticket after approval."""
    investigation_id = str(state.get("investigation_id"))
    event = state.get("event") or {}
    draft = state.get("ticket_draft") or {}
    reviewer = state.get("reviewer") or "unknown"
    session = _session()
    try:
        ticket_id = persist_approved_ticket(
            session,
            investigation_id=investigation_id,
            event_id=str(event.get("event_id")),
            draft=draft,
            approved_by=reviewer,
        )
        inv = get_investigation(session, investigation_id)
        if inv:
            update_investigation(
                session,
                inv,
                status="approved",
                reviewer=reviewer,
                review_comment=state.get("review_comment") or None,
            )
        add_audit_event(
            session,
            investigation_id=investigation_id,
            node_name="create_ticket",
            action="ticket_created",
            details={"ticket_id": ticket_id, "approved_by": reviewer},
        )
        session.commit()
    finally:
        session.close()
    return {"ticket_id": ticket_id}


def record_rejection(state: PaintOpsState) -> dict[str, Any]:
    """Record rejection without creating a ticket."""
    investigation_id = str(state.get("investigation_id"))
    session = _session()
    try:
        inv = get_investigation(session, investigation_id)
        if inv:
            update_investigation(
                session,
                inv,
                status="rejected",
                reviewer=state.get("reviewer"),
                review_comment=state.get("review_comment") or None,
            )
        add_audit_event(
            session,
            investigation_id=investigation_id,
            node_name="record_rejection",
            action="approval_rejected",
            details={
                "reviewer": state.get("reviewer"),
                "comment": state.get("review_comment"),
            },
        )
        session.commit()
    finally:
        session.close()
    return {}


def record_observation(state: PaintOpsState) -> dict[str, Any]:
    """Mark investigation as monitored (no ticket)."""
    investigation_id = str(state.get("investigation_id"))
    session = _session()
    try:
        inv = get_investigation(session, investigation_id)
        if inv:
            update_investigation(session, inv, status="monitored")
        add_audit_event(
            session,
            investigation_id=investigation_id,
            node_name="record_observation",
            action="observation_recorded",
            details={"route": "monitor"},
        )
        session.commit()
    finally:
        session.close()
    return {}


def record_invalid(state: PaintOpsState) -> dict[str, Any]:
    """Terminal node for events that failed validation: mark invalid, no analysis."""
    investigation_id = state.get("investigation_id")
    errors = list(state.get("errors") or [])
    if investigation_id:
        session = _session()
        try:
            inv = get_investigation(session, investigation_id)
            if inv:
                update_investigation(session, inv, status="invalid")
            add_audit_event(
                session,
                investigation_id=investigation_id,
                node_name="record_invalid",
                action="event_rejected_invalid",
                details={"errors": errors},
            )
            session.commit()
        finally:
            session.close()
    return {}

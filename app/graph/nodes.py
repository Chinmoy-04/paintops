"""Node implementations for the PaintOps parent graph.

Each node reads the shared state, does one job, writes its audit row, and returns
only the keys it changed. Database writes happen inside nodes so the business
records always match what the graph has done.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.errors import GraphBubbleUp
from langgraph.types import interrupt

from app.database.repository import (
    add_audit_event,
    enqueue_notification,
    get_investigation,
    update_investigation,
)
from app.database.session import get_session_factory
from app.graph.routing import MAX_REVISIONS, decide_route
from app.graph.specialists import plan_for, specialist_graph
from app.graph.specialists.base import SpecialistInput
from app.graph.state import PaintOpsState
from app.schemas.analysis import AnalysisResult
from app.schemas.event import DEFECT_TYPES, InspectionEventCreate, event_timestamp
from app.schemas.finding import Finding
from app.services.analysis_service import demo_cause_hypothesis, demo_severity
from app.services.llm import provider_name
from app.services.ticket_service import build_ticket_draft, persist_approved_ticket
from app.tools.quality_history import get_recent_booth_defects

logger = logging.getLogger(__name__)


def _session():
    return get_session_factory()()


def _record(
    investigation_id: str | None,
    node: str,
    action: str,
    details: dict[str, Any] | None = None,
    **investigation_fields: Any,
) -> None:
    """Write one audit row and, optionally, update investigation columns."""
    if not investigation_id:
        return
    session = _session()
    try:
        if investigation_fields:
            inv = get_investigation(session, investigation_id)
            if inv:
                update_investigation(session, inv, **investigation_fields)
        add_audit_event(
            session,
            investigation_id=investigation_id,
            node_name=node,
            action=action,
            details=details or {},
        )
        session.commit()
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Intake and triage
# ---------------------------------------------------------------------------


def intake(state: PaintOpsState) -> dict[str, Any]:
    """Validate the event schema and defect type."""
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

    if not errors:
        _record(
            state.get("investigation_id"),
            "intake",
            "event_validated",
            {"event_id": normalised.get("event_id")},
        )

    result: dict[str, Any] = {"event": normalised}
    if errors:
        result["errors"] = list(state.get("errors") or []) + errors
    return result


def triage(state: PaintOpsState) -> dict[str, Any]:
    """Count recent same-booth, same-defect events (the recurrence signal)."""
    event = state.get("event") or {}
    try:
        as_of = event_timestamp(event)
    except ValueError:
        as_of = datetime.now(UTC).replace(tzinfo=None)

    session = _session()
    try:
        recent, count = get_recent_booth_defects(
            session,
            booth_id=str(event.get("booth_id")),
            defect_type=str(event.get("defect_type")),
            as_of=as_of,
        )
    finally:
        session.close()

    _record(
        state.get("investigation_id"),
        "triage",
        "history_queried",
        {"recurrence_count": count},
        recurrence_count=count,
    )
    return {"recent_events": recent, "recurrence_count": count}


def plan_investigation(state: PaintOpsState) -> dict[str, Any]:
    """Supervisor: decide which specialists investigate this defect.

    The plan is a fixed defect -> specialists map (app/graph/specialists). The fan
    out itself happens on the outgoing edge (routing.dispatch_specialists).
    """
    defect = str((state.get("event") or {}).get("defect_type"))
    planned = plan_for(defect)
    _record(
        state.get("investigation_id"),
        "plan_investigation",
        "investigation_planned",
        {"defect_type": defect, "specialists": planned},
    )
    return {"specialists_planned": planned}


# ---------------------------------------------------------------------------
# Specialists (run in parallel via Send)
# ---------------------------------------------------------------------------


def make_specialist_node(name: str) -> Callable[[SpecialistInput, RunnableConfig], dict[str, Any]]:
    """Wrap a specialist subgraph so that its failure becomes a `failed` Finding.

    The subgraph is invoked inside this node rather than added as a node itself:
    that lets us catch an exception that survives the agent's RetryPolicy and turn
    it into an honest failed finding, so one broken specialist cannot sink the
    whole investigation. Passing `config` through keeps it a proper nested
    subgraph (it shares the parent's checkpointer and shows up when streaming).
    """

    def run_specialist(state: SpecialistInput, config: RunnableConfig) -> dict[str, Any]:
        try:
            out = specialist_graph(name).invoke(dict(state), config)
            finding = out["finding"]
        except GraphBubbleUp:
            raise  # interrupts and other control flow must reach the parent
        except Exception as exc:  # noqa: BLE001
            logger.exception("%s specialist failed", name)
            finding = Finding.failed(name, f"{type(exc).__name__}: {exc}", provider_name()).model_dump(mode="json")  # type: ignore[arg-type]

        _record(
            state.get("investigation_id"),
            f"{name}_agent",
            "specialist_finished",
            {
                "status": finding["status"],
                "confidence": finding["confidence"],
                "tool_calls": [t["name"] for t in finding.get("tool_calls") or []],
                "error": finding.get("error"),
            },
        )
        return {"findings": [finding]}

    run_specialist.__name__ = f"{name}_agent"
    return run_specialist


def synthesise(state: PaintOpsState) -> dict[str, Any]:
    """Merge the specialists' findings into one analysis with a deterministic severity."""
    event = state.get("event") or {}
    defect = str(event.get("defect_type"))
    confidence = float(event.get("model_confidence") or 0)
    recurrence = int(state.get("recurrence_count") or 0)
    findings = sorted(state.get("findings") or [], key=lambda f: f["specialist"])
    ok = [f for f in findings if f["status"] == "ok"]
    failed = [f for f in findings if f["status"] == "failed"]

    # Severity: confidence + recurrence (same rules as before), nudged up from low
    # to medium when a specialist found a strong signal. Never above medium from
    # findings alone, so the LLM-facing part cannot push an event into a ticket.
    severity = demo_severity(defect, confidence, recurrence)
    strongest = max((f["confidence"] for f in ok), default=0.0)
    if severity == "low" and strongest >= 0.75:
        severity = "medium"

    signals = sorted((f for f in ok if f["confidence"] >= 0.5), key=lambda f: -f["confidence"])
    if signals:
        suspected = " ".join(f["hypothesis"] for f in signals[:2])
    else:
        suspected = demo_cause_hypothesis(defect) + " No specialist found a specific signal."

    seen: set[str] = set()
    sop_refs: list[dict[str, Any]] = []
    for f in findings:
        for ref in f.get("sop_references") or []:
            key = str(ref.get("chunk_id") or ref.get("doc_id"))
            if key not in seen:
                seen.add(key)
                sop_refs.append(ref)
    sop_search_ran = any(
        t.get("name") == "search_sops" for f in ok for t in f.get("tool_calls") or []
    )
    if not sop_search_ran:
        suspected += " SOP retrieval did not complete."
    elif not sop_refs:
        suspected += " No relevant synthetic SOP chunks were retrieved."

    evidence = [
        f"Defect type: {defect}",
        f"Model confidence: {confidence:.2f}",
        f"Booth: {event.get('booth_id')}",
        f"Recurrence count in window (incl. current): {recurrence}",
    ]
    evidence += [f"[{f['specialist']}] {line}" for f in ok for line in f.get("evidence") or []]
    evidence += [f"[{f['specialist']}] specialist failed: {f.get('error')}" for f in failed]

    uncertainty = "SYNTHETIC DEMO: causes are hypotheses only; not confirmed root causes."
    if failed:
        uncertainty += " Missing checks from failed specialists: " + ", ".join(f["specialist"] for f in failed) + "."

    analysis = AnalysisResult(
        suspected_cause=suspected,
        evidence=evidence,
        uncertainty=uncertainty,
        severity=severity,  # type: ignore[arg-type]
        sop_references=sop_refs,
        no_relevant_sop_found=not sop_refs,
        analysis_provider=",".join(sorted({f.get("provider") or "unknown" for f in findings})) or "none",
        rationale=(
            f"severity={severity} from model confidence {confidence}, recurrence {recurrence}, "
            f"strongest specialist confidence {strongest}"
        ),
    )

    _record(
        state.get("investigation_id"),
        "synthesise",
        "analysis_completed",
        {
            "severity": analysis.severity,
            "analysis_provider": analysis.analysis_provider,
            "findings_ok": len(ok),
            "findings_failed": len(failed),
        },
        severity=analysis.severity,
        suspected_cause=analysis.suspected_cause,
        evidence_json=analysis.evidence,
        sop_references_json=analysis.sop_references,
        analysis_provider=analysis.analysis_provider,
        findings_json=findings,
    )
    return {"analysis": analysis.model_dump(), "severity": analysis.severity, "sop_results": sop_refs}


# ---------------------------------------------------------------------------
# Routing, drafting, human review
# ---------------------------------------------------------------------------


def route_decision(state: PaintOpsState) -> dict[str, Any]:
    """Apply the deterministic Python routing policy."""
    route = decide_route(
        recurrence_count=int(state.get("recurrence_count") or 0),
        severity=str(state.get("severity") or "low"),
    )
    _record(state.get("investigation_id"), "route_decision", "route_selected", {"route": route})
    return {"route": route}


def draft_ticket(state: PaintOpsState) -> dict[str, Any]:
    """Draft the action ticket; on a revision loop, include the reviewer's notes."""
    draft = build_ticket_draft(
        event=state.get("event") or {},
        analysis=state.get("analysis") or {},
        sop_results=state.get("sop_results") or [],
    )
    notes = list(state.get("revision_notes") or [])
    if notes:
        lines = "\n".join(f"- Revision {i}: {note}" for i, note in enumerate(notes, start=1))
        draft = draft.model_copy(
            update={
                "title": f"{draft.title} (rev {len(notes)})",
                "description": (
                    f"{draft.description}\n\nReviewer revision requests "
                    f"(recorded; demo drafts do not rewrite the content):\n{lines}"
                ),
            }
        )
    payload = draft.model_dump()
    _record(
        state.get("investigation_id"),
        "draft_ticket",
        "ticket_drafted",
        {"title": draft.title, "revision": len(notes)},
        status="awaiting_approval",
        proposed_action=draft.title,
        ticket_draft_json=payload,
        revision_count=len(notes),
    )
    return {"ticket_draft": payload}


def human_review(state: PaintOpsState) -> dict[str, Any]:
    """
    Pause for a human decision via LangGraph interrupt().

    On resume the node runs again from the top and interrupt() returns the
    reviewer's answer, so nothing irreversible may happen before the interrupt.
    """
    count = int(state.get("revision_count") or 0)
    can_revise = count < MAX_REVISIONS
    allowed = ["approved", "rejected"] + (["revise"] if can_revise else [])
    decision = interrupt(
        {
            "type": "approval_required",
            "investigation_id": state.get("investigation_id"),
            "ticket_draft": state.get("ticket_draft"),
            "evidence_summary": (state.get("analysis") or {}).get("evidence"),
            "sop_references": (state.get("analysis") or {}).get("sop_references"),
            "allowed_decisions": allowed,
            "revision_count": count,
            "message": (
                "Approve, reject, or request a revision of this SYNTHETIC action ticket. "
                "Not for real production decisions."
            ),
        }
    )
    # Expected resume payload: {decision, reviewer, comment?}
    if not isinstance(decision, dict):
        decision = {"decision": "rejected", "reviewer": "unknown", "comment": str(decision)}

    reviewer = decision.get("reviewer", "unknown")
    comment = decision.get("comment") or ""
    status = decision.get("decision", "rejected")
    base = {"approval_decision": decision, "reviewer": reviewer, "review_comment": comment}

    if status == "revise":
        if not can_revise:
            _record(
                state.get("investigation_id"),
                "human_review",
                "revision_refused",
                {"reviewer": reviewer, "revision_count": count, "max_revisions": MAX_REVISIONS},
            )
            return {**base, "approval_status": "revise_refused"}
        notes = list(state.get("revision_notes") or []) + [comment or "(no comment given)"]
        _record(
            state.get("investigation_id"),
            "human_review",
            "revision_requested",
            {"reviewer": reviewer, "comment": comment, "revision": len(notes)},
        )
        return {**base, "approval_status": "revise", "revision_notes": notes, "revision_count": len(notes)}

    if status not in {"approved", "rejected"}:
        status = "rejected"
    return {**base, "approval_status": status}


# ---------------------------------------------------------------------------
# Outcomes
# ---------------------------------------------------------------------------


def create_ticket(state: PaintOpsState) -> dict[str, Any]:
    """Insert exactly one action ticket after approval."""
    investigation_id = str(state.get("investigation_id"))
    event = state.get("event") or {}
    reviewer = state.get("reviewer") or "unknown"
    session = _session()
    try:
        ticket_id = persist_approved_ticket(
            session,
            investigation_id=investigation_id,
            event_id=str(event.get("event_id")),
            draft=state.get("ticket_draft") or {},
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
    _record(
        state.get("investigation_id"),
        "record_rejection",
        "approval_rejected",
        {"reviewer": state.get("reviewer"), "comment": state.get("review_comment")},
        status="rejected",
        reviewer=state.get("reviewer"),
        review_comment=state.get("review_comment") or None,
    )
    return {}


def notify(state: PaintOpsState) -> dict[str, Any]:
    """Queue a notification about the outcome. Delivery is n8n's job (Phase 6)."""
    investigation_id = str(state.get("investigation_id"))
    event = state.get("event") or {}
    kind = "ticket_created" if state.get("ticket_id") else "approval_rejected"
    payload = {
        "event_id": event.get("event_id"),
        "booth_id": event.get("booth_id"),
        "defect_type": event.get("defect_type"),
        "severity": state.get("severity"),
        "ticket_id": state.get("ticket_id"),
        "reviewer": state.get("reviewer"),
    }
    session = _session()
    try:
        row = enqueue_notification(session, investigation_id=investigation_id, kind=kind, payload=payload)
        add_audit_event(
            session,
            investigation_id=investigation_id,
            node_name="notify",
            action="notification_queued",
            details={"kind": kind, "notification_id": row.notification_id},
        )
        session.commit()
    finally:
        session.close()
    return {"notification": {"kind": kind, **payload}}


def record_observation(state: PaintOpsState) -> dict[str, Any]:
    """Mark investigation as monitored (no ticket)."""
    _record(
        state.get("investigation_id"),
        "record_observation",
        "observation_recorded",
        {"route": "monitor"},
        status="monitored",
    )
    return {}


def record_invalid(state: PaintOpsState) -> dict[str, Any]:
    """Terminal node for events that failed validation: mark invalid, no analysis."""
    _record(
        state.get("investigation_id"),
        "record_invalid",
        "event_rejected_invalid",
        {"errors": list(state.get("errors") or [])},
        status="invalid",
    )
    return {}

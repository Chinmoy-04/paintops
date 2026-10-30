"""Ticket draft construction and idempotent persistence helpers."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.database.repository import create_action_ticket
from app.schemas.ticket import TicketDraft


def build_ticket_draft(
    *,
    event: dict[str, Any],
    analysis: dict[str, Any],
    sop_results: list[dict[str, Any]],
) -> TicketDraft:
    """Create a structured draft clearly marking hypotheses and evidence gaps."""
    defect = event.get("defect_type", "unknown")
    severity = analysis.get("severity", "medium")
    no_sop = bool(analysis.get("no_relevant_sop_found"))
    sop_refs = analysis.get("sop_references") or [
        {"doc_id": s.get("doc_id"), "title": s.get("title"), "chunk_id": s.get("chunk_id")}
        for s in sop_results
    ]

    ticket_type = (
        "maintenance_inspection"
        if defect in {"orange_peel", "runs_sags", "uneven_coverage"}
        else "quality_inspection"
    )
    title = f"[SYNTHETIC] Inspect {defect} at {event.get('booth_id')}"
    description_parts = [
        "SYNTHETIC DEMO TICKET — not a real work order.",
        f"Event: {event.get('event_id')} | Body: {event.get('body_id')}",
        f"Suspected cause (hypothesis): {analysis.get('suspected_cause')}",
        f"Uncertainty: {analysis.get('uncertainty')}",
        "Evidence:",
        *[f"- {e}" for e in (analysis.get("evidence") or [])],
    ]
    if no_sop:
        description_parts.append(
            "WARNING: no_relevant_sop_found=true — manual SOP verification required."
        )
    else:
        description_parts.append(
            "SOP references: "
            + ", ".join(str(r.get("doc_id")) for r in sop_refs if r.get("doc_id"))
        )

    return TicketDraft(
        ticket_type=ticket_type,  # type: ignore[arg-type]
        priority=severity if severity in {"low", "medium", "high", "critical"} else "medium",  # type: ignore[arg-type]
        title=title,
        description="\n".join(description_parts),
        sop_references=list(sop_refs),
        requires_manual_sop_verification=no_sop,
    )


def persist_approved_ticket(
    session: Session,
    *,
    investigation_id: str,
    event_id: str,
    draft: dict[str, Any],
    approved_by: str,
) -> str:
    """Insert exactly one ticket for the investigation (idempotent)."""
    ticket = create_action_ticket(
        session,
        investigation_id=investigation_id,
        event_id=event_id,
        ticket_type=draft.get("ticket_type", "quality_inspection"),
        priority=draft.get("priority", "medium"),
        title=draft.get("title", "Untitled"),
        description=draft.get("description", ""),
        sop_references=draft.get("sop_references") or [],
        approved_by=approved_by,
    )
    return ticket.ticket_id

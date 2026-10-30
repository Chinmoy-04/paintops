"""Graph approval / rejection / monitor path tests (DEMO_MODE)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.database.repository import (
    create_inspection_event,
    create_investigation,
    get_ticket_for_investigation,
    list_audit_events,
)
from app.database.session import get_session_factory
from app.graph.builder import build_graph
from app.schemas.event import InspectionEventCreate


def _seed_event(payload: dict, *, with_history: int = 0):
    session = get_session_factory()()
    try:
        base_ts = datetime(2026, 10, 30, 9, 15, 0)
        for i in range(with_history):
            hist = {
                **payload,
                "event_id": f"{payload['event_id']}-H{i}",
                "timestamp": (base_ts - timedelta(minutes=10 * (i + 1))).isoformat() + "Z",
                "body_id": f"CAR-H{i}",
            }
            create_inspection_event(session, InspectionEventCreate.model_validate(hist))
        event, _ = create_inspection_event(
            session, InspectionEventCreate.model_validate(payload)
        )
        inv = create_investigation(session, event_id=event.event_id)
        session.commit()
        return inv.investigation_id, inv.thread_id, payload
    finally:
        session.close()


def test_monitor_route_finishes_without_ticket(sample_event_payload: dict) -> None:
    sample_event_payload["event_id"] = "QC-MON-1"
    sample_event_payload["model_confidence"] = 0.7
    inv_id, thread_id, payload = _seed_event(sample_event_payload, with_history=0)
    graph = build_graph(checkpointer=MemorySaver())
    result = graph.invoke(
        {
            "event": InspectionEventCreate.model_validate(payload).model_dump(mode="json"),
            "investigation_id": inv_id,
            "thread_id": thread_id,
        },
        config={"configurable": {"thread_id": thread_id}},
    )
    assert result.get("route") == "monitor"
    session = get_session_factory()()
    try:
        assert get_ticket_for_investigation(session, inv_id) is None
        audits = list_audit_events(session, inv_id)
        assert any(a.action == "observation_recorded" for a in audits)
    finally:
        session.close()


def test_action_required_pauses_then_approval_creates_one_ticket(
    sample_event_payload: dict,
) -> None:
    sample_event_payload["event_id"] = "QC-ACT-1"
    sample_event_payload["model_confidence"] = 0.94
    inv_id, thread_id, payload = _seed_event(sample_event_payload, with_history=2)
    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": thread_id}}
    graph.invoke(
        {
            "event": InspectionEventCreate.model_validate(payload).model_dump(mode="json"),
            "investigation_id": inv_id,
            "thread_id": thread_id,
        },
        config=config,
    )
    snap = graph.get_state(config)
    assert snap.next == ("human_review",) or "human_review" in snap.next

    graph.invoke(
        Command(
            resume={
                "decision": "approved",
                "reviewer": "quality_manager_demo",
                "comment": "ok",
            }
        ),
        config=config,
    )
    session = get_session_factory()()
    try:
        ticket = get_ticket_for_investigation(session, inv_id)
        assert ticket is not None
        # Idempotent re-approval path: create_ticket uses unique constraint.
        ticket_id = ticket.ticket_id
        # Replay create via second approval attempt on already finished graph is N/A;
        # instead call persist twice indirectly by checking single ticket row.
        from sqlalchemy import select, func
        from app.database.models import ActionTicket

        count = session.scalar(select(func.count()).select_from(ActionTicket))
        assert count == 1
        assert ticket_id == ticket.ticket_id
    finally:
        session.close()


def test_rejection_creates_no_ticket(sample_event_payload: dict) -> None:
    sample_event_payload["event_id"] = "QC-REJ-1"
    sample_event_payload["model_confidence"] = 0.97
    sample_event_payload["defect_type"] = "runs_sags"
    inv_id, thread_id, payload = _seed_event(sample_event_payload, with_history=0)
    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": thread_id}}
    graph.invoke(
        {
            "event": InspectionEventCreate.model_validate(payload).model_dump(mode="json"),
            "investigation_id": inv_id,
            "thread_id": thread_id,
        },
        config=config,
    )
    graph.invoke(
        Command(
            resume={
                "decision": "rejected",
                "reviewer": "quality_manager_demo",
                "comment": "insufficient evidence",
            }
        ),
        config=config,
    )
    session = get_session_factory()()
    try:
        assert get_ticket_for_investigation(session, inv_id) is None
        audits = list_audit_events(session, inv_id)
        assert any(a.action == "approval_rejected" for a in audits)
    finally:
        session.close()


def test_repeated_approval_does_not_duplicate_tickets(
    sample_event_payload: dict,
) -> None:
    from app.services.ticket_service import persist_approved_ticket

    sample_event_payload["event_id"] = "QC-IDEM-1"
    inv_id, _, payload = _seed_event(sample_event_payload, with_history=2)
    session = get_session_factory()()
    try:
        draft = {
            "ticket_type": "quality_inspection",
            "priority": "high",
            "title": "t",
            "description": "d",
            "sop_references": [],
        }
        t1 = persist_approved_ticket(
            session,
            investigation_id=inv_id,
            event_id=payload["event_id"],
            draft=draft,
            approved_by="r1",
        )
        t2 = persist_approved_ticket(
            session,
            investigation_id=inv_id,
            event_id=payload["event_id"],
            draft=draft,
            approved_by="r1",
        )
        session.commit()
        assert t1 == t2
    finally:
        session.close()

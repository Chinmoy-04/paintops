"""Phase 1 tests: supervisor fan-out, findings reducer, failures, retries, revise loop."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command, Send
from sqlalchemy import func, select

from app.database.models import ActionTicket
from app.database.repository import (
    create_inspection_event,
    create_investigation,
    get_investigation,
    get_ticket_for_investigation,
    list_audit_events,
    list_notifications,
)
from app.database.seed import WINDOW_END, seed_plant
from app.database.session import get_session_factory
from app.graph.builder import build_graph, reset_compiled_graph
from app.graph.routing import MAX_REVISIONS, dispatch_specialists
from app.graph.specialists import base as specialist_base
from app.graph.specialists import specialist_graph
from app.schemas.decision import DecisionRequest
from app.schemas.event import InspectionEventCreate
from app.services import investigation_service
from app.services.llm import ScriptedChatModel
from app.tools import plant_context


def _start(payload: dict, *, history: int = 0, seed: bool = False) -> tuple[Any, dict, str]:
    """Store the event (+ optional same-booth history / seeded plant) and run to the first stop."""
    session = get_session_factory()()
    try:
        if seed:
            seed_plant(session)
        ts = InspectionEventCreate.model_validate(payload).timestamp.replace(tzinfo=None)
        for i in range(history):
            create_inspection_event(
                session,
                InspectionEventCreate.model_validate(
                    {
                        **payload,
                        "event_id": f"{payload['event_id']}-H{i}",
                        "body_id": f"CAR-H{i}",
                        "timestamp": (ts - timedelta(minutes=10 * (i + 1))).isoformat() + "Z",
                    }
                ),
            )
        event, _ = create_inspection_event(session, InspectionEventCreate.model_validate(payload))
        inv = create_investigation(session, event_id=event.event_id)
        session.commit()
        inv_id, thread_id = inv.investigation_id, inv.thread_id
    finally:
        session.close()

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
    return graph, config, inv_id


def _audit_actions(inv_id: str) -> list[tuple[str, str]]:
    session = get_session_factory()()
    try:
        return [(a.node_name, a.action) for a in list_audit_events(session, inv_id)]
    finally:
        session.close()


def _resume(graph, config, decision: str, comment: str = "") -> None:
    graph.invoke(
        Command(resume={"decision": decision, "reviewer": "qm_demo", "comment": comment}),
        config=config,
    )


@pytest.fixture(autouse=True)
def _fresh_specialists():
    specialist_graph.cache_clear()
    yield
    specialist_graph.cache_clear()


def test_dispatch_specialists_sends_one_task_per_planned_specialist() -> None:
    sends = dispatch_specialists(
        {
            "event": {"event_id": "E1"},
            "investigation_id": "I1",
            "recurrence_count": 2,
            "specialists_planned": ["equipment", "process"],
        }
    )
    assert all(isinstance(s, Send) for s in sends)
    assert [s.node for s in sends] == ["equipment_agent", "process_agent"]
    assert sends[0].arg == {"event": {"event_id": "E1"}, "investigation_id": "I1", "recurrence_count": 2}


@pytest.mark.parametrize(
    ("defect", "expected"),
    [
        ("orange_peel", {"environment", "equipment", "process"}),
        ("uneven_coverage", {"equipment", "process"}),
        ("color_mismatch", {"environment", "process"}),
    ],
)
def test_fan_out_runs_only_the_mapped_specialists(
    sample_event_payload: dict, defect: str, expected: set[str]
) -> None:
    sample_event_payload.update(event_id=f"QC-FAN-{defect}", defect_type=defect, model_confidence=0.7)
    graph, config, inv_id = _start(sample_event_payload)

    findings = graph.get_state(config).values["findings"]
    assert {f["specialist"] for f in findings} == expected
    assert len(findings) == len(expected)  # reducer appended one per specialist, none lost
    finished = {node for node, action in _audit_actions(inv_id) if action == "specialist_finished"}
    assert finished == {f"{name}_agent" for name in expected}


def test_specialists_find_the_planted_booth_03_pattern(sample_event_payload: dict) -> None:
    sample_event_payload.update(
        event_id="QC-PLANT-1",
        booth_id="BOOTH-03",
        timestamp=WINDOW_END.isoformat() + "Z",
        model_confidence=0.93,
    )
    graph, config, inv_id = _start(sample_event_payload, seed=True)

    values = graph.get_state(config).values
    by_name = {f["specialist"]: f for f in values["findings"]}
    assert by_name["environment"]["status"] == "ok" and by_name["environment"]["confidence"] >= 0.5
    assert "humidity up" in by_name["environment"]["hypothesis"]
    assert "spray_nozzle overdue" in by_name["equipment"]["hypothesis"]
    assert [t["name"] for t in by_name["process"]["tool_calls"]] == ["search_sops", "get_active_material_batch"]
    assert "humidity" in values["analysis"]["suspected_cause"]
    assert any(r["doc_id"] == "SOP-PAINT-002" for r in values["analysis"]["sop_references"])
    # Seeded history gives 5 orange-peel events in the window -> action required.
    assert values["route"] == "action_required"

    session = get_session_factory()()
    try:
        inv = get_investigation(session, inv_id)
        assert inv.status == "awaiting_approval"
        assert {f["specialist"] for f in inv.findings_json} == {"environment", "equipment", "process"}
    finally:
        session.close()


def test_failed_specialist_does_not_block_the_investigation(
    sample_event_payload: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*args, **kwargs):
        raise ConnectionError("telemetry historian unreachable")

    monkeypatch.setattr(plant_context, "telemetry_window", broken)
    sample_event_payload.update(event_id="QC-FAIL-1", model_confidence=0.7)
    graph, config, inv_id = _start(sample_event_payload)

    values = graph.get_state(config).values
    by_name = {f["specialist"]: f for f in values["findings"]}
    assert by_name["environment"]["status"] == "failed"
    assert by_name["environment"]["confidence"] == 0.0
    assert "telemetry historian unreachable" in by_name["environment"]["error"]
    assert by_name["equipment"]["status"] == "ok" and by_name["process"]["status"] == "ok"
    assert "environment" in values["analysis"]["uncertainty"]
    assert values["route"] == "monitor"  # the run still reached a decision
    assert ("record_observation", "observation_recorded") in _audit_actions(inv_id)


def test_agent_node_retries_a_flaky_model_call(
    sample_event_payload: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"n": 0}

    def flaky_model(*, demo_script=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("model server busy")
        return ScriptedChatModel(script=list(demo_script or []))

    monkeypatch.setattr(specialist_base, "get_chat_model", flaky_model)
    sample_event_payload.update(event_id="QC-RETRY-1", defect_type="color_mismatch", model_confidence=0.7)
    graph, config, _ = _start(sample_event_payload)

    findings = graph.get_state(config).values["findings"]
    assert all(f["status"] == "ok" for f in findings)
    assert calls["n"] > len(findings)  # at least one extra call: the retry


def test_revise_loop_is_capped_and_no_ticket_exists_before_approval(sample_event_payload: dict) -> None:
    sample_event_payload.update(event_id="QC-REV-1", model_confidence=0.94)
    graph, config, inv_id = _start(sample_event_payload, history=2)

    def ticket_count() -> int:
        session = get_session_factory()()
        try:
            return session.scalar(select(func.count()).select_from(ActionTicket)) or 0
        finally:
            session.close()

    assert graph.get_state(config).next == ("human_review",)
    assert ticket_count() == 0

    for i in range(1, MAX_REVISIONS + 1):
        _resume(graph, config, "revise", f"add nozzle photo {i}")
        snap = graph.get_state(config)
        assert snap.next == ("human_review",)
        assert snap.values["ticket_draft"]["title"].endswith(f"(rev {i})")
        assert ticket_count() == 0

    # Out of revisions: the request is refused and review is asked again.
    pending = graph.get_state(config).tasks[0].interrupts[0].value
    assert pending["allowed_decisions"] == ["approved", "rejected"]
    _resume(graph, config, "revise", "one more change")
    snap = graph.get_state(config)
    assert snap.next == ("human_review",)
    assert snap.values["revision_count"] == MAX_REVISIONS
    assert ticket_count() == 0

    _resume(graph, config, "approved", "ok")
    session = get_session_factory()()
    try:
        ticket = get_ticket_for_investigation(session, inv_id)
        assert ticket is not None and ticket.title.endswith(f"(rev {MAX_REVISIONS})")
        assert "add nozzle photo 1" in ticket.description
        inv = get_investigation(session, inv_id)
        assert inv.status == "approved" and inv.revision_count == MAX_REVISIONS
        assert [n.kind for n in list_notifications(session, inv_id)] == ["ticket_created"]
    finally:
        session.close()
    actions = [a for _, a in _audit_actions(inv_id)]
    assert actions.count("revision_requested") == MAX_REVISIONS
    assert actions.count("revision_refused") == 1
    assert ticket_count() == 1


def test_rejection_queues_a_rejection_notification(sample_event_payload: dict) -> None:
    sample_event_payload.update(event_id="QC-REJ-N", model_confidence=0.97, defect_type="runs_sags")
    graph, config, inv_id = _start(sample_event_payload)
    _resume(graph, config, "rejected", "not convinced")

    session = get_session_factory()()
    try:
        assert get_ticket_for_investigation(session, inv_id) is None
        notes = list_notifications(session, inv_id)
        assert [n.kind for n in notes] == ["approval_rejected"]
        assert notes[0].status == "pending"
    finally:
        session.close()


def test_decision_replay_through_the_service_is_idempotent(sample_event_payload: dict) -> None:
    reset_compiled_graph()
    sample_event_payload.update(event_id="QC-IDEM-SVC", model_confidence=0.97, defect_type="runs_sags")
    session = get_session_factory()()
    try:
        started = investigation_service.start_investigation(
            session, InspectionEventCreate.model_validate(sample_event_payload)
        )
        assert started["status"] == "awaiting_approval"
        inv_id = started["investigation_id"]
        decision = DecisionRequest(decision="approved", reviewer="qm_demo")
        first = investigation_service.apply_decision(session, inv_id, decision)
        second = investigation_service.apply_decision(session, inv_id, decision)
        assert first.status == second.status == "approved"
        assert first.ticket_id == second.ticket_id is not None
        assert session.scalar(select(func.count()).select_from(ActionTicket)) == 1
    finally:
        session.close()
        reset_compiled_graph()


def test_a_tool_that_never_ran_is_reported_as_not_checked(
    sample_event_payload: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Cap of 1 model turn: each agent asks for a tool but is stopped before it runs.
    monkeypatch.setattr(specialist_base, "MAX_TOOL_ROUNDS", 1)
    sample_event_payload.update(event_id="QC-NOTRUN-1", model_confidence=0.7)
    graph, config, _ = _start(sample_event_payload)

    values = graph.get_state(config).values
    for f in values["findings"]:
        assert f["tool_calls"] == []
        assert "incomplete" in f["hypothesis"] and f["confidence"] == 0.0
        assert "not found" not in f["hypothesis"].lower()
    assert "SOP retrieval did not complete" in values["analysis"]["suspected_cause"]
    assert "No relevant synthetic SOP" not in values["analysis"]["suspected_cause"]

"""Phase 0 tests: invalid-event path, failed resume, synthetic plant seed."""

from __future__ import annotations

from datetime import timedelta

import pytest
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy import func, select

from app.database.models import (
    Booth,
    InspectionEvent,
    MaintenanceLog,
    MaterialBatch,
    TelemetryReading,
)
from app.database.repository import (
    add_investigation_step,
    create_inspection_event,
    create_investigation,
    fetch_telemetry,
    get_active_batch,
    get_investigation,
    get_ticket_for_investigation,
    list_audit_events,
    list_investigation_steps,
)
from app.database.seed import LINES, WINDOW_END, booth_line, seed_plant
from app.database.session import get_session_factory
from app.graph.builder import build_graph
from app.schemas.decision import DecisionRequest
from app.schemas.event import InspectionEventCreate
from app.services import investigation_service


def test_invalid_event_ends_in_record_invalid_without_analysis(
    sample_event_payload: dict,
) -> None:
    session = get_session_factory()()
    try:
        event, _ = create_inspection_event(
            session, InspectionEventCreate.model_validate(sample_event_payload)
        )
        inv = create_investigation(session, event_id=event.event_id)
        session.commit()
        inv_id, thread_id = inv.investigation_id, inv.thread_id
    finally:
        session.close()

    bad_event = {**sample_event_payload, "defect_type": "not_a_real_defect"}
    graph = build_graph(checkpointer=MemorySaver())
    result = graph.invoke(
        {"event": bad_event, "investigation_id": inv_id, "thread_id": thread_id},
        config={"configurable": {"thread_id": thread_id}},
    )

    assert result.get("errors")
    assert "analysis" not in result
    assert "route" not in result
    session = get_session_factory()()
    try:
        assert get_investigation(session, inv_id).status == "invalid"
        actions = [a.action for a in list_audit_events(session, inv_id)]
        assert "event_rejected_invalid" in actions
        assert "analysis_completed" not in actions
    finally:
        session.close()


def test_failed_resume_marks_investigation_failed(
    sample_event_payload: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = get_session_factory()()
    try:
        event, _ = create_inspection_event(
            session, InspectionEventCreate.model_validate(sample_event_payload)
        )
        inv = create_investigation(session, event_id=event.event_id)
        inv.status = "awaiting_approval"
        session.commit()
        inv_id = inv.investigation_id
    finally:
        session.close()

    class ExplodingGraph:
        def invoke(self, *args, **kwargs):
            raise RuntimeError("checkpoint store unavailable")

    monkeypatch.setattr(investigation_service, "get_compiled_graph", lambda: ExplodingGraph())

    session = get_session_factory()()
    try:
        with pytest.raises(RuntimeError):
            investigation_service.apply_decision(
                session,
                inv_id,
                DecisionRequest(decision="approved", reviewer="qa_demo"),
            )
    finally:
        session.close()

    session = get_session_factory()()
    try:
        assert get_investigation(session, inv_id).status == "failed"
        assert get_ticket_for_investigation(session, inv_id) is None
        actions = [a.action for a in list_audit_events(session, inv_id)]
        assert "resume_failed" in actions
    finally:
        session.close()


def test_seed_plant_layout_and_planted_patterns() -> None:
    session = get_session_factory()()
    try:
        counts = seed_plant(session)
        session.commit()

        assert counts["booths"] == 9
        assert session.scalar(select(func.count()).select_from(Booth)) == 9
        assert len(LINES) == 3 and booth_line("BOOTH-03") == "PAINT-LINE-01"
        assert session.scalar(select(func.count()).select_from(TelemetryReading)) > 9 * 190
        assert session.scalar(select(func.count()).select_from(MaintenanceLog)) == 27
        assert session.scalar(select(func.count()).select_from(MaterialBatch)) == 10

        # BOOTH-03 humidity drift: last hour clearly above the early baseline.
        early = fetch_telemetry(
            session,
            booth_id="BOOTH-03",
            start=WINDOW_END - timedelta(hours=48),
            end=WINDOW_END - timedelta(hours=40),
        )
        late = fetch_telemetry(
            session,
            booth_id="BOOTH-03",
            start=WINDOW_END - timedelta(hours=1),
            end=WINDOW_END,
        )
        avg = lambda rows: sum(r.humidity_pct for r in rows) / len(rows)  # noqa: E731
        assert avg(late) - avg(early) > 15

        # LINE-02 basecoat booth switched to the low-viscosity batch.
        batch = get_active_batch(session, booth_id="BOOTH-05", as_of=WINDOW_END)
        assert batch is not None and batch.batch_id.endswith("-B") and batch.viscosity_s < 22

        defects = {
            e.defect_type
            for e in session.scalars(select(InspectionEvent)).all()
        }
        assert {"orange_peel", "fisheye_craters", "color_mismatch"} <= defects
    finally:
        session.close()


def test_seed_plant_is_idempotent() -> None:
    session = get_session_factory()()
    try:
        first = seed_plant(session)
        session.commit()
        second = seed_plant(session)
        session.commit()
        assert first["events"] > 0
        assert second == {k: 0 for k in second}
    finally:
        session.close()


def test_investigation_steps_get_sequential_numbers(sample_event_payload: dict) -> None:
    session = get_session_factory()()
    try:
        event, _ = create_inspection_event(
            session, InspectionEventCreate.model_validate(sample_event_payload)
        )
        inv = create_investigation(session, event_id=event.event_id)
        for node in ["intake", "triage", "synthesise"]:
            add_investigation_step(
                session, investigation_id=inv.investigation_id, node=node, kind="node_finished"
            )
        session.commit()
        steps = list_investigation_steps(session, inv.investigation_id)
        assert [s.seq for s in steps] == [1, 2, 3]
        assert [s.node for s in steps] == ["intake", "triage", "synthesise"]
    finally:
        session.close()

"""FastAPI endpoint tests: async ingest, SSE stream, inspection endpoints, decisions."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.database.session import init_db, reset_engine
from app.graph.builder import reset_compiled_graph
from app.main import app

KEY = {"X-PaintOps-Key": "paintops-dev-key"}


@pytest.fixture
def client(sample_event_payload):
    reset_compiled_graph()
    reset_engine()
    init_db()
    with TestClient(app) as c:
        yield c
    reset_compiled_graph()


def follow(client: TestClient, investigation_id: str, **params) -> list[dict]:
    """Read the investigation's SSE stream until the server closes it.

    Returns [{"event", "id", "data"}, ...]. The stream replays stored steps, follows
    the live run, and ends with an `end` event once no run is in progress.
    """
    events: list[dict] = []
    current: dict = {}
    with client.stream("GET", f"/api/investigations/{investigation_id}/stream", params=params) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        for line in r.iter_lines():
            if not line:
                if current:
                    events.append(current)
                    current = {}
                continue
            field, _, value = line.partition(": ")
            if field == "data":
                current["data"] = json.loads(value)
            elif field in {"event", "id"}:
                current[field] = value
    if current:
        events.append(current)
    return events


def post_and_wait(client: TestClient, payload: dict) -> dict:
    r = client.post("/api/events", json=payload, headers=KEY)
    assert r.status_code in {200, 202}, r.text
    body = r.json()
    follow(client, body["investigation_id"])
    return body


def test_health(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "demo_mode" in body


def test_post_event_returns_202_at_once_and_replay_is_idempotent(
    client: TestClient, sample_event_payload: dict
) -> None:
    sample_event_payload["event_id"] = "QC-API-1"
    sample_event_payload["model_confidence"] = 0.7
    r1 = client.post("/api/events", json=sample_event_payload, headers=KEY)
    assert r1.status_code == 202
    body1 = r1.json()
    assert body1["event_id"] == "QC-API-1"
    assert body1["status"] == "processing"
    assert body1["stream_url"] == f"/api/investigations/{body1['investigation_id']}/stream"
    follow(client, body1["investigation_id"])

    r2 = client.post("/api/events", json=sample_event_payload, headers=KEY)
    assert r2.status_code == 200
    assert r2.json()["investigation_id"] == body1["investigation_id"]
    assert r2.json()["status"] == "monitored"


def test_ingest_requires_api_key(client: TestClient, sample_event_payload: dict) -> None:
    assert client.post("/api/events", json=sample_event_payload).status_code == 401
    bad = {"X-PaintOps-Key": "wrong"}
    assert client.post("/api/events", json=sample_event_payload, headers=bad).status_code == 401
    assert client.post("/api/scenarios/booth08_minor").status_code == 401
    # Read endpoints are open (the UI reads them from the browser).
    assert client.get("/api/investigations").status_code == 200


def test_stream_replays_steps_in_order_and_ends(client: TestClient, sample_event_payload: dict) -> None:
    sample_event_payload.update(event_id="QC-API-STREAM", model_confidence=0.97, defect_type="dust_inclusion")
    inv_id = client.post("/api/events", json=sample_event_payload, headers=KEY).json()["investigation_id"]

    live = follow(client, inv_id)
    kinds = [e["event"] for e in live]
    assert kinds[0] == "run_started"
    assert kinds[-1] == "end"
    assert live[-1]["data"]["status"] == "awaiting_approval"
    assert "interrupt" in kinds
    # Ids are the step seq: 1, 2, 3, ... with no gaps or repeats.
    ids = [int(e["id"]) for e in live if "id" in e]
    assert ids == list(range(1, len(ids) + 1))

    nodes = [e["data"]["node"] for e in live if e["event"] == "node" and e["data"]["namespace"] == ""]
    assert nodes[:3] == ["intake", "triage", "plan_investigation"]
    assert nodes[-1] == "draft_ticket"
    # Specialist subgraph steps carry their namespace; tool calls arrive as custom events.
    inner = [e for e in live if e["event"] == "node" and e["data"]["namespace"]]
    assert {e["data"]["namespace"].split(":")[0] for e in inner} == {"environment_agent", "equipment_agent", "process_agent"}
    calls = [e["data"] for e in live if e["event"] == "tool_call"]
    results = [e["data"] for e in live if e["event"] == "tool_result"]
    assert calls and len(calls) == len(results)
    assert {"search_sops"} <= {c["payload"]["tool"] for c in calls}

    # A second connection replays the same stored steps; Last-Event-ID skips ahead.
    replay = follow(client, inv_id)
    assert [e.get("id") for e in replay] == [e.get("id") for e in live]
    after = follow(client, inv_id, after_seq=ids[-3])
    assert [int(e["id"]) for e in after if "id" in e] == ids[-2:]

    steps = client.get(f"/api/investigations/{inv_id}/steps").json()
    assert [s["seq"] for s in steps] == ids


def test_stream_last_event_id_header(client: TestClient, sample_event_payload: dict) -> None:
    sample_event_payload.update(event_id="QC-API-LEID", model_confidence=0.7)
    inv_id = post_and_wait(client, sample_event_payload)["investigation_id"]
    total = len(client.get(f"/api/investigations/{inv_id}/steps").json())
    with client.stream(
        "GET", f"/api/investigations/{inv_id}/stream", headers={"Last-Event-ID": str(total - 1)}
    ) as r:
        ids = [line.split(": ")[1] for line in r.iter_lines() if line.startswith("id: ")]
    assert ids == [str(total)]


def test_unknown_investigation_404(client: TestClient) -> None:
    assert client.get("/api/investigations/nope/stream").status_code == 404
    assert client.get("/api/investigations/nope/steps").status_code == 404
    assert client.get("/api/investigations/nope/history").status_code == 404


def test_list_and_detail(client: TestClient, sample_event_payload: dict) -> None:
    sample_event_payload["event_id"] = "QC-API-2"
    sample_event_payload["model_confidence"] = 0.7
    inv_id = post_and_wait(client, sample_event_payload)["investigation_id"]

    listed = client.get("/api/investigations").json()
    assert any(i["investigation_id"] == inv_id for i in listed)

    detail = client.get(f"/api/investigations/{inv_id}").json()
    assert detail["investigation_id"] == inv_id
    assert detail["event"]["event_id"] == "QC-API-2"


def test_history_lists_checkpoints_newest_first(client: TestClient, sample_event_payload: dict) -> None:
    sample_event_payload.update(event_id="QC-API-HIST", model_confidence=0.97, defect_type="runs_sags")
    inv_id = post_and_wait(client, sample_event_payload)["investigation_id"]
    history = client.get(f"/api/investigations/{inv_id}/history").json()
    assert history[0]["next"] == ["human_review"]
    assert history[0]["interrupts"][0]["value"]["type"] == "approval_required"
    assert history[-1]["source"] == "input"
    steps = [h["step"] for h in history]
    assert steps == sorted(steps, reverse=True)


def _awaiting(client: TestClient, payload: dict, event_id: str) -> str:
    payload.update(event_id=event_id, model_confidence=0.97, defect_type="runs_sags")
    inv_id = post_and_wait(client, payload)["investigation_id"]
    assert client.get(f"/api/investigations/{inv_id}").json()["status"] == "awaiting_approval"
    return inv_id


def test_approval_flow_via_api(client: TestClient, sample_event_payload: dict) -> None:
    # Recurrence: three same-booth, same-defect events in the window.
    base = dict(sample_event_payload, booth_id="BOOTH-03", defect_type="orange_peel", model_confidence=0.94)
    for i, ts in enumerate(["2026-10-30T08:55:00Z", "2026-10-30T09:05:00Z", "2026-10-30T09:15:00Z"]):
        post_and_wait(client, dict(base, event_id=f"QC-API-ACT-{i}", body_id=f"CAR-{i}", timestamp=ts))

    pending = client.get("/api/investigations", params={"status": "awaiting_approval"}).json()
    assert pending, "expected at least one awaiting_approval investigation"
    inv_id = pending[0]["investigation_id"]

    decision = client.post(
        f"/api/investigations/{inv_id}/decision",
        json={"decision": "approved", "reviewer": "quality_manager_demo", "comment": "Approve inspection task."},
    )
    assert decision.status_code == 200
    body = decision.json()
    assert body["status"] == "approved"
    assert body["ticket_id"]

    again = client.post(
        f"/api/investigations/{inv_id}/decision",
        json={"decision": "approved", "reviewer": "quality_manager_demo"},
    ).json()
    assert again["ticket_id"] == body["ticket_id"]

    # The resumed run's steps were stored after the first run's.
    kinds = [s["kind"] for s in client.get(f"/api/investigations/{inv_id}/steps").json()]
    assert kinds.count("run_started") == 2 and kinds[-1] == "run_finished"

    tickets = client.get("/api/tickets").json()
    assert [t["ticket_id"] for t in tickets] == [body["ticket_id"]]
    assert client.get("/api/tickets", params={"status": "closed"}).json() == []


def test_revise_via_api_then_cap(client: TestClient, sample_event_payload: dict) -> None:
    inv_id = _awaiting(client, sample_event_payload, "QC-API-REV")
    url = f"/api/investigations/{inv_id}/decision"
    for n in (1, 2):
        r = client.post(url, json={"decision": "revise", "reviewer": "qm", "comment": f"note {n}"})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "awaiting_approval"
        detail = client.get(f"/api/investigations/{inv_id}").json()
        assert detail["revision_count"] == n
        assert f"note {n}" in detail["ticket_draft"]["description"]

    third = client.post(url, json={"decision": "revise", "reviewer": "qm", "comment": "again"})
    assert third.status_code == 409
    assert client.post(url, json={"decision": "rejected", "reviewer": "qm"}).json()["status"] == "rejected"


def test_decision_on_unknown_or_unready_investigation(client: TestClient, sample_event_payload: dict) -> None:
    r = client.post("/api/investigations/nope/decision", json={"decision": "approved", "reviewer": "qm"})
    assert r.status_code == 404
    sample_event_payload.update(event_id="QC-API-MON", model_confidence=0.7)
    inv_id = post_and_wait(client, sample_event_payload)["investigation_id"]
    r = client.post(f"/api/investigations/{inv_id}/decision", json={"decision": "approved", "reviewer": "qm"})
    assert r.status_code == 409


def test_scenarios_seed_and_run(client: TestClient) -> None:
    r = client.post("/api/scenarios/booth03_orange_peel", headers=KEY)
    assert r.status_code == 202
    inv_id = r.json()["investigation_id"]
    end = follow(client, inv_id)[-1]
    assert end["data"]["status"] == "awaiting_approval"

    r = client.post("/api/scenarios/booth08_minor", headers=KEY)
    assert follow(client, r.json()["investigation_id"])[-1]["data"]["status"] == "monitored"

    assert client.post("/api/scenarios/nope", headers=KEY).status_code == 404

    booths = client.get("/api/booths").json()
    assert len(booths) == 9
    b3 = next(b for b in booths if b["booth_id"] == "BOOTH-03")
    assert b3["awaiting_approval"] == 1 and b3["latest_telemetry"]["humidity_pct"] is not None

    stats = client.get("/api/stats").json()
    assert stats["investigations_by_status"] == {"awaiting_approval": 1, "monitored": 1}
    assert stats["awaiting_approval"] == 1
    assert stats["events_total"] > 50
    assert stats["active_runs"] == 0


def test_graph_structure(client: TestClient) -> None:
    g = client.get("/api/graph").json()
    ids = {n["id"] for n in g["nodes"]}
    assert {"intake", "environment_agent", "human_review", "notify", "__start__", "__end__"} <= ids
    assert {"source": "draft_ticket", "target": "human_review", "conditional": False} in g["edges"]
    assert set(g["specialists"]) == {"environment", "equipment", "process"}
    assert {n["id"] for n in g["specialists"]["process"]["nodes"]} >= {"agent", "tools", "report"}


def test_plant_feed_carries_run_lifecycle(client: TestClient, sample_event_payload: dict) -> None:
    from app.services.run_manager import get_run_manager

    # Subscribe through the manager (what /api/events/stream does) to avoid an
    # endless HTTP stream in the test.
    manager = get_run_manager()
    queue = client.portal.call(manager.subscribe_feed)
    sample_event_payload.update(event_id="QC-API-FEED", model_confidence=0.7)
    inv_id = post_and_wait(client, sample_event_payload)["investigation_id"]
    items = []
    while not queue.empty():
        items.append(queue.get_nowait())
    client.portal.call(manager.unsubscribe_feed, queue)
    assert {i["investigation_id"] for i in items} == {inv_id}
    assert items[0]["kind"] == "run_started"
    assert items[-1] == {**items[-1], "kind": "run_finished", "status": "monitored"}
    assert all(i["node"] for i in items)


def test_cors_allows_only_configured_origins(client: TestClient) -> None:
    allowed = get_settings().cors_origins[0]
    ok = client.options(
        "/api/events",
        headers={"Origin": allowed, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "X-PaintOps-Key"},
    )
    assert ok.headers.get("access-control-allow-origin") == allowed
    bad = client.options(
        "/api/events", headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "POST"}
    )
    assert "access-control-allow-origin" not in bad.headers

"""FastAPI endpoint tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.database.session import init_db, reset_engine
from app.graph.builder import reset_compiled_graph
from app.main import app


@pytest.fixture
def client(sample_event_payload):
    reset_compiled_graph()
    reset_engine()
    init_db()
    with TestClient(app) as c:
        yield c
    reset_compiled_graph()


def test_health(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "demo_mode" in body


def test_post_event_and_idempotent_replay(
    client: TestClient, sample_event_payload: dict
) -> None:
    sample_event_payload["event_id"] = "QC-API-1"
    sample_event_payload["model_confidence"] = 0.7
    r1 = client.post("/api/events", json=sample_event_payload)
    assert r1.status_code in {200, 202}
    body1 = r1.json()
    assert body1["event_id"] == "QC-API-1"
    assert "investigation_id" in body1

    r2 = client.post("/api/events", json=sample_event_payload)
    assert r2.status_code in {200, 202}
    body2 = r2.json()
    assert body2["investigation_id"] == body1["investigation_id"]


def test_list_and_detail(client: TestClient, sample_event_payload: dict) -> None:
    sample_event_payload["event_id"] = "QC-API-2"
    sample_event_payload["model_confidence"] = 0.7
    posted = client.post("/api/events", json=sample_event_payload).json()
    inv_id = posted["investigation_id"]

    listed = client.get("/api/investigations").json()
    assert any(i["investigation_id"] == inv_id for i in listed)

    detail = client.get(f"/api/investigations/{inv_id}").json()
    assert detail["investigation_id"] == inv_id
    assert detail["event"]["event_id"] == "QC-API-2"


def test_approval_flow_via_api(client: TestClient, sample_event_payload: dict) -> None:
    # Seed recurrence via multiple posts with different ids same booth/defect.
    base = dict(sample_event_payload)
    base["booth_id"] = "BOOTH-03"
    base["defect_type"] = "orange_peel"
    base["model_confidence"] = 0.94
    timestamps = [
        "2026-10-30T08:55:00Z",
        "2026-10-30T09:05:00Z",
        "2026-10-30T09:15:00Z",
    ]
    for i, ts in enumerate(timestamps):
        evt = dict(base)
        evt["event_id"] = f"QC-API-ACT-{i}"
        evt["body_id"] = f"CAR-{i}"
        evt["timestamp"] = ts
        client.post("/api/events", json=evt)

    # Last event should be awaiting approval due to recurrence.
    pending = client.get(
        "/api/investigations", params={"status": "awaiting_approval"}
    ).json()
    assert pending, "expected at least one awaiting_approval investigation"
    inv_id = pending[0]["investigation_id"]

    decision = client.post(
        f"/api/investigations/{inv_id}/decision",
        json={
            "decision": "approved",
            "reviewer": "quality_manager_demo",
            "comment": "Reviewed synthetic evidence; approve inspection task.",
        },
    )
    assert decision.status_code == 200
    body = decision.json()
    assert body["status"] == "approved"
    assert body["ticket_id"]

    # Idempotent replay
    again = client.post(
        f"/api/investigations/{inv_id}/decision",
        json={"decision": "approved", "reviewer": "quality_manager_demo"},
    ).json()
    assert again["ticket_id"] == body["ticket_id"]

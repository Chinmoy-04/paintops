"""Event ingest, demo scenarios, and the plant-wide live feed."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.security import require_api_key
from app.database.session import get_session
from app.schemas.event import InspectionEventCreate
from app.services.investigation_service import submit_event
from app.services.run_manager import get_run_manager
from app.services.scenarios import SCENARIOS, build_scenario_event

router = APIRouter(prefix="/api", tags=["events"])


class EventAcceptedResponse(BaseModel):
    event_id: str
    investigation_id: str
    thread_id: str
    status: str
    message: str
    stream_url: str


def _accepted(result: dict[str, Any], response: Response) -> EventAcceptedResponse:
    response.status_code = status.HTTP_202_ACCEPTED if result["created"] else status.HTTP_200_OK
    return EventAcceptedResponse(
        event_id=result["event_id"],
        investigation_id=result["investigation_id"],
        thread_id=result["thread_id"],
        status=result["status"],
        message=result["message"],
        stream_url=f"/api/investigations/{result['investigation_id']}/stream",
    )


# These are `async def` on purpose: RunManager.start creates an asyncio task, which
# needs the running event loop. Their database work is a few quick inserts.
@router.post("/events", response_model=EventAcceptedResponse, dependencies=[Depends(require_api_key)])
async def post_event(
    payload: InspectionEventCreate,
    response: Response,
    session: Session = Depends(get_session),
) -> EventAcceptedResponse:
    """Accept a synthetic inspection event and start its investigation in the background.

    Returns 202 at once for a new event (follow it on `stream_url`), or 200 for an
    idempotent replay of an existing event_id.
    """
    return _accepted(submit_event(session, payload, get_run_manager()), response)


@router.post(
    "/scenarios/{name}", response_model=EventAcceptedResponse, dependencies=[Depends(require_api_key)]
)
async def post_scenario(
    name: str,
    response: Response,
    session: Session = Depends(get_session),
) -> EventAcceptedResponse:
    """Create a fresh event for a named demo scenario and investigate it (202)."""
    if name not in SCENARIOS:
        raise HTTPException(status_code=404, detail=f"Unknown scenario. Known: {sorted(SCENARIOS)}")
    payload = build_scenario_event(session, name)
    return _accepted(submit_event(session, payload, get_run_manager()), response)


@router.get("/events/stream", response_class=EventSourceResponse)
async def stream_plant_feed(request: Request) -> AsyncIterable[ServerSentEvent]:
    """Live feed of top-level steps across all investigations (no replay).

    Each event is compact: investigation_id, seq, node, kind, ts, and status on
    run_finished. Open an investigation's own stream for the details.
    """
    manager = get_run_manager()
    queue = manager.subscribe_feed()
    try:
        while not await request.is_disconnected():
            try:
                item = await asyncio.wait_for(queue.get(), timeout=1.0)
            except TimeoutError:
                continue
            yield ServerSentEvent(data=item, event=item["kind"])
    finally:
        manager.unsubscribe_feed(queue)

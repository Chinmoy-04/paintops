"""Investigation list/detail, live stream, stored steps, and checkpoint history."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.sse import EventSourceResponse, ServerSentEvent
from sqlalchemy.orm import Session

from app.database.repository import get_investigation, list_investigation_steps
from app.database.session import get_session, get_session_factory
from app.graph.builder import get_compiled_graph
from app.services.investigation_service import investigation_detail, investigation_summaries
from app.services.run_manager import END_KINDS, get_run_manager, step_to_dict, to_jsonable

router = APIRouter(prefix="/api", tags=["investigations"])


@router.get("/investigations")
def list_investigations_endpoint(
    status: str | None = Query(default=None),
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    return investigation_summaries(session, status=status)


@router.get("/investigations/{investigation_id}")
def get_investigation_endpoint(
    investigation_id: str,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    try:
        return investigation_detail(session, investigation_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="Investigation not found") from None


def _lookup(investigation_id: str) -> tuple[str, str] | None:
    """(status, thread_id) of the investigation, or None if it does not exist."""
    session = get_session_factory()()
    try:
        inv = get_investigation(session, investigation_id)
        return (inv.status, inv.thread_id) if inv else None
    finally:
        session.close()


def require_investigation(investigation_id: str) -> tuple[str, str]:
    """Dependency: 404 before a stream starts (an error inside a stream is too late)."""
    found = _lookup(investigation_id)
    if found is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    return found


def _steps_after(investigation_id: str, after_seq: int) -> list[dict[str, Any]] | None:
    """Stored steps with seq > after_seq, or None if the investigation does not exist."""
    session = get_session_factory()()
    try:
        if get_investigation(session, investigation_id) is None:
            return None
        return [step_to_dict(s) for s in list_investigation_steps(session, investigation_id) if s.seq > after_seq]
    finally:
        session.close()


@router.get("/investigations/{investigation_id}/steps")
def get_steps(investigation_id: str, after_seq: int = Query(default=0, ge=0)) -> list[dict[str, Any]]:
    """Every stored step of the investigation (optionally only those after a seq)."""
    steps = _steps_after(investigation_id, after_seq)
    if steps is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    return steps


def _sse(step: dict[str, Any]) -> ServerSentEvent:
    return ServerSentEvent(data=step, event=step["kind"], id=str(step["seq"]))


@router.get("/investigations/{investigation_id}/stream", response_class=EventSourceResponse)
async def stream_investigation(
    investigation_id: str,
    last_event_id: int | None = Header(default=None),
    after_seq: int = Query(default=0, ge=0),
    _: tuple[str, str] = Depends(require_investigation),
) -> AsyncIterable[ServerSentEvent]:
    """Server-Sent Events: replay the stored steps, then follow the live run.

    Each event's id is the step's seq. A reconnecting browser sends Last-Event-ID and
    gets only newer steps (`after_seq` does the same for curl). When no run is in
    progress the stream ends with an `end` event carrying the investigation status;
    after a reviewer decision, connect again to follow the resumed run.
    """
    manager = get_run_manager()
    # Subscribe BEFORE reading the stored steps, so a step stored in between is
    # still delivered (from the queue); seq removes the overlap.
    queue = manager.subscribe(investigation_id)
    try:
        last = last_event_id or after_seq
        for step in await asyncio.to_thread(_steps_after, investigation_id, last) or []:
            last = step["seq"]
            yield _sse(step)

        while manager.is_active(investigation_id) or not queue.empty():
            try:
                step = await asyncio.wait_for(queue.get(), timeout=1.0)
            except TimeoutError:
                continue
            if step["seq"] <= last:
                continue
            last = step["seq"]
            yield _sse(step)
            if step["kind"] in END_KINDS and not manager.is_active(investigation_id) and queue.empty():
                break

        found = await asyncio.to_thread(_lookup, investigation_id)
        yield ServerSentEvent(
            data={"investigation_id": investigation_id, "status": found[0] if found else None}, event="end"
        )
    finally:
        manager.unsubscribe(investigation_id, queue)


@router.get("/investigations/{investigation_id}/history")
async def get_history(found: tuple[str, str] = Depends(require_investigation)) -> list[dict[str, Any]]:
    """The graph's checkpoints for this investigation, newest first (time-travel view)."""
    graph = get_compiled_graph()
    out: list[dict[str, Any]] = []
    async for snap in graph.aget_state_history({"configurable": {"thread_id": found[1]}}):
        metadata = snap.metadata or {}
        out.append(
            {
                "checkpoint_id": snap.config["configurable"]["checkpoint_id"],
                "parent_checkpoint_id": (snap.parent_config or {}).get("configurable", {}).get("checkpoint_id"),
                "step": metadata.get("step"),
                "source": metadata.get("source"),
                "next": list(snap.next),
                "created_at": snap.created_at,
                "interrupts": [to_jsonable(i) for t in snap.tasks for i in t.interrupts],
                "values": to_jsonable(snap.values),
            }
        )
    return out

"""Run investigations as background asyncio tasks and stream their steps.

One RunManager lives for the life of the API process (created in the FastAPI
lifespan). For every run it:

1. streams the graph with `astream(stream_mode=["updates", "custom"], subgraphs=True)`,
2. turns each streamed item into a *step* and stores it in `investigation_steps`
   (so a client that connects late can replay it),
3. publishes the stored step to every live subscriber of that investigation, and a
   compact copy to subscribers of the plant-wide feed.

Steps have a per-investigation `seq` (1, 2, 3, ...). It is the SSE event id, so a
reconnecting client says where it stopped (`Last-Event-ID`) and gets only newer steps.

Step kinds:
    run_started, run_finished, run_failed   lifecycle of one run (start or resume)
    node                                    a node finished (stream_mode "updates")
    interrupt                               the graph paused for a human decision
    tool_call, tool_result                  a specialist used a tool ("custom")
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any

from langchain_core.messages import BaseMessage
from langgraph.types import Command, Interrupt

from app.database.models import InvestigationStep
from app.database.repository import add_audit_event, add_investigation_step, get_investigation, update_investigation
from app.database.session import get_session_factory
from app.graph.builder import get_compiled_graph

logger = logging.getLogger(__name__)

# A run (start or resume) has ended, so a stream with nothing else running can close.
END_KINDS = {"run_finished", "run_failed"}


def to_jsonable(value: Any) -> Any:
    """Make a streamed value safe to store as JSON and send over SSE."""
    if isinstance(value, BaseMessage):
        out: dict[str, Any] = {"type": value.type, "content": value.content}
        if getattr(value, "tool_calls", None):
            out["tool_calls"] = [{"name": c["name"], "args": c["args"]} for c in value.tool_calls]
        return out
    if isinstance(value, Interrupt):
        return {"id": value.id, "value": to_jsonable(value.value)}
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    if hasattr(value, "model_dump"):
        return to_jsonable(value.model_dump(mode="json"))
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return json.loads(json.dumps(value, default=str))


def step_to_dict(step: InvestigationStep) -> dict[str, Any]:
    return {
        "investigation_id": step.investigation_id,
        "seq": step.seq,
        "node": step.node,
        "namespace": step.namespace,
        "kind": step.kind,
        "payload": step.payload_json or {},
        "ts": step.ts.isoformat() if step.ts else None,
    }


def _node_of(namespace: tuple[str, ...]) -> str:
    """'environment_agent:1f3c...' -> 'environment_agent' (the parent-graph node)."""
    return namespace[0].split(":", 1)[0] if namespace else ""


class RunManager:
    """Starts and resumes graph runs as tasks; fans their steps out to subscribers."""

    def __init__(self, graph_getter: Callable[[], Any] = get_compiled_graph) -> None:
        self._graph_getter = graph_getter
        self._tasks: dict[str, asyncio.Task[str]] = {}
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = {}
        self._feed_subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    # -- runs ---------------------------------------------------------------

    def start(self, investigation_id: str, thread_id: str, initial_state: dict[str, Any]) -> asyncio.Task[str]:
        """Start a new run in the background and return its task at once."""
        return self._spawn(investigation_id, thread_id, initial_state, "start")

    def resume(self, investigation_id: str, thread_id: str, decision: dict[str, Any]) -> asyncio.Task[str]:
        """Resume a run paused at human_review with the reviewer's decision."""
        return self._spawn(investigation_id, thread_id, Command(resume=decision), "resume")

    def is_active(self, investigation_id: str) -> bool:
        return investigation_id in self._tasks

    @property
    def active_count(self) -> int:
        return len(self._tasks)

    def _spawn(self, investigation_id: str, thread_id: str, graph_input: Any, mode: str) -> asyncio.Task[str]:
        if investigation_id in self._tasks:
            raise ValueError(f"Investigation {investigation_id} already has a run in progress.")
        task = asyncio.create_task(
            self._run(investigation_id, thread_id, graph_input, mode), name=f"run-{investigation_id}"
        )
        self._tasks[investigation_id] = task
        return task

    async def _run(self, investigation_id: str, thread_id: str, graph_input: Any, mode: str) -> str:
        """Stream one run to the end. Returns the investigation's final status. Never raises
        (except on cancellation): a failure is recorded and published as `run_failed`."""
        config = {"configurable": {"thread_id": thread_id}}
        try:
            await self._emit(investigation_id, "", "run", "run_started", {"mode": mode})
            graph = self._graph_getter()
            async for namespace, stream_mode, chunk in graph.astream(
                graph_input, config, stream_mode=["updates", "custom"], subgraphs=True
            ):
                ns = "|".join(namespace)
                if stream_mode == "custom":
                    kind = str(chunk.get("type", "custom")) if isinstance(chunk, dict) else "custom"
                    await self._emit(investigation_id, ns, _node_of(namespace), kind, to_jsonable(chunk))
                    continue
                for node, update in chunk.items():
                    if node == "__interrupt__":
                        await self._emit(investigation_id, ns, "human_review", "interrupt", {"interrupts": to_jsonable(update)})
                    else:
                        # Inside a specialist subgraph, name the step after the inner node.
                        await self._emit(investigation_id, ns, node, "node", to_jsonable(update or {}))
            status = await asyncio.to_thread(self._status, investigation_id)
            await self._emit(investigation_id, "", "run", "run_finished", {"mode": mode, "status": status})
            return status
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("Run (%s) failed for %s", mode, investigation_id)
            action = "investigation_failed" if mode == "start" else "resume_failed"
            await asyncio.to_thread(self._mark_failed, investigation_id, action, exc)
            try:
                await self._emit(
                    investigation_id, "", "run", "run_failed", {"mode": mode, "error": f"{type(exc).__name__}: {exc}"}
                )
            except Exception:  # noqa: BLE001
                logger.exception("Could not record run_failed for %s", investigation_id)
            return "failed"
        finally:
            self._tasks.pop(investigation_id, None)

    async def shutdown(self) -> None:
        """Cancel runs still in progress (API shutdown). A cancelled run stays `processing`."""
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    # -- persistence --------------------------------------------------------

    @staticmethod
    def _store(investigation_id: str, namespace: str, node: str, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        session = get_session_factory()()
        try:
            step = add_investigation_step(
                session,
                investigation_id=investigation_id,
                node=node[:64],
                kind=kind,
                payload=payload,
                namespace=namespace[:256],
            )
            session.commit()
            return step_to_dict(step)
        finally:
            session.close()

    @staticmethod
    def _status(investigation_id: str) -> str:
        session = get_session_factory()()
        try:
            inv = get_investigation(session, investigation_id)
            return inv.status if inv else "unknown"
        finally:
            session.close()

    @staticmethod
    def _mark_failed(investigation_id: str, action: str, exc: Exception) -> None:
        session = get_session_factory()()
        try:
            inv = get_investigation(session, investigation_id)
            if inv:
                update_investigation(session, inv, status="failed")
            add_audit_event(
                session, investigation_id=investigation_id, node_name="api", action=action, details={"error": str(exc)}
            )
            session.commit()
        finally:
            session.close()

    async def _emit(self, investigation_id: str, namespace: str, node: str, kind: str, payload: Any) -> None:
        if not isinstance(payload, dict):
            payload = {"value": payload}
        # SQLAlchemy is synchronous: run it in a worker thread so the event loop
        # (and every other stream) keeps moving.
        step = await asyncio.to_thread(self._store, investigation_id, namespace, node, kind, payload)
        self._publish(step)

    # -- subscribers ----------------------------------------------------------

    def _publish(self, step: dict[str, Any]) -> None:
        for queue in self._subscribers.get(step["investigation_id"], set()):
            queue.put_nowait(step)
        if step["namespace"] == "" and self._feed_subscribers:
            item = {
                "investigation_id": step["investigation_id"],
                "seq": step["seq"],
                "node": step["node"],
                "kind": step["kind"],
                "ts": step["ts"],
            }
            if "status" in step["payload"]:
                item["status"] = step["payload"]["status"]
            for queue in self._feed_subscribers:
                queue.put_nowait(item)

    def subscribe(self, investigation_id: str) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._subscribers.setdefault(investigation_id, set()).add(queue)
        return queue

    def unsubscribe(self, investigation_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        queues = self._subscribers.get(investigation_id)
        if queues is not None:
            queues.discard(queue)
            if not queues:
                del self._subscribers[investigation_id]

    def subscribe_feed(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._feed_subscribers.add(queue)
        return queue

    def unsubscribe_feed(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._feed_subscribers.discard(queue)


_manager: RunManager | None = None


def set_run_manager(manager: RunManager | None) -> None:
    global _manager
    _manager = manager


def get_run_manager() -> RunManager:
    if _manager is None:
        raise RuntimeError("The RunManager is not running; it is created in the app lifespan.")
    return _manager

"""Compile the PaintOps LangGraph StateGraph with an async SQLite checkpointer."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph

from app.config import get_settings
from app.graph import nodes
from app.graph.routing import (
    approval_route,
    dispatch_specialists,
    route_from_state,
    validation_route,
)
from app.graph.specialists import SPECS
from app.graph.specialists.base import SpecialistInput
from app.graph.state import PaintOpsState

logger = logging.getLogger(__name__)

_compiled = None


SPECIALIST_NODES = [f"{name}_agent" for name in SPECS]


def build_graph(checkpointer: Any | None = None):
    """Build the multi-agent investigation graph, compiled with an optional checkpointer.

    intake -> triage -> plan_investigation =Send=> specialists (parallel)
        -> synthesise -> route_decision -> record_observation | draft_ticket
        -> human_review -> create_ticket | record_rejection | draft_ticket (revise)
        -> notify
    """
    graph = StateGraph(PaintOpsState)

    graph.add_node("intake", nodes.intake)
    graph.add_node("triage", nodes.triage)
    graph.add_node("plan_investigation", nodes.plan_investigation)
    for name in SPECS:
        graph.add_node(f"{name}_agent", nodes.make_specialist_node(name), input_schema=SpecialistInput)
    graph.add_node("synthesise", nodes.synthesise)
    graph.add_node("route_decision", nodes.route_decision)
    graph.add_node("draft_ticket", nodes.draft_ticket)
    graph.add_node("human_review", nodes.human_review)
    graph.add_node("create_ticket", nodes.create_ticket)
    graph.add_node("record_rejection", nodes.record_rejection)
    graph.add_node("notify", nodes.notify)
    graph.add_node("record_observation", nodes.record_observation)
    graph.add_node("record_invalid", nodes.record_invalid)

    graph.add_edge(START, "intake")
    graph.add_conditional_edges(
        "intake",
        validation_route,
        {"valid": "triage", "invalid": "record_invalid"},
    )
    graph.add_edge("triage", "plan_investigation")
    # Fan out: dispatch_specialists returns one Send per planned specialist.
    graph.add_conditional_edges("plan_investigation", dispatch_specialists, SPECIALIST_NODES)
    # Fan in: synthesise runs once, after every dispatched specialist has finished.
    for node in SPECIALIST_NODES:
        graph.add_edge(node, "synthesise")
    graph.add_edge("synthesise", "route_decision")
    graph.add_conditional_edges(
        "route_decision",
        route_from_state,
        {"monitor": "record_observation", "action_required": "draft_ticket"},
    )
    graph.add_edge("draft_ticket", "human_review")
    graph.add_conditional_edges(
        "human_review",
        approval_route,
        {
            "approved": "create_ticket",
            "rejected": "record_rejection",
            "revise": "draft_ticket",
            "revise_refused": "human_review",
        },
    )
    graph.add_edge("create_ticket", "notify")
    graph.add_edge("record_rejection", "notify")
    graph.add_edge("notify", END)
    graph.add_edge("record_observation", END)
    graph.add_edge("record_invalid", END)

    if checkpointer is not None:
        return graph.compile(checkpointer=checkpointer)
    return graph.compile()


@asynccontextmanager
async def open_graph() -> AsyncIterator[Any]:
    """Open the async checkpointer, compile the graph, and close both on exit.

    AsyncSqliteSaver holds an aiosqlite connection that belongs to the running event
    loop, so it is opened inside the FastAPI lifespan (or a script's asyncio.run),
    never at import time.
    """
    global _compiled
    path = Path(get_settings().checkpoint_db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(str(path)) as checkpointer:
        _compiled = build_graph(checkpointer=checkpointer)
        logger.info("Compiled PaintOps graph with AsyncSqliteSaver checkpointer")
        try:
            yield _compiled
        finally:
            _compiled = None


def get_compiled_graph():
    """Return the graph opened by `open_graph()`. Raises if it is not open."""
    if _compiled is None:
        raise RuntimeError("The graph is not open; it is opened by open_graph() in the app lifespan.")
    return _compiled


def reset_compiled_graph() -> None:
    """Forget the open graph (tests / reset script). `open_graph()` closes the connection."""
    global _compiled
    _compiled = None

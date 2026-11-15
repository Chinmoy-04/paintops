"""Compile the PaintOps LangGraph StateGraph with SQLite checkpointer."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from app.config import get_settings
from app.graph import nodes
from app.graph.routing import approval_route, route_from_state, validation_route
from app.graph.state import PaintOpsState

logger = logging.getLogger(__name__)

_compiled = None
_checkpointer_cm = None


def build_graph(checkpointer: Any | None = None):
    """Build and optionally compile the investigation graph."""
    graph = StateGraph(PaintOpsState)

    graph.add_node("validate_event", nodes.validate_event)
    graph.add_node("fetch_line_context", nodes.fetch_line_context)
    graph.add_node("retrieve_sop", nodes.retrieve_sop)
    graph.add_node("analyse_deviation", nodes.analyse_deviation_node)
    graph.add_node("route_decision", nodes.route_decision)
    graph.add_node("draft_ticket", nodes.draft_ticket)
    graph.add_node("human_review", nodes.human_review)
    graph.add_node("create_ticket", nodes.create_ticket)
    graph.add_node("record_rejection", nodes.record_rejection)
    graph.add_node("record_observation", nodes.record_observation)
    graph.add_node("record_invalid", nodes.record_invalid)

    graph.add_edge(START, "validate_event")
    graph.add_conditional_edges(
        "validate_event",
        validation_route,
        {
            "valid": "fetch_line_context",
            "invalid": "record_invalid",
        },
    )
    graph.add_edge("fetch_line_context", "retrieve_sop")
    graph.add_edge("retrieve_sop", "analyse_deviation")
    graph.add_edge("analyse_deviation", "route_decision")
    graph.add_conditional_edges(
        "route_decision",
        route_from_state,
        {
            "monitor": "record_observation",
            "action_required": "draft_ticket",
        },
    )
    graph.add_edge("draft_ticket", "human_review")
    graph.add_conditional_edges(
        "human_review",
        approval_route,
        {
            "approved": "create_ticket",
            "rejected": "record_rejection",
        },
    )
    graph.add_edge("record_observation", END)
    graph.add_edge("create_ticket", END)
    graph.add_edge("record_rejection", END)
    graph.add_edge("record_invalid", END)

    if checkpointer is not None:
        return graph.compile(checkpointer=checkpointer)
    return graph.compile()


def _open_checkpointer() -> SqliteSaver:
    """Open a persistent SqliteSaver for single-process MVP."""
    global _checkpointer_cm
    settings = get_settings()
    path = Path(settings.checkpoint_db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # SqliteSaver.from_conn_string returns a context manager in recent versions.
    cm = SqliteSaver.from_conn_string(str(path))
    _checkpointer_cm = cm
    saver = cm.__enter__()
    return saver


def get_compiled_graph(force_reload: bool = False):
    """Return a singleton compiled graph with persistent checkpointer."""
    global _compiled
    if _compiled is not None and not force_reload:
        return _compiled
    checkpointer = _open_checkpointer()
    _compiled = build_graph(checkpointer=checkpointer)
    logger.info("Compiled PaintOps graph with SqliteSaver checkpointer")
    return _compiled


def reset_compiled_graph() -> None:
    """Drop cached graph (tests / reset)."""
    global _compiled, _checkpointer_cm
    if _checkpointer_cm is not None:
        try:
            _checkpointer_cm.__exit__(None, None, None)
        except Exception:  # noqa: BLE001
            pass
    _checkpointer_cm = None
    _compiled = None

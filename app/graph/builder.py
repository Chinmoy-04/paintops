"""Compile the PaintOps LangGraph StateGraph with SQLite checkpointer."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver
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
_checkpointer_cm = None


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

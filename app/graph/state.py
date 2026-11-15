"""LangGraph state definition for the PaintOps parent graph."""

import operator
from typing import Annotated, Any, Literal, TypedDict


class PaintOpsState(TypedDict, total=False):
    """Shared graph state. Raw data lives here; prompts are built inside nodes.

    Most keys are plain: a node's return value overwrites them. `findings` has a
    reducer (operator.add), so the specialists running in parallel each append
    their Finding instead of overwriting each other's.
    """

    event: dict[str, Any]
    investigation_id: str
    thread_id: str

    recent_events: list[dict[str, Any]]
    recurrence_count: int

    specialists_planned: list[str]
    findings: Annotated[list[dict[str, Any]], operator.add]

    sop_results: list[dict[str, Any]]
    analysis: dict[str, Any]
    severity: Literal["low", "medium", "high", "critical"]
    route: Literal["monitor", "action_required"]

    ticket_draft: dict[str, Any]
    approval_decision: dict[str, Any]
    approval_status: Literal["approved", "rejected", "revise", "revise_refused"]
    reviewer: str
    review_comment: str
    revision_notes: list[str]
    revision_count: int
    ticket_id: str
    notification: dict[str, Any]

    errors: list[str]

"""LangGraph state definition for PaintOps."""

from typing import Any, Literal, TypedDict


class PaintOpsState(TypedDict, total=False):
    """Shared graph state. Raw data lives here; prompts are built inside nodes."""

    event: dict[str, Any]
    investigation_id: str
    thread_id: str

    recent_events: list[dict[str, Any]]
    recurrence_count: int

    sop_results: list[dict[str, Any]]
    analysis: dict[str, Any]
    severity: Literal["low", "medium", "high", "critical"]
    route: Literal["monitor", "action_required"]

    ticket_draft: dict[str, Any]
    approval_decision: dict[str, Any]
    approval_status: Literal["approved", "rejected"]
    reviewer: str
    review_comment: str
    ticket_id: str

    errors: list[str]

"""Deterministic routing policy — LLM cannot override these rules."""

from __future__ import annotations

from typing import Any, Literal

from langgraph.types import Send

from app.config import get_settings

Route = Literal["monitor", "action_required"]


def decide_route(
    *,
    recurrence_count: int,
    severity: str,
    high_severity_action_required: bool | None = None,
    action_threshold: int | None = None,
) -> Route:
    """
    Apply synthetic demo routing thresholds.

    action_required if recurrence >= threshold OR severity in {high, critical}
    (when high_severity_action_required is enabled). Otherwise monitor.
    """
    settings = get_settings()
    threshold = (
        action_threshold
        if action_threshold is not None
        else settings.recurrence_action_threshold
    )
    high_sev = (
        high_severity_action_required
        if high_severity_action_required is not None
        else settings.high_severity_action_required
    )

    if recurrence_count >= threshold:
        return "action_required"
    if high_sev and severity in {"high", "critical"}:
        return "action_required"
    return "monitor"


def route_from_state(state: dict[str, Any]) -> Route:
    """Conditional edge helper reading graph state."""
    return decide_route(
        recurrence_count=int(state.get("recurrence_count") or 0),
        severity=str(state.get("severity") or "low"),
    )


# A reviewer can send a draft back for revision at most this many times; after
# that only approve or reject is accepted.
MAX_REVISIONS = 2

ApprovalRoute = Literal["approved", "rejected", "revise", "revise_refused"]


def approval_route(state: dict[str, Any]) -> ApprovalRoute:
    """Route after the human review interrupt. Anything unrecognised is a rejection."""
    status = state.get("approval_status")
    if status in {"approved", "revise", "revise_refused"}:
        return status  # type: ignore[return-value]
    return "rejected"


def dispatch_specialists(state: dict[str, Any]) -> list[Send]:
    """Fan out: one Send per planned specialist. They run in parallel in one step."""
    payload = {
        "event": state.get("event") or {},
        "investigation_id": state.get("investigation_id"),
        "recurrence_count": int(state.get("recurrence_count") or 0),
    }
    return [Send(f"{name}_agent", payload) for name in state.get("specialists_planned") or []]


def validation_route(state: dict[str, Any]) -> Literal["valid", "invalid"]:
    """Route after validate_event: any recorded error ends the run."""
    return "invalid" if state.get("errors") else "valid"

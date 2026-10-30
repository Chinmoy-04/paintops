"""Deterministic routing policy tests."""

from app.graph.routing import decide_route


def test_monitor_for_low_recurrence_low_severity() -> None:
    assert decide_route(recurrence_count=1, severity="low") == "monitor"
    assert decide_route(recurrence_count=2, severity="medium") == "monitor"


def test_action_required_on_recurrence_threshold() -> None:
    assert decide_route(recurrence_count=3, severity="low") == "action_required"
    assert decide_route(recurrence_count=5, severity="medium") == "action_required"


def test_action_required_on_high_severity() -> None:
    assert decide_route(recurrence_count=1, severity="high") == "action_required"
    assert decide_route(recurrence_count=1, severity="critical") == "action_required"


def test_high_severity_flag_can_be_disabled() -> None:
    assert (
        decide_route(
            recurrence_count=1,
            severity="high",
            high_severity_action_required=False,
        )
        == "monitor"
    )

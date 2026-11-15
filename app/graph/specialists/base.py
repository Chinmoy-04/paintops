"""Shared builder for specialist agent subgraphs.

Every specialist is its own compiled StateGraph with private state:

    START -> agent -> (tool calls?) -> tools -> agent -> ... -> report -> END

- `agent` asks the chat model what to do next. It has a RetryPolicy, so a flaky
  model call is retried before the specialist gives up.
- `tools` runs the tool calls the model asked for and feeds the results back.
- `report` turns what the tools returned into one Finding.
- The loop is capped at MAX_TOOL_ROUNDS model turns.

The parent graph never sees `messages` or `tool_log`; it only receives the Finding.
"""

from __future__ import annotations

import json
import operator
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import RetryPolicy, default_retry_on

from app.schemas.finding import Finding, SpecialistName, ToolCallRecord
from app.services.llm import get_chat_model, provider_name

MAX_TOOL_ROUNDS = 4


def _retry_model_errors(exc: Exception) -> bool:
    # LangGraph's default skips every OSError, which includes the built-in
    # TimeoutError. A timed-out model call is worth retrying, so add it back.
    return isinstance(exc, TimeoutError) or default_retry_on(exc)


AGENT_RETRY = RetryPolicy(
    max_attempts=3,
    initial_interval=0.1,
    max_interval=1.0,
    jitter=False,
    retry_on=_retry_model_errors,
)


class SpecialistInput(TypedDict, total=False):
    """What the parent sends to a specialist (via Send)."""

    event: dict[str, Any]
    investigation_id: str
    recurrence_count: int


class SpecialistState(SpecialistInput, total=False):
    """Private working state of one specialist run."""

    messages: Annotated[list[AnyMessage], add_messages]
    tool_log: Annotated[list[dict[str, Any]], operator.add]
    rounds: int
    finding: dict[str, Any]


@dataclass(frozen=True)
class Assessment:
    """A specialist's judgement of its tool results, before it becomes a Finding."""

    hypothesis: str
    confidence: float
    evidence: list[str]
    sop_references: list[dict[str, Any]] | None = None


@dataclass(frozen=True)
class SpecialistSpec:
    name: SpecialistName
    system_prompt: str
    # Tools bound to this event (booth and time are fixed; the model picks the rest).
    make_tools: Callable[[dict[str, Any]], list[BaseTool]]
    # DEMO_MODE only: the tool calls the scripted model will make for this event.
    demo_script: Callable[[dict[str, Any]], list[dict[str, Any]]]
    # Turns the tool results into a hypothesis. Deterministic rules over real data.
    assess: Callable[[dict[str, Any], dict[str, Any]], Assessment]


def not_run(results: dict[str, Any], *tool_names: str) -> list[str]:
    """Tools the agent never called. "Not checked" must never read as "nothing found"."""
    return [name for name in tool_names if name not in results]


def _brief(event: dict[str, Any], recurrence_count: int) -> str:
    return (
        "Investigate this SYNTHETIC paint inspection event. Use your tools, then stop.\n"
        f"Event: {json.dumps(event, default=str)}\n"
        f"Same-booth, same-defect events in the recurrence window: {recurrence_count}"
    )


def build_specialist_graph(spec: SpecialistSpec):
    """Compile the agent -> tools -> report loop for one specialist."""

    def agent(state: SpecialistState) -> dict[str, Any]:
        event = state["event"]
        history = list(state.get("messages") or [])
        new: list[AnyMessage] = []
        if not history:
            new = [
                SystemMessage(content=spec.system_prompt),
                HumanMessage(content=_brief(event, int(state.get("recurrence_count") or 0))),
            ]
        model = get_chat_model(demo_script=spec.demo_script(event)).bind_tools(spec.make_tools(event))
        response = model.invoke(history + new)
        return {"messages": [*new, response], "rounds": int(state.get("rounds") or 0) + 1}

    def tools(state: SpecialistState) -> dict[str, Any]:
        by_name = {t.name: t for t in spec.make_tools(state["event"])}
        last = state["messages"][-1]
        replies: list[ToolMessage] = []
        log: list[dict[str, Any]] = []
        for call in last.tool_calls:
            tool = by_name.get(call["name"])
            if tool is None:
                result: Any = {"error": f"Unknown tool {call['name']}"}
            else:
                result = tool.invoke(call["args"])
            log.append({"name": call["name"], "args": call["args"], "result": result})
            replies.append(
                ToolMessage(content=json.dumps(result, default=str), tool_call_id=call["id"], name=call["name"])
            )
        return {"messages": replies, "tool_log": log}

    def after_agent(state: SpecialistState) -> Literal["tools", "report"]:
        last = state["messages"][-1]
        if getattr(last, "tool_calls", None) and int(state.get("rounds") or 0) < MAX_TOOL_ROUNDS:
            return "tools"
        return "report"

    def report(state: SpecialistState) -> dict[str, Any]:
        log = state.get("tool_log") or []
        latest: dict[str, Any] = {}
        for entry in log:
            latest[entry["name"]] = entry["result"]
        assessment = spec.assess(state["event"], latest)
        finding = Finding(
            specialist=spec.name,
            hypothesis=assessment.hypothesis,
            confidence=round(max(0.0, min(1.0, assessment.confidence)), 2),
            evidence=assessment.evidence,
            sop_references=assessment.sop_references or [],
            tool_calls=[ToolCallRecord(**entry) for entry in log],
            provider=provider_name(),
        )
        return {"finding": finding.model_dump(mode="json")}

    graph = StateGraph(SpecialistState, input_schema=SpecialistInput)
    graph.add_node("agent", agent, retry_policy=AGENT_RETRY)
    graph.add_node("tools", tools)
    graph.add_node("report", report)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", after_agent, {"tools": "tools", "report": "report"})
    graph.add_edge("tools", "agent")
    graph.add_edge("report", END)
    return graph.compile(name=f"{spec.name}_specialist")

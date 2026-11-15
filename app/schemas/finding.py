"""What a specialist agent hands back to the parent graph."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

SpecialistName = Literal["environment", "equipment", "process"]


class ToolCallRecord(BaseModel):
    """One tool call a specialist made, kept for the audit trail and the UI."""

    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    result: Any = None


class Finding(BaseModel):
    """
    One specialist's conclusion. Hypotheses only — never a confirmed root cause.

    status="failed" means the specialist could not finish; the hypothesis then says
    why, confidence is 0, and nothing is invented to fill the gap.
    """

    specialist: SpecialistName
    status: Literal["ok", "failed"] = "ok"
    hypothesis: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)
    sop_references: list[dict[str, Any]] = Field(default_factory=list)
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    provider: str = "demo_scripted"
    error: str | None = None

    @classmethod
    def failed(cls, specialist: SpecialistName, error: str, provider: str = "") -> Finding:
        return cls(
            specialist=specialist,
            status="failed",
            hypothesis=f"{specialist} specialist could not complete its checks.",
            confidence=0.0,
            evidence=[],
            provider=provider or "unknown",
            error=error,
        )

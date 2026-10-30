"""Structured analysis output schemas."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class AnalysisResult(BaseModel):
    """Validated analysis produced by the LLM or demo adapter."""

    suspected_cause: str
    evidence: list[str] = Field(default_factory=list)
    uncertainty: str = ""
    severity: Literal["low", "medium", "high", "critical"]
    sop_references: list[dict[str, Any]] = Field(default_factory=list)
    no_relevant_sop_found: bool = False
    analysis_provider: str = "demo_rules"
    rationale: str = ""

"""Human approval decision schemas."""

from typing import Literal

from pydantic import BaseModel, Field


class DecisionRequest(BaseModel):
    """Reviewer decision payload for resuming a paused investigation."""

    decision: Literal["approved", "rejected"]
    reviewer: str = Field(..., min_length=1, max_length=128)
    comment: str | None = None


class DecisionResponse(BaseModel):
    """Outcome after resuming the graph with a decision."""

    investigation_id: str
    status: str
    ticket_id: str | None = None
    message: str

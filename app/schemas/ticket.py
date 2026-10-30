"""Ticket draft and read schemas."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class TicketDraft(BaseModel):
    """Structured action-ticket draft awaiting human approval."""

    ticket_type: Literal["quality_inspection", "maintenance_inspection"] = (
        "quality_inspection"
    )
    priority: Literal["low", "medium", "high", "critical"]
    title: str
    description: str
    sop_references: list[dict[str, Any]] = Field(default_factory=list)
    requires_manual_sop_verification: bool = False


class TicketRead(BaseModel):
    """Persisted action ticket."""

    ticket_id: str
    investigation_id: str
    event_id: str
    ticket_type: str
    priority: str
    title: str
    description: str
    sop_references: list[dict[str, Any]] = Field(default_factory=list)
    status: str
    approved_by: str
    approved_at: datetime
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

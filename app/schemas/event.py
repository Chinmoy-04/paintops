"""Inspection event schemas."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

DefectType = Literal[
    "orange_peel",
    "runs_sags",
    "dust_inclusion",
    "uneven_coverage",
    "fisheye_craters",
    "color_mismatch",
]

DEFECT_TYPES: tuple[str, ...] = (
    "orange_peel",
    "runs_sags",
    "dust_inclusion",
    "uneven_coverage",
    "fisheye_craters",
    "color_mismatch",
)


class TelemetryPayload(BaseModel):
    """Synthetic booth environment readings."""

    booth_temperature_c: float | None = None
    humidity_pct: float | None = None
    airflow_m_s: float | None = None

    model_config = ConfigDict(extra="allow")


class InspectionEventCreate(BaseModel):
    """Inbound synthetic paint-quality inspection event."""

    event_id: str = Field(..., min_length=1, max_length=128)
    timestamp: datetime
    plant_id: str = Field(..., min_length=1, max_length=64)
    production_line: str = Field(..., min_length=1, max_length=64)
    booth_id: str = Field(..., min_length=1, max_length=64)
    body_id: str = Field(..., min_length=1, max_length=64)
    defect_type: DefectType
    model_confidence: float = Field(..., ge=0.0, le=1.0)
    telemetry: TelemetryPayload | dict[str, Any] = Field(default_factory=dict)
    source: str = "synthetic_cv_inspection"

    @field_validator("timestamp")
    @classmethod
    def ensure_timezone_aware_or_naive_utc(cls, value: datetime) -> datetime:
        """Accept aware or naive datetimes; store as provided (UTC convention)."""
        return value


class InspectionEventRead(BaseModel):
    """Persisted inspection event summary."""

    event_id: str
    timestamp: datetime
    plant_id: str
    production_line: str
    booth_id: str
    body_id: str
    defect_type: str
    model_confidence: float
    telemetry: dict[str, Any]
    source: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


def event_timestamp(event: dict[str, Any]) -> datetime:
    """Event time as naive UTC (the storage convention), from a dict or model dump."""
    raw = event.get("timestamp")
    if isinstance(raw, datetime):
        return raw.replace(tzinfo=None) if raw.tzinfo else raw
    if isinstance(raw, str):
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
    raise ValueError(f"Event has no usable timestamp: {raw!r}")

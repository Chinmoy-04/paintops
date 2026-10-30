"""SQL tool: recent booth/defect history."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.database.repository import fetch_recent_events


def get_recent_booth_defects(
    session: Session,
    *,
    booth_id: str,
    defect_type: str,
    as_of: datetime,
    window_minutes: int | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """
    Query recent matching inspection events.

    Returns (event dicts, recurrence_count including current window matches).
    """
    settings = get_settings()
    minutes = window_minutes or settings.recurrence_window_minutes
    rows = fetch_recent_events(
        session,
        booth_id=booth_id,
        defect_type=defect_type,
        as_of=as_of,
        window_minutes=minutes,
    )
    events = [
        {
            "event_id": r.event_id,
            "timestamp": r.timestamp.isoformat(),
            "booth_id": r.booth_id,
            "defect_type": r.defect_type,
            "model_confidence": r.model_confidence,
            "body_id": r.body_id,
        }
        for r in rows
    ]
    return events, len(events)

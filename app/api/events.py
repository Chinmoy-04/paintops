"""POST /api/events"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database.session import get_session
from app.schemas.event import InspectionEventCreate
from app.services.investigation_service import start_investigation

router = APIRouter(prefix="/api", tags=["events"])


class EventAcceptedResponse(BaseModel):
    event_id: str
    investigation_id: str
    thread_id: str
    status: str
    message: str


@router.post("/events", response_model=EventAcceptedResponse)
def post_event(
    payload: InspectionEventCreate,
    response: Response,
    session: Session = Depends(get_session),
) -> Any:
    """Accept a synthetic inspection event and start investigation workflow.

    Returns 202 for a newly accepted workflow run, 200 for an idempotent replay
    of an existing event_id.
    """
    result = start_investigation(session, payload)
    response.status_code = (
        status.HTTP_202_ACCEPTED if result.get("created") else status.HTTP_200_OK
    )
    return EventAcceptedResponse(
        event_id=result["event_id"],
        investigation_id=result["investigation_id"],
        thread_id=result["thread_id"],
        status=result["status"],
        message=result["message"],
    )

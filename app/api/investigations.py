"""Investigation list/detail endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database.session import get_session
from app.services.investigation_service import investigation_detail, investigation_summaries

router = APIRouter(prefix="/api", tags=["investigations"])


@router.get("/investigations")
def list_investigations_endpoint(
    status: str | None = Query(default=None),
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    return investigation_summaries(session, status=status)


@router.get("/investigations/{investigation_id}")
def get_investigation_endpoint(
    investigation_id: str,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    try:
        return investigation_detail(session, investigation_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="Investigation not found") from None

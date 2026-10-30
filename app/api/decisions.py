"""POST /api/investigations/{id}/decision"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database.session import get_session
from app.schemas.decision import DecisionRequest, DecisionResponse
from app.services.investigation_service import apply_decision

router = APIRouter(prefix="/api", tags=["decisions"])


@router.post(
    "/investigations/{investigation_id}/decision",
    response_model=DecisionResponse,
)
def post_decision(
    investigation_id: str,
    payload: DecisionRequest,
    session: Session = Depends(get_session),
) -> DecisionResponse:
    try:
        return apply_decision(session, investigation_id, payload)
    except LookupError:
        raise HTTPException(status_code=404, detail="Investigation not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None

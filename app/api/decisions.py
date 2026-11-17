"""POST /api/investigations/{id}/decision"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database.session import get_session
from app.schemas.decision import DecisionRequest, DecisionResponse
from app.services.investigation_service import apply_decision
from app.services.run_manager import get_run_manager

router = APIRouter(prefix="/api", tags=["decisions"])


@router.post(
    "/investigations/{investigation_id}/decision",
    response_model=DecisionResponse,
)
async def post_decision(
    investigation_id: str,
    payload: DecisionRequest,
    session: Session = Depends(get_session),
) -> DecisionResponse:
    """Approve, reject, or send back for revision (at most 2 revisions).

    Waits for the resumed run to finish; its steps also stream to subscribers.
    """
    try:
        return await apply_decision(session, investigation_id, payload, get_run_manager())
    except LookupError:
        raise HTTPException(status_code=404, detail="Investigation not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from None

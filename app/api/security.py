"""Shared-secret check for ingest and n8n-facing routes."""

from __future__ import annotations

import secrets

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

from app.config import get_settings

_header = APIKeyHeader(name="X-PaintOps-Key", auto_error=False)


def require_api_key(key: str | None = Security(_header)) -> None:
    """Reject the request with 401 unless X-PaintOps-Key matches PAINTOPS_API_KEY."""
    expected = get_settings().paintops_api_key
    if not key or not secrets.compare_digest(key.encode(), expected.encode()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid X-PaintOps-Key header.",
        )

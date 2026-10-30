"""Shared pytest fixtures."""

from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

# Force demo mode and isolated test DB before app imports mutate settings.
TEST_DB = Path(__file__).resolve().parent / "_test_paintops.db"
os.environ["DEMO_MODE"] = "true"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
os.environ["CHECKPOINT_DB_PATH"] = str(
    Path(__file__).resolve().parent / "_test_checkpoints.db"
)

from app.config import get_settings
from app.database.session import Base, get_engine, get_session_factory, init_db, reset_engine


@pytest.fixture(autouse=True)
def _fresh_db() -> Generator[None, None, None]:
    """Reset settings cache and recreate a clean SQLite schema per test."""
    get_settings.cache_clear()
    reset_engine()
    if TEST_DB.exists():
        TEST_DB.unlink()
    init_db()
    yield
    reset_engine()
    if TEST_DB.exists():
        TEST_DB.unlink()
    cp = Path(os.environ["CHECKPOINT_DB_PATH"])
    if cp.exists():
        cp.unlink()


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@pytest.fixture
def sample_event_payload() -> dict:
    return {
        "event_id": "QC-TEST-00001",
        "timestamp": "2026-10-30T09:15:00Z",
        "plant_id": "PLANT-01",
        "production_line": "PAINT-LINE-02",
        "booth_id": "BOOTH-03",
        "body_id": "CAR-008721",
        "defect_type": "orange_peel",
        "model_confidence": 0.94,
        "telemetry": {
            "booth_temperature_c": 24.5,
            "humidity_pct": 72.0,
            "airflow_m_s": 1.8,
        },
        "source": "synthetic_cv_inspection",
    }

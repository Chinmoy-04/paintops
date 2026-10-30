"""Database persistence and deduplication tests."""

from datetime import datetime, timedelta

from sqlalchemy import select

from app.database.models import InspectionEvent
from app.database.repository import (
    create_inspection_event,
    fetch_recent_events,
    get_event,
)
from app.schemas.event import InspectionEventCreate


def test_valid_event_stored_once(db_session, sample_event_payload: dict) -> None:
    payload = InspectionEventCreate.model_validate(sample_event_payload)
    event, created = create_inspection_event(db_session, payload)
    db_session.commit()
    assert created is True
    assert get_event(db_session, event.event_id) is not None

    event2, created2 = create_inspection_event(db_session, payload)
    db_session.commit()
    assert created2 is False
    assert event2.event_id == event.event_id

    rows = db_session.scalars(select(InspectionEvent)).all()
    assert len(rows) == 1


def test_duplicate_event_id_does_not_create_second_row(
    db_session, sample_event_payload: dict
) -> None:
    payload = InspectionEventCreate.model_validate(sample_event_payload)
    create_inspection_event(db_session, payload)
    db_session.commit()

    # Mutate unrelated fields — still same event_id.
    sample_event_payload["body_id"] = "CAR-OTHER"
    payload2 = InspectionEventCreate.model_validate(sample_event_payload)
    existing, created = create_inspection_event(db_session, payload2)
    db_session.commit()
    assert created is False
    assert existing.body_id == "CAR-008721"


def test_fetch_recent_events_respects_booth_defect_window(
    db_session, sample_event_payload: dict
) -> None:
    base = datetime(2026, 10, 30, 9, 15, 0)
    events = [
        {**sample_event_payload, "event_id": "E1", "timestamp": base.isoformat() + "Z"},
        {
            **sample_event_payload,
            "event_id": "E2",
            "timestamp": (base - timedelta(minutes=30)).isoformat() + "Z",
        },
        {
            **sample_event_payload,
            "event_id": "E3",
            "timestamp": (base - timedelta(minutes=90)).isoformat() + "Z",
        },
        {
            **sample_event_payload,
            "event_id": "E4",
            "booth_id": "BOOTH-99",
            "timestamp": (base - timedelta(minutes=10)).isoformat() + "Z",
        },
        {
            **sample_event_payload,
            "event_id": "E5",
            "defect_type": "runs_sags",
            "timestamp": (base - timedelta(minutes=10)).isoformat() + "Z",
        },
    ]
    for raw in events:
        create_inspection_event(db_session, InspectionEventCreate.model_validate(raw))
    db_session.commit()

    recent = fetch_recent_events(
        db_session,
        booth_id="BOOTH-03",
        defect_type="orange_peel",
        as_of=base,
        window_minutes=60,
    )
    ids = {e.event_id for e in recent}
    assert ids == {"E1", "E2"}

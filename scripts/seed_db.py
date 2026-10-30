"""Seed the business SQLite database with synthetic inspection events."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import get_settings
from app.database.repository import create_inspection_event
from app.database.session import get_session_factory, init_db, reset_engine
from app.schemas.event import InspectionEventCreate


def load_events(path: Path) -> list[InspectionEventCreate]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [InspectionEventCreate.model_validate(item) for item in raw]


def main() -> None:
    settings = get_settings()
    events_path = ROOT / "data" / "synthetic_events.json"
    reset_engine()
    init_db()
    session = get_session_factory()()
    created = 0
    skipped = 0
    try:
        for payload in load_events(events_path):
            _, was_created = create_inspection_event(session, payload)
            if was_created:
                created += 1
            else:
                skipped += 1
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    print(
        f"Seed complete. created={created} skipped={skipped} "
        f"db={settings.database_url}"
    )


if __name__ == "__main__":
    main()

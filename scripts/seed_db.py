"""Seed the business database with the synthetic plant (booths, telemetry,
maintenance, material batches, and inspection events).

SYNTHETIC DEMO DATA ONLY. Safe to re-run: existing rows are kept.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import get_settings
from app.database.seed import seed_plant
from app.database.session import get_session_factory, init_db, reset_engine


def main() -> None:
    settings = get_settings()
    reset_engine()
    init_db()
    session = get_session_factory()()
    try:
        counts = seed_plant(session)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    summary = " ".join(f"{k}={v}" for k, v in counts.items())
    print(f"Seed complete. {summary} db={settings.database_url}")


if __name__ == "__main__":
    main()

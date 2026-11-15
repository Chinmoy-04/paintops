"""Submit one synthetic example event through the investigation service."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database.session import get_session_factory, init_db
from app.schemas.event import InspectionEventCreate
from app.services.investigation_service import start_investigation


def main() -> None:
    init_db()
    payload = InspectionEventCreate.model_validate(
        {
            "event_id": "QC-EXAMPLE-001",
            "timestamp": "2026-10-30T09:15:00Z",
            "plant_id": "PLANT-01",
            "production_line": "PAINT-LINE-01",
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
    )
    session = get_session_factory()()
    try:
        result = start_investigation(session, payload)
        session.commit()
    finally:
        session.close()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

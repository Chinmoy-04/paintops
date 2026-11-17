"""Named demo scenarios: each one creates a new inspection event that matches a
pattern planted in the synthetic plant (see app/database/seed.py).

SYNTHETIC DEMO ONLY. A scenario event is timed 5 minutes before the end of the seeded
data window, so the specialists see the planted telemetry, maintenance, and batch data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.models import Booth, new_uuid
from app.database.repository import fetch_telemetry
from app.database.seed import PLANT_ID, WINDOW_END, booth_line, seed_plant
from app.schemas.event import InspectionEventCreate


@dataclass(frozen=True)
class Scenario:
    booth_id: str
    defect_type: str
    model_confidence: float
    description: str


SCENARIOS: dict[str, Scenario] = {
    "booth03_orange_peel": Scenario(
        "BOOTH-03", "orange_peel", 0.94,
        "Clearcoat booth with rising humidity, falling airflow and overdue nozzle cleaning; "
        "recurring orange peel. Expected: action required, waits for review.",
    ),
    "line02_fisheye": Scenario(
        "BOOTH-05", "fisheye_craters", 0.92,
        "Basecoat booth after a new low-viscosity batch; fisheye craters cluster. "
        "Expected: action required, waits for review.",
    ),
    "booth07_dust": Scenario(
        "BOOTH-07", "dust_inclusion", 0.9,
        "Primer booth with an overdue filter and climbing differential pressure; dust inclusions.",
    ),
    "booth08_minor": Scenario(
        "BOOTH-08", "runs_sags", 0.65,
        "A single low-confidence defect on a healthy booth. Expected: monitor only, no ticket.",
    ),
}

SCENARIO_LEAD = timedelta(minutes=5)


def build_scenario_event(session: Session, name: str) -> InspectionEventCreate:
    """Seed the plant if it is empty, then build a fresh event for the scenario.

    Raises KeyError for an unknown scenario name.
    """
    scenario = SCENARIOS[name]
    if not session.scalar(select(func.count()).select_from(Booth)):
        seed_plant(session)
        session.commit()

    ts = WINDOW_END - SCENARIO_LEAD
    readings = fetch_telemetry(session, booth_id=scenario.booth_id, start=ts - timedelta(hours=1), end=ts)
    telemetry: dict[str, Any] = {}
    if readings:
        last = readings[-1]
        telemetry = {
            "booth_temperature_c": last.temperature_c,
            "humidity_pct": last.humidity_pct,
            "airflow_m_s": last.airflow_m_s,
        }
    return InspectionEventCreate(
        event_id=f"QC-SCN-{new_uuid()[:8].upper()}",
        timestamp=ts,
        plant_id=PLANT_ID,
        production_line=booth_line(scenario.booth_id),
        booth_id=scenario.booth_id,
        body_id=f"CAR-SCN-{new_uuid()[:6].upper()}",
        defect_type=scenario.defect_type,  # type: ignore[arg-type]
        model_confidence=scenario.model_confidence,
        telemetry=telemetry,
        source=f"scenario:{name}",
    )

"""Deterministic synthetic plant data: booths, telemetry, maintenance, batches, events.

SYNTHETIC DEMO DATA ONLY. Values are invented for a portfolio demo and are not
real paint-shop limits or measurements.

Layout: 1 plant, 3 lines x 3 booths (primer -> base -> clear on each line).

Planted patterns the specialist agents should be able to find:
- BOOTH-03 (clearcoat, LINE-01): humidity drifts up and airflow drops over the last
  6 h, nozzle cleaning is overdue, and orange_peel defects cluster in the last 2 h.
- LINE-02 (BOOTH-04..06): a new basecoat batch with low viscosity starts 6 h before
  the end of the window; fisheye_craters cluster on BOOTH-05 after it.
- BOOTH-07 (primer, LINE-03): filter differential pressure climbs (filter overdue),
  dust_inclusion defects follow.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.models import Booth, MaintenanceLog, MaterialBatch, TelemetryReading
from app.database.repository import create_inspection_event
from app.schemas.event import InspectionEventCreate

PLANT_ID = "PLANT-01"
LINES: dict[str, list[str]] = {
    "PAINT-LINE-01": ["BOOTH-01", "BOOTH-02", "BOOTH-03"],
    "PAINT-LINE-02": ["BOOTH-04", "BOOTH-05", "BOOTH-06"],
    "PAINT-LINE-03": ["BOOTH-07", "BOOTH-08", "BOOTH-09"],
}
BOOTH_TYPES = ("primer", "base", "clear")

# End of the synthetic data window. Demo scenarios are timed relative to this.
WINDOW_END = datetime(2026, 10, 30, 12, 0, 0)
WINDOW_HOURS = 48
TELEMETRY_STEP_MIN = 15
SEED = 42


def booth_line(booth_id: str) -> str:
    """Return the production line a booth belongs to."""
    for line, booths in LINES.items():
        if booth_id in booths:
            return line
    raise KeyError(booth_id)


def all_booths() -> list[tuple[str, str, str]]:
    """(booth_id, line, booth_type) for every booth in the synthetic plant."""
    return [
        (booth, line, BOOTH_TYPES[i])
        for line, booths in LINES.items()
        for i, booth in enumerate(booths)
    ]


@dataclass
class _Reading:
    booth_id: str
    ts: datetime
    temperature_c: float
    humidity_pct: float
    airflow_m_s: float
    filter_dp_pa: float


def _ramp(ts: datetime, start: datetime, end: datetime) -> float:
    """0 before start, 1 after end, linear in between."""
    if ts <= start:
        return 0.0
    if ts >= end:
        return 1.0
    return (ts - start) / (end - start)


def generate_telemetry(rng: random.Random) -> list[_Reading]:
    """48 h of 15-minute readings per booth, with the planted drifts."""
    readings: list[_Reading] = []
    start = WINDOW_END - timedelta(hours=WINDOW_HOURS)
    steps = WINDOW_HOURS * 60 // TELEMETRY_STEP_MIN
    drift_start = WINDOW_END - timedelta(hours=6)
    for booth_id, _line, _type in all_booths():
        for i in range(steps + 1):
            ts = start + timedelta(minutes=i * TELEMETRY_STEP_MIN)
            temp = 23.0 + rng.gauss(0, 0.4)
            humidity = 50.0 + rng.gauss(0, 2.5)
            airflow = 2.1 + rng.gauss(0, 0.06)
            filter_dp = 120.0 + 10.0 * (i / steps) + rng.gauss(0, 3)

            if booth_id == "BOOTH-03":
                k = _ramp(ts, drift_start, WINDOW_END - timedelta(hours=1))
                humidity += 22.0 * k
                airflow -= 0.3 * k
                temp += 1.5 * k
            if booth_id == "BOOTH-07":
                filter_dp += 140.0 * _ramp(ts, start + timedelta(hours=12), WINDOW_END)

            readings.append(
                _Reading(
                    booth_id=booth_id,
                    ts=ts,
                    temperature_c=round(temp, 2),
                    humidity_pct=round(humidity, 1),
                    airflow_m_s=round(airflow, 2),
                    filter_dp_pa=round(filter_dp, 1),
                )
            )
    return readings


def generate_maintenance() -> list[dict[str, Any]]:
    """Maintenance history; BOOTH-03 nozzle and BOOTH-07 filter are overdue."""
    logs: list[dict[str, Any]] = []
    techs = ["tech_ana", "tech_ben", "tech_chen", "tech_dev"]
    for n, (booth_id, _line, _type) in enumerate(all_booths()):
        nozzle_days = 12 if booth_id == "BOOTH-03" else 2 + n % 3
        filter_days = 30 if booth_id == "BOOTH-07" else 6 + n % 4
        logs.append(
            {
                "booth_id": booth_id,
                "ts": WINDOW_END - timedelta(days=nozzle_days, hours=n),
                "component": "spray_nozzle",
                "action": "cleaned",
                "technician": techs[n % len(techs)],
                "notes": "Routine nozzle clean (synthetic).",
            }
        )
        logs.append(
            {
                "booth_id": booth_id,
                "ts": WINDOW_END - timedelta(days=filter_days, hours=2 * n),
                "component": "exhaust_filter",
                "action": "replaced",
                "technician": techs[(n + 1) % len(techs)],
                "notes": "Filter set replaced (synthetic).",
            }
        )
        logs.append(
            {
                "booth_id": booth_id,
                "ts": WINDOW_END - timedelta(days=20 + n),
                "component": "booth_hvac",
                "action": "calibrated",
                "technician": techs[(n + 2) % len(techs)],
                "notes": "Temperature and humidity sensors calibrated (synthetic).",
            }
        )
    return logs


def generate_batches() -> list[dict[str, Any]]:
    """One older batch per booth, plus the new low-viscosity basecoat on LINE-02."""
    material_by_type = {
        "primer": "PR-GREY-210",
        "base": "BC-SILVER-455",
        "clear": "CC-2K-HS-900",
    }
    batches: list[dict[str, Any]] = []
    for n, (booth_id, line, booth_type) in enumerate(all_booths()):
        batches.append(
            {
                "batch_id": f"{material_by_type[booth_type]}-L{line[-2:]}-A",
                "booth_id": booth_id,
                "material": material_by_type[booth_type],
                "supplier": "Northwind Coatings (synthetic)",
                "viscosity_s": 24.0 + (n % 3) * 0.5,
                "started_at": WINDOW_END - timedelta(days=3, hours=n),
            }
        )
    for booth_id in LINES["PAINT-LINE-02"]:
        booth_type = BOOTH_TYPES[LINES["PAINT-LINE-02"].index(booth_id)]
        if booth_type != "base":
            continue
        batches.append(
            {
                "batch_id": "BC-SILVER-455-L02-B",
                "booth_id": booth_id,
                "material": "BC-SILVER-455",
                "supplier": "Fabrikam Paints (synthetic)",
                "viscosity_s": 19.5,
                "started_at": WINDOW_END - timedelta(hours=6),
            }
        )
    return batches


def _nearest(readings_by_booth: dict[str, list[_Reading]], booth_id: str, ts: datetime) -> _Reading:
    rows = readings_by_booth[booth_id]
    return min(rows, key=lambda r: abs((r.ts - ts).total_seconds()))


def generate_events(rng: random.Random, readings: list[_Reading]) -> list[dict[str, Any]]:
    """Sparse background defects across all booths plus the planted clusters."""
    by_booth: dict[str, list[_Reading]] = {}
    for r in readings:
        by_booth.setdefault(r.booth_id, []).append(r)

    background_defects = ["dust_inclusion", "runs_sags", "uneven_coverage", "orange_peel"]
    specs: list[tuple[str, datetime, str, float]] = []
    start = WINDOW_END - timedelta(hours=WINDOW_HOURS)
    for _ in range(45):
        booth_id = rng.choice([b for b, _, _ in all_booths()])
        ts = start + timedelta(minutes=rng.randrange(0, (WINDOW_HOURS - 6) * 60))
        specs.append((booth_id, ts, rng.choice(background_defects), round(rng.uniform(0.6, 0.88), 2)))

    for minutes, conf in [(110, 0.86), (75, 0.9), (40, 0.92), (15, 0.93)]:
        specs.append(("BOOTH-03", WINDOW_END - timedelta(minutes=minutes), "orange_peel", conf))
    for minutes, conf in [(300, 0.84), (190, 0.9), (60, 0.91)]:
        specs.append(("BOOTH-05", WINDOW_END - timedelta(minutes=minutes), "fisheye_craters", conf))
    for minutes, conf in [(150, 0.83), (45, 0.89)]:
        specs.append(("BOOTH-07", WINDOW_END - timedelta(minutes=minutes), "dust_inclusion", conf))
    specs.append(("BOOTH-06", WINDOW_END - timedelta(minutes=200), "color_mismatch", 0.78))

    specs.sort(key=lambda s: s[1])
    events: list[dict[str, Any]] = []
    for i, (booth_id, ts, defect, conf) in enumerate(specs, start=1):
        r = _nearest(by_booth, booth_id, ts)
        events.append(
            {
                "event_id": f"QC-SEED-{i:05d}",
                "timestamp": ts.isoformat() + "Z",
                "plant_id": PLANT_ID,
                "production_line": booth_line(booth_id),
                "booth_id": booth_id,
                "body_id": f"CAR-{8000 + i * 7:06d}",
                "defect_type": defect,
                "model_confidence": conf,
                "telemetry": {
                    "booth_temperature_c": r.temperature_c,
                    "humidity_pct": r.humidity_pct,
                    "airflow_m_s": r.airflow_m_s,
                },
                "source": "synthetic_seed",
            }
        )
    return events


def seed_plant(session: Session, *, seed: int = SEED) -> dict[str, int]:
    """Insert the synthetic plant. Idempotent: plant context is skipped if booths exist."""
    rng = random.Random(seed)
    readings = generate_telemetry(rng)
    counts = {"booths": 0, "telemetry": 0, "maintenance": 0, "batches": 0, "events": 0}

    already = session.scalar(select(func.count()).select_from(Booth)) or 0
    if not already:
        for booth_id, line, booth_type in all_booths():
            session.add(
                Booth(booth_id=booth_id, plant_id=PLANT_ID, production_line=line, booth_type=booth_type)
            )
        session.flush()
        counts["booths"] = len(all_booths())

        session.add_all(TelemetryReading(**r.__dict__) for r in readings)
        counts["telemetry"] = len(readings)

        maintenance = generate_maintenance()
        session.add_all(MaintenanceLog(**m) for m in maintenance)
        counts["maintenance"] = len(maintenance)

        batches = generate_batches()
        session.add_all(MaterialBatch(**b) for b in batches)
        counts["batches"] = len(batches)
        session.flush()

    for payload in generate_events(rng, readings):
        _, created = create_inspection_event(session, InspectionEventCreate.model_validate(payload))
        counts["events"] += int(created)
    return counts

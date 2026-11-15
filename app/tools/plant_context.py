"""SQL tools over the synthetic plant context, used by the specialist agents.

Every function returns plain JSON-serialisable data so it can be sent back to a
model as a tool result and stored in the audit trail as-is.

SYNTHETIC DEMO ONLY: the "demo bands" and maintenance intervals below are invented
for the portfolio demo, not real paint-shop limits.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from statistics import mean
from typing import Any

from sqlalchemy.orm import Session

from app.database.repository import (
    fetch_booth_events,
    fetch_maintenance_logs,
    fetch_telemetry,
    get_active_batch,
)

METRICS = ("temperature_c", "humidity_pct", "airflow_m_s", "filter_dp_pa")

# Synthetic demo values, mirrored in SOP-PAINT-004/009/010 text.
VISCOSITY_DEMO_BAND_S = (22.0, 26.0)
MAINTENANCE_DEMO_INTERVAL_DAYS = {"spray_nozzle": 7, "exhaust_filter": 21, "booth_hvac": 60}


def _summarise(rows: list[Any]) -> dict[str, Any]:
    if not rows:
        return {"readings": 0}
    out: dict[str, Any] = {
        "readings": len(rows),
        "from": rows[0].ts.isoformat(),
        "to": rows[-1].ts.isoformat(),
    }
    last_hour_start = rows[-1].ts - timedelta(hours=1)
    recent = [r for r in rows if r.ts >= last_hour_start]
    for metric in METRICS:
        values = [getattr(r, metric) for r in rows]
        out[metric] = {
            "mean": round(mean(values), 2),
            "min": round(min(values), 2),
            "max": round(max(values), 2),
            "last_hour_mean": round(mean(getattr(r, metric) for r in recent), 2),
        }
    return out


def telemetry_window(session: Session, *, booth_id: str, as_of: datetime, hours: float) -> dict[str, Any]:
    """Summary of the booth's telemetry over the last `hours` before as_of."""
    rows = fetch_telemetry(session, booth_id=booth_id, start=as_of - timedelta(hours=hours), end=as_of)
    return {"booth_id": booth_id, "window_hours": hours, **_summarise(rows)}


def telemetry_baseline(
    session: Session,
    *,
    booth_id: str,
    as_of: datetime,
    hours: float = 48,
    exclude_recent_hours: float = 6,
) -> dict[str, Any]:
    """The booth's own normal: telemetry from `hours` ago up to `exclude_recent_hours` ago."""
    rows = fetch_telemetry(
        session,
        booth_id=booth_id,
        start=as_of - timedelta(hours=hours),
        end=as_of - timedelta(hours=exclude_recent_hours),
    )
    return {
        "booth_id": booth_id,
        "baseline_hours": hours,
        "excludes_recent_hours": exclude_recent_hours,
        **_summarise(rows),
    }


def maintenance_history(session: Session, *, booth_id: str, as_of: datetime, limit: int = 10) -> dict[str, Any]:
    """Recent maintenance entries plus days since the last action per component."""
    logs = fetch_maintenance_logs(session, booth_id=booth_id, before=as_of, limit=limit)
    entries = [
        {
            "component": log.component,
            "action": log.action,
            "ts": log.ts.isoformat(),
            "days_ago": round((as_of - log.ts).total_seconds() / 86400, 1),
            "technician": log.technician,
        }
        for log in logs
    ]
    last_by_component: dict[str, float] = {}
    for e in entries:
        last_by_component.setdefault(e["component"], e["days_ago"])
    overdue = [
        {"component": c, "days_since": d, "demo_interval_days": MAINTENANCE_DEMO_INTERVAL_DAYS[c]}
        for c, d in last_by_component.items()
        if c in MAINTENANCE_DEMO_INTERVAL_DAYS and d > MAINTENANCE_DEMO_INTERVAL_DAYS[c]
    ]
    return {
        "booth_id": booth_id,
        "entries": entries,
        "days_since_by_component": last_by_component,
        "overdue_vs_demo_interval": overdue,
    }


def booth_defect_mix(session: Session, *, booth_id: str, as_of: datetime, hours: float = 24) -> dict[str, Any]:
    """Count of each defect type in the booth over the window."""
    events = fetch_booth_events(session, booth_id=booth_id, start=as_of - timedelta(hours=hours), end=as_of)
    counts = Counter(e.defect_type for e in events)
    return {"booth_id": booth_id, "window_hours": hours, "total": len(events), "by_defect": dict(counts)}


def active_material_batch(session: Session, *, booth_id: str, as_of: datetime) -> dict[str, Any]:
    """The material batch running in the booth at as_of, with demo-band checks."""
    batch = get_active_batch(session, booth_id=booth_id, as_of=as_of)
    if batch is None:
        return {"booth_id": booth_id, "batch": None}
    low, high = VISCOSITY_DEMO_BAND_S
    return {
        "booth_id": booth_id,
        "batch": {
            "batch_id": batch.batch_id,
            "material": batch.material,
            "supplier": batch.supplier,
            "viscosity_s": batch.viscosity_s,
            "started_at": batch.started_at.isoformat(),
            "hours_since_start": round((as_of - batch.started_at).total_seconds() / 3600, 1),
        },
        "viscosity_demo_band_s": [low, high],
        "viscosity_in_demo_band": low <= batch.viscosity_s <= high,
    }

"""Read-only plant views: graph structure, tickets, stats, booths."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.models import ActionTicket, InspectionEvent, Investigation, TelemetryReading
from app.database.repository import list_booths, list_tickets
from app.database.session import get_session
from app.graph.builder import build_graph
from app.graph.specialists import SPECS, specialist_graph
from app.services.run_manager import get_run_manager

router = APIRouter(prefix="/api", tags=["plant"])


def _shape(graph: Any) -> dict[str, Any]:
    drawable = graph.get_graph()
    return {
        "nodes": [{"id": node_id} for node_id in drawable.nodes],
        "edges": [
            {"source": e.source, "target": e.target, "conditional": e.conditional} for e in drawable.edges
        ],
    }


@router.get("/graph")
def get_graph_structure() -> dict[str, Any]:
    """Nodes and edges of the investigation graph, plus each specialist's subgraph.

    Node ids match the `node` field of streamed steps, so a UI can light up a node
    when its step arrives.
    """
    return {
        **_shape(build_graph()),
        "specialists": {name: _shape(specialist_graph(name)) for name in SPECS},
    }


@router.get("/tickets")
def get_tickets(
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    return [
        {
            "ticket_id": t.ticket_id,
            "investigation_id": t.investigation_id,
            "event_id": t.event_id,
            "ticket_type": t.ticket_type,
            "priority": t.priority,
            "title": t.title,
            "description": t.description,
            "sop_references": t.sop_references_json or [],
            "status": t.status,
            "approved_by": t.approved_by,
            "approved_at": t.approved_at.isoformat() if t.approved_at else None,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in list_tickets(session, status=status, limit=limit)
    ]


def _counts(session: Session, column: Any) -> dict[str, int]:
    return {str(k): int(v) for k, v in session.execute(select(column, func.count()).group_by(column)).all()}


@router.get("/stats")
def get_stats(session: Session = Depends(get_session)) -> dict[str, Any]:
    """Headline numbers for the control room."""
    by_status = _counts(session, Investigation.status)
    return {
        "events_total": session.scalar(select(func.count()).select_from(InspectionEvent)) or 0,
        "investigations_total": sum(by_status.values()),
        "investigations_by_status": by_status,
        "awaiting_approval": by_status.get("awaiting_approval", 0),
        "investigations_by_defect": {
            str(k): int(v)
            for k, v in session.execute(
                select(InspectionEvent.defect_type, func.count())
                .join(Investigation, Investigation.event_id == InspectionEvent.event_id)
                .group_by(InspectionEvent.defect_type)
            ).all()
        },
        "tickets_by_status": _counts(session, ActionTicket.status),
        "active_runs": get_run_manager().active_count,
    }


@router.get("/booths")
def get_booths(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    """Every booth with its event counts, open reviews, and latest telemetry reading."""
    events = dict(
        session.execute(select(InspectionEvent.booth_id, func.count()).group_by(InspectionEvent.booth_id)).all()
    )
    last_event = dict(
        session.execute(
            select(InspectionEvent.booth_id, func.max(InspectionEvent.timestamp)).group_by(InspectionEvent.booth_id)
        ).all()
    )
    open_reviews = dict(
        session.execute(
            select(InspectionEvent.booth_id, func.count())
            .join(Investigation, Investigation.event_id == InspectionEvent.event_id)
            .where(Investigation.status == "awaiting_approval")
            .group_by(InspectionEvent.booth_id)
        ).all()
    )
    out: list[dict[str, Any]] = []
    for booth in list_booths(session):
        reading = session.scalars(
            select(TelemetryReading)
            .where(TelemetryReading.booth_id == booth.booth_id)
            .order_by(TelemetryReading.ts.desc())
            .limit(1)
        ).first()
        out.append(
            {
                "booth_id": booth.booth_id,
                "plant_id": booth.plant_id,
                "production_line": booth.production_line,
                "booth_type": booth.booth_type,
                "events_total": int(events.get(booth.booth_id, 0)),
                "last_event_at": last_event[booth.booth_id].isoformat() if booth.booth_id in last_event else None,
                "awaiting_approval": int(open_reviews.get(booth.booth_id, 0)),
                "latest_telemetry": {
                    "ts": reading.ts.isoformat(),
                    "temperature_c": reading.temperature_c,
                    "humidity_pct": reading.humidity_pct,
                    "airflow_m_s": reading.airflow_m_s,
                    "filter_dp_pa": reading.filter_dp_pa,
                }
                if reading
                else None,
            }
        )
    return out

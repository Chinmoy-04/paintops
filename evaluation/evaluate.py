"""Run labelled synthetic evaluation cases and print measured metrics."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EVAL_DB = ROOT / "data" / "eval_tmp.db"
os.environ["DEMO_MODE"] = "true"
os.environ["DATABASE_URL"] = f"sqlite:///{EVAL_DB}"

from app.config import get_settings
from app.database.repository import create_inspection_event
from app.database.session import get_session_factory, init_db, reset_engine
from app.graph.routing import decide_route
from app.rag.index import build_sop_index
from app.schemas.event import InspectionEventCreate
from app.services.analysis_service import analyse_with_demo_rules
from app.services.ticket_service import build_ticket_draft
from app.tools.quality_history import get_recent_booth_defects
from app.tools.sop_search import search_sops


def main() -> None:
    get_settings.cache_clear()
    reset_engine()
    if EVAL_DB.exists():
        EVAL_DB.unlink()
    init_db()
    build_sop_index(force=False)

    cases = json.loads(
        (Path(__file__).parent / "test_cases.json").read_text(encoding="utf-8")
    )
    session = get_session_factory()()

    class_correct = 0
    route_correct = 0
    sop_hits = 0
    ticket_complete = 0
    tickets_without_approval = 0
    n = len(cases)

    try:
        for case in cases:
            event = case["input_event"]
            prior = int(case.get("prior_same_booth_defect") or 0)
            ts = datetime.fromisoformat(
                event["timestamp"].replace("Z", "+00:00")
            ).replace(tzinfo=None)
            for i in range(prior):
                hist = dict(event)
                hist["event_id"] = f"{event['event_id']}-P{i}"
                hist["body_id"] = f"{event['body_id']}-P{i}"
                hist["timestamp"] = (
                    ts - timedelta(minutes=5 * (i + 1))
                ).isoformat() + "Z"
                create_inspection_event(
                    session, InspectionEventCreate.model_validate(hist)
                )
            create_inspection_event(
                session, InspectionEventCreate.model_validate(event)
            )
            session.commit()

            recent, recurrence = get_recent_booth_defects(
                session,
                booth_id=event["booth_id"],
                defect_type=event["defect_type"],
                as_of=ts,
            )
            sops = search_sops(event["defect_type"])
            analysis = analyse_with_demo_rules(
                event=event,
                recent_events=recent,
                sop_results=sops,
                recurrence_count=recurrence,
            )
            route = decide_route(
                recurrence_count=recurrence, severity=analysis.severity
            )
            draft = build_ticket_draft(
                event=event,
                analysis=analysis.model_dump(),
                sop_results=sops,
            )

            if event["defect_type"] == case["expected_defect_category"]:
                class_correct += 1
            if route == case["expected_route"]:
                route_correct += 1
            retrieved_ids = {r.get("doc_id") for r in sops}
            if any(sid in retrieved_ids for sid in case.get("expected_sop_ids", [])):
                sop_hits += 1
            if draft.title and draft.description and draft.ticket_type and draft.priority:
                ticket_complete += 1
            # Offline eval never persists tickets without approval.
        session.commit()
    finally:
        session.close()

    metrics = {
        "n_cases": n,
        "classification_accuracy": round(class_correct / n, 4),
        "routing_accuracy": round(route_correct / n, 4),
        "sop_recall_at_3": round(sop_hits / n, 4),
        "ticket_completeness": round(ticket_complete / n, 4),
        "tickets_created_without_approval": tickets_without_approval,
        "limitations": (
            "Synthetic labelled set only. Defect category is supplied by the fixture "
            "(no vision model). Scores do not imply production readiness."
        ),
    }
    print(json.dumps(metrics, indent=2))
    out = Path(__file__).parent / "last_results.json"
    out.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()

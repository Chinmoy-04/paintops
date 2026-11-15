"""Lesson 01 example: watch one investigation run through the multi-agent graph.

Run from the repo root against a throwaway database:

    DATABASE_URL=sqlite:///./data/lesson01.db python docs/learn/examples/01_watch_run.py

(PowerShell: $env:DATABASE_URL="sqlite:///./data/lesson01.db"; python docs/learn/examples/01_watch_run.py)
Delete data/lesson01.db afterwards, or before re-running it.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.database.repository import create_inspection_event, create_investigation
from app.database.seed import WINDOW_END, seed_plant
from app.database.session import get_session_factory, init_db
from app.graph.builder import build_graph
from app.schemas.event import InspectionEventCreate

init_db()
event = {
    "event_id": "QC-LESSON-1",
    "timestamp": WINDOW_END.isoformat() + "Z",
    "plant_id": "PLANT-01",
    "production_line": "PAINT-LINE-01",
    "booth_id": "BOOTH-03",
    "body_id": "CAR-LESSON-1",
    "defect_type": "orange_peel",
    "model_confidence": 0.93,
}
with get_session_factory()() as s:
    seed_plant(s)
    create_inspection_event(s, InspectionEventCreate.model_validate(event))
    inv = create_investigation(s, event_id=event["event_id"])
    s.commit()
    inv_id = inv.investigation_id

graph = build_graph(checkpointer=MemorySaver())
config = {"configurable": {"thread_id": inv_id}}
start = {"event": event, "investigation_id": inv_id, "thread_id": inv_id}

for namespace, update in graph.stream(start, config, stream_mode="updates", subgraphs=True):
    where = " > ".join(ns.split(":")[0] for ns in namespace) or "parent"
    print(f"[{where}] {list(update)}")

print("paused before:", graph.get_state(config).next)
graph.invoke(Command(resume={"decision": "approved", "reviewer": "you"}), config)
print("ticket:", graph.get_state(config).values["ticket_id"])

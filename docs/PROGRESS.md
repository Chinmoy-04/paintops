# PaintOps progress log

The running record of the build, one entry per phase. Read this together with
[`MASTER_PLAN.md`](MASTER_PLAN.md) at the start of every chat. The last commit of each
phase updates this file: its status, what was built, decisions and deviations agreed,
known gaps handed to later phases, and the "Next phase: start here" section.

## Status

| Phase | Name | Status | PR |
|---|---|---|---|
| 0 | Foundations and bug fixes | ✅ merged | [#1](https://github.com/Chinmoy-04/paintops/pull/1) |
| 1 | Multi-agent LangGraph | ✅ merged | [#2](https://github.com/Chinmoy-04/paintops/pull/2) |
| — | Plan handoff setup | this PR | — |
| 2 | Async runs, streaming, inspection API | ⏭ next | — |
| 3–15 | See `MASTER_PLAN.md` | not started | — |

## Phase 0 — Foundations and bug fixes ✅

PR: [#1](https://github.com/Chinmoy-04/paintops/pull/1) · branch `v2/00-foundations`

Built:
- Bug fixes: `apply_decision` marks the investigation failed (with an audit row) when
  resuming the graph throws; validation errors end the run in a `record_invalid` node
  (status `invalid`); a recurrence count of 0 is no longer turned into 1; deprecated
  `datetime.utcnow()` replaced.
- New tables: `booths`, `telemetry_readings`, `maintenance_logs`, `material_batches`,
  `investigation_steps` (for stream replay). `investigations` gains `findings_json` and
  `revision_count`.
- Defect types `fisheye_craters` and `color_mismatch` added.
- `app/database/seed.py`: a deterministic synthetic plant (1 plant, 3 lines, 9 booths,
  48 h telemetry, maintenance, batches, events) with planted patterns for the
  specialists to find. Replaces `data/synthetic_events.json`.
- SOPs 007–010 added; hero example moved to `PAINT-LINE-01` / `BOOTH-03`.
- `.dockerignore` added.

Tests: 29 passing.

## Phase 1 — Multi-agent LangGraph ✅

PR: [#2](https://github.com/Chinmoy-04/paintops/pull/2) · branch `v2/01-multi-agent` ·
lesson [`learn/01-langgraph-multi-agent.md`](learn/01-langgraph-multi-agent.md)

Built:
- Graph: `intake → triage → plan_investigation =Send⇒ environment / equipment / process
  specialists (parallel) → synthesise → route_decision → record_observation |
  draft_ticket → human_review → create_ticket | record_rejection | draft_ticket (revise)
  → notify`.
- Specialists are compiled subgraphs (`agent → tools → report`) built from
  `SpecialistSpec` in `app/graph/specialists/base.py`, with private state, a 4-round tool
  cap and a `RetryPolicy` on the model call. A specialist that still fails after retries
  becomes a `status="failed"` Finding instead of failing the investigation.
- Tools in `app/tools/plant_context.py` query the synthetic plant (telemetry,
  maintenance, defect mix, material batch) plus SOP search. A tool that never ran is
  reported as "not checked", never as "nothing found".
- Which specialists run is a deterministic defect → specialists map
  (`app/graph/specialists/__init__.py::plan_for`); `process` always runs.
- `findings` uses an `operator.add` reducer so parallel results merge.
- Severity stays deterministic: findings can only lift low → medium.
- `human_review` accepts approved / rejected / revise; the revise loop is capped at 2.
- `notify` writes a `notification_outbox` row.
- `DEMO_MODE` uses `ScriptedChatModel` (`app/services/llm.py`), a real LangChain chat
  model that plays back tool calls.

Tests: 40 passing (29 existing + 11 new). Evaluation scores unchanged.

## Known gaps (assigned to later phases)

| Gap | Fixed in |
|---|---|
| `DecisionRequest` and the API don't accept `revise` yet (the graph does) | Phase 2 |
| `DEMO_MODE=false` raises an error until vLLM is added | Phase 5 |
| `notify` only queues after approve/reject; "approval needed" notifications are not sent | Phase 6 |
| `evaluation/evaluate.py` still scores the old demo rules, not the graph | Phase 7 |

## Decisions and deviations

- The expanded master plan (`MASTER_PLAN.md`) replaces the earlier 8-phase plan. Phases
  0–7 keep their agreed scope; phases 8–15 and the basics labs are added.
- No other deviations so far.

## Next phase: start here — Phase 2, async runs, streaming, inspection API

- **Before starting:** check that `main` contains Phase 1 (PR #2) and this handoff PR,
  then confirm the Phase 2 scope in one short message.
- **Branch:** `v2/02-streaming-api` from an up-to-date `main`.
- **Labs first:** write and verify `docs/learn/labs/01-langgraph-basics/` (L1: a 20-line
  graph with state, nodes, edges, a conditional edge, a checkpointer) and
  `docs/learn/labs/02-async-streaming/` (L2: `async/await`, an SSE endpoint in FastAPI,
  reading it with `curl`). Neither may use PaintOps code.
- **Then the phase scope** (see `MASTER_PLAN.md`, Phase 2):
  - Async checkpointer opened in the FastAPI lifespan (`app/main.py`,
    `app/graph/builder.py`).
  - `app/services/run_manager.py`: run the graph as an asyncio task with
    `astream(stream_mode=["updates","custom"], subgraphs=True)`, store each item via
    `add_investigation_step`, publish to subscribers; specialists emit tool-call events
    with `get_stream_writer()`.
  - Endpoints: `POST /api/events` (202 at once), `GET /api/investigations/{id}/stream`
    (SSE, replay then live), `/steps`, `/history`, `GET /api/graph`, `/api/tickets`,
    `/api/stats`, `/api/booths`, `POST /api/scenarios/{name}`, `GET /api/events/stream`;
    the decision endpoint and `DecisionRequest` gain `revise`.
  - `X-PaintOps-Key` on ingest and n8n-facing routes; CORS narrowed.
  - Lesson note `docs/learn/02-...md`.
- **Risks to check first:** which async checkpointer package and version match the
  installed `langgraph`; that the existing 40 tests still pass once the API becomes async.

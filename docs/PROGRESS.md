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
| — | Plan handoff setup | ✅ merged | [#3](https://github.com/Chinmoy-04/paintops/pull/3) |
| 2 | Async runs, streaming, inspection API | 🔍 PR open | branch `v2/02-streaming-api` |
| 3 | React control-room UI | ⏭ next | — |
| 4–15 | See `MASTER_PLAN.md` | not started | — |

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

## Phase 2 — Async runs, streaming, inspection API 🔍

PR: from branch `v2/02-streaming-api` · labs
[`L1`](learn/labs/01-langgraph-basics/README.md),
[`L2`](learn/labs/02-async-streaming/README.md) · lesson
[`learn/02-async-streaming-api.md`](learn/02-async-streaming-api.md)

Built:
- Labs L1 (LangGraph: state, nodes, edges, conditional edge, checkpointer) and L2
  (`async/await`, tasks, queues, an SSE endpoint read with `curl`). Both run, neither
  uses PaintOps code.
- `AsyncSqliteSaver` opened in the FastAPI lifespan through
  `app/graph/builder.py::open_graph` (an async context manager). `get_compiled_graph()`
  raises if the graph is not open. The nodes stay synchronous; LangGraph runs them in
  worker threads under `astream`.
- `app/services/run_manager.py::RunManager`: each run (start or resume) is an asyncio
  task streaming `astream(stream_mode=["updates","custom"], subgraphs=True)`. Every
  item becomes a step (`run_started`, `node`, `tool_call`, `tool_result`, `interrupt`,
  `run_finished`/`run_failed`), stored with `add_investigation_step` (per-investigation
  `seq`) and then published to per-investigation subscribers and the plant-wide feed.
  A failed run marks the investigation `failed` with an `investigation_failed` /
  `resume_failed` audit row; it never raises out of the task.
- Specialists emit `tool_call` / `tool_result` custom events with `get_stream_writer()`
  (`app/graph/specialists/base.py`).
- Endpoints: `POST /api/events` (202 at once, 200 for a replay, response has
  `stream_url`); `GET /api/investigations/{id}/stream` (SSE: subscribe, replay stored
  steps, then live; event id = seq; `Last-Event-ID` / `?after_seq=`; ends with an
  `end` event when no run is in progress); `/steps`; `/history` (checkpoints newest
  first, with interrupts and full state values); `GET /api/graph` (nodes and edges,
  plus each specialist subgraph); `/api/tickets`; `/api/stats`; `/api/booths`;
  `POST /api/scenarios/{name}` (`booth03_orange_peel`, `line02_fisheye`, `booth07_dust`,
  `booth08_minor`; seeds the plant if empty; `app/services/scenarios.py`);
  `GET /api/events/stream` (live plant-wide feed, no replay).
- Decision endpoint and `DecisionRequest` accept `revise`; a third revise returns 409.
  The endpoint waits for the short resumed run; `asyncio.shield` keeps the run alive
  if the client disconnects.
- `X-PaintOps-Key` (`app/api/security.py`, `secrets.compare_digest`) on
  `POST /api/events` and `POST /api/scenarios/{name}`. Key from `PAINTOPS_API_KEY`
  (default `paintops-dev-key`, with a startup warning while the default is used).
- CORS narrowed to `CORS_ORIGINS` (default: Vite dev server on 5173), `GET`/`POST`,
  headers `Content-Type`, `X-PaintOps-Key`, `Last-Event-ID`.
- `scripts/run_example_event.py` runs the graph through the RunManager.

Tests: 51 passing (40 existing, 2 of them ported to the async service, plus 11 new
API tests: 202 at once, key check, stream order/replay/`Last-Event-ID`, history,
revise and its cap, scenarios, booths, stats, graph, plant feed, CORS). Checked live
with uvicorn and `curl` on a throwaway database: scenario → stream → revise → approve
→ ticket.

Decisions (within the plan's scope, no new libraries):
- SSE uses FastAPI's built-in `fastapi.sse.EventSourceResponse` (FastAPI 0.162), so no
  SSE package was added.
- Read endpoints and the decision endpoint have no key: the browser UI calls them and
  the plan has no login (out of scope). The key is on the routes that create work.
- A stream closes with `end` when the investigation is idle (including waiting for
  review); clients reconnect after a decision.

## Known gaps (assigned to later phases)

| Gap | Fixed in |
|---|---|
| ~~`DecisionRequest` and the API don't accept `revise` yet~~ | done in Phase 2 |
| The imported n8n ingestion workflow does not send `X-PaintOps-Key`, so it now gets 401 | Phase 6 (hardened ingestion) |
| Runs are in-process asyncio tasks: a run in progress when the API stops is cancelled and its investigation stays `processing` (no automatic recovery) | Phase 13 (worker + job queue) |
| `/history` returns full state at every checkpoint; fine for demo sizes, may need trimming | Phase 3 if the UI needs it |
| `DEMO_MODE=false` raises an error until vLLM is added | Phase 5 |
| `notify` only queues after approve/reject; "approval needed" notifications are not sent | Phase 6 |
| `evaluation/evaluate.py` still scores the old demo rules, not the graph | Phase 7 |

## Decisions and deviations

- The expanded master plan (`MASTER_PLAN.md`) replaces the earlier 8-phase plan. Phases
  0–7 keep their agreed scope; phases 8–15 and the basics labs are added.
- Phase 2: no deviations. Leftover uncommitted Phase 2 edits from an earlier chat were
  discarded at your request, and the phase was built from a clean `main`.
- No other deviations so far.

## Next phase: start here — Phase 3, React control-room UI

- **Before starting:** check that `main` contains Phase 2 (the `v2/02-streaming-api`
  PR), then confirm the Phase 3 scope in one short message.
- **Branch:** `v2/03-web-ui` from an up-to-date `main`.
- **Lab first:** `docs/learn/labs/03-react-basics/` (L3: a component, state, fetching an
  API, one React Flow node). It may not use PaintOps code.
- **Load the design skills first** (see `MASTER_PLAN.md`, Phase 3).
- **Then the phase scope** (see `MASTER_PLAN.md`, Phase 3): `web/` with Vite, React,
  TypeScript, Tailwind, shadcn/ui, `@xyflow/react`, TanStack Query, Motion. Screens:
  Control room, Investigation (live graph, node panel, replay scrubber, findings,
  approve/revise/reject), Review inbox, Tickets, Workflows. Streamlit removed.
- **API it builds on** (all in lesson 02): `GET /api/graph` (node ids match the steps'
  `node`; specialist inner steps carry `namespace` `"<name>_agent:<task id>"`),
  `GET /api/investigations/{id}/stream` (SSE; event names = step kinds; ends with
  `end`), `/steps`, `/history`, `GET /api/events/stream`, `/api/stats`, `/api/booths`,
  `/api/tickets`, `POST /api/scenarios/{name}` and `POST /api/events` (both need
  `X-PaintOps-Key`), `POST /api/investigations/{id}/decision` (`approved` /
  `rejected` / `revise`).
- **Risks to check first:** CORS allows only `CORS_ORIGINS` (default
  `http://localhost:5173` and `http://127.0.0.1:5173`); if Vite runs elsewhere, set it.
  A browser `EventSource` cannot send custom headers, which is fine (streams need no
  key), but scenario buttons must send `X-PaintOps-Key` with `fetch`. `EventSource`
  reconnects after `end` unless the UI calls `close()`.

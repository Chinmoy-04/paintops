# Lesson 02 — Async runs, live streaming, and an inspection API

Phase 1 built the agent graph, but the API ran it *inside* the HTTP request:
`POST /api/events` did not answer until every specialist had finished. Phase 2 turns
that around. The API now accepts an event in a fraction of a second (`202 Accepted`),
runs the graph in the background, and streams every step to anyone watching: each
node, each specialist's tool call, and the pause for human review. This note explains
the four ideas behind that, shows where each lives in the repo, and gives you things
to break and exercises.

Do the labs first if any of this is new:
[L1 LangGraph basics](labs/01-langgraph-basics/README.md) and
[L2 async + SSE](labs/02-async-streaming/README.md).

Versions used: `langgraph` 1.2.18, `langgraph-checkpoint-sqlite` 3.1.2, `aiosqlite`
0.22.1, `fastapi` 0.162.0 (its built-in `fastapi.sse`, so no extra SSE library).

## Watch it run first

Start the API (terminal 1). The two environment variables keep this demo out of your
normal database; delete `data/lesson02*.db` before running it again.

```bash
DATABASE_URL=sqlite:///./data/lesson02.db CHECKPOINT_DB_PATH=./data/lesson02_cp.db .venv/Scripts/python.exe -m uvicorn app.main:app --port 8000
```

PowerShell:

```powershell
$env:DATABASE_URL="sqlite:///./data/lesson02.db"; $env:CHECKPOINT_DB_PATH="./data/lesson02_cp.db"; .venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
```

Start a demo scenario (terminal 2). The scenario seeds the synthetic plant on first
use and creates an event on BOOTH-03, where orange peel is recurring:

```bash
curl -s -X POST http://127.0.0.1:8000/api/scenarios/booth03_orange_peel -H "X-PaintOps-Key: paintops-dev-key"
```

It answers at once with `"status": "processing"` and a `stream_url`. Read the stream
(use the investigation id from the answer):

```bash
curl -N http://127.0.0.1:8000/api/investigations/<id>/stream
```

You will see about 45 events. Abridged:

```text
event: run_started
data: {"investigation_id": "...", "seq": 1, "node": "run", "namespace": "", "kind": "run_started", ...}
id: 1

event: node
data: {... "seq": 2, "node": "intake", "namespace": "", "kind": "node", "payload": {"event": {...}}}
id: 2

event: node
data: {... "seq": 5, "node": "agent", "namespace": "environment_agent:602424a1-...", "kind": "node", ...}

event: tool_call
data: {... "node": "environment_agent", "kind": "tool_call", "payload": {"type": "tool_call", "specialist": "environment", "tool": "get_telemetry_window", "args": {...}}}

event: tool_result
data: {... "payload": {"tool": "get_telemetry_window", "ok": true, "duration_ms": 4, "summary": "{\"booth_id\": ..."}}

...
event: interrupt
data: {... "node": "human_review", "kind": "interrupt", "payload": {"interrupts": [{"id": "...", "value": {"type": "approval_required", ...}}]}}

event: run_finished
data: {... "payload": {"mode": "start", "status": "awaiting_approval"}}

event: end
data: {"investigation_id": "...", "status": "awaiting_approval"}
```

Now send it back for revision, then approve it, and look at what was stored:

```bash
curl -s -X POST http://127.0.0.1:8000/api/investigations/<id>/decision -H "Content-Type: application/json" -d "{\"decision\":\"revise\",\"reviewer\":\"qm\",\"comment\":\"add nozzle photo\"}"
curl -s -X POST http://127.0.0.1:8000/api/investigations/<id>/decision -H "Content-Type: application/json" -d "{\"decision\":\"approved\",\"reviewer\":\"qm\"}"
curl -s http://127.0.0.1:8000/api/investigations/<id>/steps
curl -s http://127.0.0.1:8000/api/investigations/<id>/history
curl -s http://127.0.0.1:8000/api/tickets
```

Interactive docs for every endpoint: <http://127.0.0.1:8000/docs>.

## 1. An async checkpointer, opened in the lifespan

The graph saves a checkpoint after every step (lab L1). Phase 1 used `SqliteSaver`,
which is synchronous. To run the graph with `astream` inside FastAPI's event loop we
need `AsyncSqliteSaver` (from `langgraph-checkpoint-sqlite`, backed by `aiosqlite`).

An `aiosqlite` connection belongs to the event loop that opened it. That rules out
opening it at import time, as Phase 1 did. It is opened in the app's **lifespan**,
the async context manager FastAPI runs once at startup and once at shutdown:

- `app/graph/builder.py::open_graph` is an `asynccontextmanager`. It opens
  `AsyncSqliteSaver.from_conn_string(...)`, compiles the graph with it, and closes the
  connection on exit. `get_compiled_graph()` hands out the open graph (and raises if
  nobody opened it).
- `app/main.py::lifespan` does `async with open_graph():`, creates the `RunManager`,
  `yield`s (the app serves requests), then cancels any runs still going and closes.

The nodes themselves are still ordinary synchronous functions that use SQLAlchemy.
That is fine: when you `astream` a graph, LangGraph runs sync nodes in a worker
thread, so they do not block the loop. The specialist subgraphs, invoked from inside
a node with the parent's `config`, still share the checkpointer and still stream.

## 2. A run is a background task: `app/services/run_manager.py`

`POST /api/events` now does only the quick part: store the event, create the
investigation row, and call `RunManager.start(...)`, which does
`asyncio.create_task(self._run(...))` and returns. The HTTP answer goes out while the
task keeps running (lab L2, `create_task`).

`_run` is one loop over the graph's stream:

```python
async for namespace, mode, chunk in graph.astream(
    graph_input, config, stream_mode=["updates", "custom"], subgraphs=True
):
```

- `stream_mode="updates"` yields `{node_name: what_it_returned}` after each node.
- `stream_mode="custom"` yields whatever a node passes to `get_stream_writer()`. The
  specialists' `tools` node (`app/graph/specialists/base.py`) writes a `tool_call`
  before each tool and a `tool_result` (ok, duration, a 300-character summary) after.
  Outside a streaming run the writer does nothing, so tests that `invoke` the graph
  are unaffected.
- Asking for **several modes** makes each item carry its mode: `(namespace, mode, chunk)`.
- `subgraphs=True` also streams from inside the specialist subgraphs. The
  `namespace` tuple says where an item came from: `()` is the parent graph,
  `("environment_agent:602424a1-...",)` is inside that specialist (the part after the
  colon is the task id, different every run).
- When the graph pauses at `interrupt()`, the updates stream yields
  `{"__interrupt__": (Interrupt(...),)}`. That becomes the `interrupt` step.

Each item becomes a **step**: stored with `add_investigation_step` in the
`investigation_steps` table (created in Phase 0 for exactly this), given the next
`seq` for that investigation, then published to subscribers. Storing comes first, so
a step a client has seen is always a step it can replay. SQLAlchemy is synchronous, so
the store runs in `asyncio.to_thread`.

A resume is the same loop with `Command(resume=decision)` as the input. Every run is
wrapped in `run_started` and `run_finished` (or `run_failed`) steps. A run that throws
marks the investigation `failed`, writes an `investigation_failed` or `resume_failed`
audit row, and publishes `run_failed`. It never raises out of the task, because
nobody would be there to catch it.

## 3. Server-Sent Events: replay, then live

`GET /api/investigations/{id}/stream` (`app/api/investigations.py`) is an SSE
endpoint built with FastAPI's `EventSourceResponse` (lab L2). The order of operations
matters:

1. **Subscribe first.** The handler gets an `asyncio.Queue` from the RunManager.
2. **Replay.** It reads the stored steps from the database and sends them.
3. **Live.** It sends whatever arrives on the queue, skipping any `seq` it already
   sent in the replay.

Doing it in the other order (replay, then subscribe) loses any step stored between
the two. Subscribing first means a step might arrive both ways, and the `seq` check
drops the duplicate.

Each SSE event's `id` is the step's `seq`. A browser's `EventSource` remembers the
last id and, on reconnect, sends it as `Last-Event-ID`; the endpoint then replays only
newer steps. `?after_seq=N` does the same for `curl`.

The stream **ends** with an `end` event (carrying the investigation status) once no
run is in progress. An investigation waiting for review is idle, not running. After
a decision, connect again to watch the resumed run (the new steps carry on with the
next seq numbers).

`GET /api/events/stream` is the plant-wide feed: a compact copy of every top-level
step from every investigation (no replay), for the control room in Phase 3.

## 4. The rest of the API

| Endpoint | What it gives you |
|---|---|
| `POST /api/events` | 202 at once; 200 for an idempotent replay. Needs `X-PaintOps-Key`. |
| `POST /api/scenarios/{name}` | A fresh event for `booth03_orange_peel`, `line02_fisheye`, `booth07_dust`, or `booth08_minor` (`app/services/scenarios.py`). Needs `X-PaintOps-Key`. |
| `GET /api/investigations/{id}/stream` | SSE, replay then live |
| `GET /api/investigations/{id}/steps` | The stored steps as JSON (`?after_seq=`) |
| `GET /api/investigations/{id}/history` | Every checkpoint, newest first: step, source, next node, interrupts, and the full state, ready for a replay scrubber |
| `GET /api/graph` | Nodes and edges of the graph and of each specialist subgraph, from `compiled.get_graph()`. Node ids match the steps' `node` field. |
| `GET /api/tickets`, `/api/stats`, `/api/booths` | Read-only views for the UI |
| `POST /api/investigations/{id}/decision` | `approved`, `rejected`, or now `revise` (409 after 2 revisions). Waits for the short resumed run. |

**`X-PaintOps-Key`** (`app/api/security.py`) protects the routes that *create*
work: ingest and scenarios, which n8n will call. The check uses
`secrets.compare_digest`, so a wrong key takes the same time to reject however many
characters match. The key comes from `PAINTOPS_API_KEY`; the built-in default works
on a fresh checkout and the API logs a warning while it is in use.

**CORS** was `allow_origins=["*"]`. It is now the list in `CORS_ORIGINS` (default:
the Vite dev server that Phase 3 adds), only `GET` and `POST`, and only the headers
the UI needs (`Content-Type`, `X-PaintOps-Key`, `Last-Event-ID`). CORS only limits
which *web pages* may call the API from a browser; `curl` ignores it, which is why the
key exists too.

## Break it (and see what happens)

1. In `stream_investigation`, read the replay first and call `manager.subscribe(...)`
   after it. Run `pytest tests/test_api.py -q`: everything still passes (it did three
   times in a row when this lesson was written). So why is it a bug? (It is a race: a
   step stored between the read and the subscribe is never sent to that client. Demo
   runs are fast and the tests rarely land in that gap, which is exactly why races
   survive test suites.)
2. In `app/main.py`, replace `async with open_graph():` with a plain `yield` and
   start the server. `POST` a scenario: it is accepted (202), but the run fails.
   `GET /api/investigations/<id>/steps` shows `run_failed` with "The graph is not
   open", and the investigation is `failed` with an audit row.
3. In `RunManager._run`, remove `"custom"` from `stream_mode`. Run
   `pytest tests/test_api.py -q`: `test_stream_replays_steps_in_order_and_ends` fails
   because the `tool_call` events are gone, while every node step still arrives.
4. Change `post_event` from `async def` to `def`. `POST /api/events` now fails with
   `RuntimeError: no running event loop`: FastAPI runs a plain `def` route in a worker
   thread, and `asyncio.create_task` needs the loop's own thread.

## Exercises

1. Add a `kind="heartbeat"` step to the stream every 10 seconds of silence, without
   storing it. (Hint: the `asyncio.wait_for(..., timeout=1.0)` loop already wakes up
   every second.) Why should it not get an `id`?
2. `GET /api/investigations/{id}/history` returns the full state at every checkpoint.
   Add `?include_values=false` to leave the values out, and measure the size of both
   answers for a revised investigation.
3. Open <http://127.0.0.1:8000/docs>, start a scenario, then in the browser console
   on the same origin run
   `const es = new EventSource("/api/investigations/<id>/stream"); es.addEventListener("tool_call", e => console.log(JSON.parse(e.data).payload))`.
   Then close it on `end`. Why must you close it yourself? (Lab L2, exercise 3.)
4. Two reviewers click "approve" at the same moment. Read `apply_decision` and
   `RunManager._spawn`: what does the second one get, and is a second ticket possible?

## Where this goes next

Phase 3 builds the React control room on exactly these endpoints: `/api/graph` draws
the graph, `/stream` animates it, `/history` drives the replay scrubber, and
`/api/events/stream` keeps the control room live. Phase 13 moves the runs from an
in-process asyncio task to a worker Deployment fed by a job queue; the
store-then-publish step format stays the same.

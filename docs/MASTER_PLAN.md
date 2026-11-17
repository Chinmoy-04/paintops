# PaintOps master plan (expanded) — from basics to a full agentic platform

> **STRICTLY FOLLOW THIS PLAN.** Build the phases in order, exactly as scoped here. Do not
> add, drop, reorder, or substitute features, libraries, or services on your own. If
> something turns out to be wrong or impossible, stop and ask before deviating, and record
> the agreed change in this file.

## Context

The baseline v2 plan (8 phases) is under way: **Phase 0 and Phase 1 are merged** (PRs #1,
#2). You now want a much bigger project that is still a learning path: start from the
basics of each technology, and end somewhere genuinely complex. The baseline phases stay
exactly as agreed; this plan **adds** to them:

- a **from-zero basics lab** before each technology is used,
- **seven new phases** after the baseline (observability, advanced RAG, agent memory and
  self-critique, a vision model, LLM fine-tuning, Kubernetes, CI/CD + free public deployment),
- a final capstone.

This file replaces `golden-rolling-nautilus.md` as the master plan. It is copied into the
repo as `docs/MASTER_PLAN.md` in the handoff setup (see "One chat per phase").

### Decisions (all confirmed by you)

| Topic | Decision |
|---|---|
| Baseline choices | Unchanged: React + React Flow dark control room (animated 2D), vLLM on the RTX 5060, multi-agent graph, 1 plant / 3 lines / 9 booths, Postgres, n8n → Mailpit, PR per phase, stop after every phase |
| New AI tracks | Agent memory + self-critique, advanced RAG, vision defect model, fine-tuning the local LLM |
| New platform tracks | Observability stack, Kubernetes + CI/CD |
| Not added | Real-time MQTT stream, login/roles, second plant |
| Basics | A standalone from-zero lab before each topic, plus a catch-up lab for LangGraph |
| Pace | One new chat per phase; I stop before every phase and never run two phases in one chat |
| Deployment | Must be deployable **for free**; free-tier cloud accounts allowed, nothing paid |
| Attribution | No Claude co-author or "Generated with" lines anywhere (global rule) |

Everything stays **synthetic**; a human approves every ticket; routing stays deterministic Python.

## The learning ladder

| Level | Phases | What you can do afterwards |
|---|---|---|
| 1. Foundations | 0–3 | Build and stream a multi-agent LangGraph app and show it live in a UI |
| 2. Running it properly | 4–7 | Containerise a multi-service stack, serve a local LLM, automate with n8n |
| 3. Seeing inside it | 8 | Trace, measure, and evaluate agents |
| 4. Smarter agents | 9–10 | Advanced retrieval, long-term memory, self-critique, dynamic planning |
| 5. Your own models | 11–12 | Train a vision model and fine-tune an LLM on your GPU |
| 6. Production platform | 13–14 | Kubernetes, CI/CD, a free public deployment |
| 7. Capstone | 15 | One polished, documented, demo-ready system |

## Basics labs

Each lab lives in `docs/learn/labs/NN-<topic>/`: a short README and tiny runnable files that
have **nothing to do with PaintOps**, so the idea is seen alone before the project uses it.
Each takes 30–60 minutes and ends with 2–3 exercises. A lab ships in the same PR as the
phase it prepares, and you do the lab **before** reading that phase's code.

| Lab | Before phase | From zero |
|---|---|---|
| L1 LangGraph basics (catch-up) | 2 | A 20-line graph: state, nodes, edges, a conditional edge, a checkpointer |
| L2 Async + streaming | 2 | `async/await`, an SSE endpoint in FastAPI, reading it with `curl` |
| L3 React + data fetching | 3 | A component, state, fetching an API, one React Flow node |
| L4 Docker basics | 4 | First Dockerfile, layers and cache, a 2-service Compose file, volumes, networks |
| L5 Talking to an LLM | 5 | Chat completions against a local server, tool calling by hand, structured output |
| L6 n8n basics | 6 | First workflow: trigger, HTTP request, IF, expressions, credentials |
| L8 Observability basics | 8 | A trace vs a metric vs a log; instrument a 10-line script |
| L9 RAG basics | 9 | Embeddings, chunking, cosine similarity, a vector search in 30 lines |
| L10 Agent memory basics | 10 | Short-term (checkpoint) vs long-term (store) memory in a toy chatbot |
| L11 Training a model | 11 | PyTorch tensors, a training loop, train/validation split on a toy dataset |
| L12 Fine-tuning basics | 12 | What LoRA changes, tokenising a dataset, one tiny training run |
| L13 Kubernetes basics | 13 | Pod, Deployment, Service on a local cluster; `kubectl` essentials |
| L14 CI basics | 14 | A GitHub Actions workflow that runs tests on every push |

---

## Baseline phases (unchanged scope)

### Phase 0 — Foundations and bug fixes ✅ merged (PR #1)
### Phase 1 — Multi-agent LangGraph ✅ merged (PR #2), lesson 01

### Phase 2 — Async runs, streaming, inspection API  *(labs L1, L2; lesson 02)*
Branch `v2/02-streaming-api`.
- Async checkpointer opened in the FastAPI lifespan (`app/main.py`, `app/graph/builder.py`).
- New `app/services/run_manager.py`: run the graph as an asyncio task with
  `astream(stream_mode=["updates","custom"], subgraphs=True)`, store each item in
  `investigation_steps` (table exists; `add_investigation_step` in `app/database/repository.py`), publish to subscribers. Specialists emit tool-call events with `get_stream_writer()`.
- Endpoints: `POST /api/events` (202 at once), `GET /api/investigations/{id}/stream` (SSE, replay then live), `/steps`, `/history`, `GET /api/graph`, `/api/tickets`, `/api/stats`, `/api/booths`, `POST /api/scenarios/{name}`, `GET /api/events/stream`; decision endpoint and `DecisionRequest` gain `revise`.
- `X-PaintOps-Key` on ingest and n8n-facing routes; CORS narrowed.

### Phase 3 — React control-room UI  *(lab L3; lesson 03)*
Branch `v2/03-web-ui`. `web/`: Vite, React, TypeScript, Tailwind, shadcn/ui, `@xyflow/react`, TanStack Query, Motion. Load the design skills first (`impeccable`, `design-taste-frontend`, `ui-ux-pro-max`, `shadcn`, `magic-ui`/`kokonutui`, `dataviz`, and any newer ones installed).
Screens: Control room, Investigation (live graph with animated nodes and edge particles, node panel, replay scrubber, findings, approve/revise/reject), Review inbox, Tickets, Workflows. Streamlit removed.

### Phase 4 — Docker stack  *(lab L4; lesson 04)*
Branch `v2/04-docker`. Multi-stage API and web images, Compose with `postgres`, `init`, `api`, `web`, `n8n`, `mailpit`, `vllm` (gpu profile), dev override with `docker compose watch`, Postgres for data and checkpoints, basic CI (pytest + web build + compose build).

### Phase 5 — vLLM and real tool-calling agents  *(lab L5; lesson 05)*
Branch `v2/05-vllm`. `vllm/vllm-openai` serving `Qwen/Qwen2.5-3B-Instruct-AWQ`; `app/services/llm.py::get_chat_model` returns `ChatOpenAI(base_url=LLM_BASE_URL)` when `DEMO_MODE=false`; validated `Finding` output with one repair retry. First step: verify GPU passthrough; fallback is Ollama's `/v1` with no code change.

### Phase 6 — n8n workflows  *(lab L6; lesson 06)*
Branch `v2/06-n8n`. Ingestion (hardened), line simulator, notifications to Mailpit (reads `notification_outbox`), approval escalation, error workflow; auto-import at container start.

### Phase 7 — v2 milestone: evaluation, docs, demo
Branch `v2/07-polish`. Evaluation over the real graph (~40 cases, demo and LLM modes reported separately), README, demo script. Tag `v2.0`.

---

## New phases

### Phase 8 — Observability and continuous evaluation  *(lab L8; lesson 08)*
Branch `v3/08-observability`.
- **Tracing:** self-hosted Langfuse in Compose; LangGraph runs traced via the Langfuse callback (one trace per investigation, spans per node, specialist, tool, and model call, token counts and latency).
- **Metrics:** `/metrics` on the API (Prometheus client): investigations by status, node latency, tool errors, queue depth, approval wait time. Prometheus + Grafana services with two provisioned dashboards (plant quality, agent health).
- **Logs:** structured JSON logs carrying `investigation_id` and trace id.
- **Evaluation:** `evaluation/` becomes a suite: deterministic checks plus an **LLM judge** scoring hypothesis groundedness against tool results; results pushed to Langfuse as scores.
- **UI:** an "Observability" page linking each investigation to its trace, with live latency and cost tiles.
- Done when: one investigation can be followed UI → trace → metrics → logs by id.

### Phase 9 — Advanced RAG and a knowledge graph  *(lab L9; lesson 09)*
Branch `v3/09-advanced-rag`.
- **Retrieval pipeline** in `app/rag/`: hybrid search (BM25 + vectors) with rank fusion, a cross-encoder **reranker**, query rewriting from the event context, metadata filters (defect, booth type), and parent-document expansion. `app/tools/sop_search.py::search_sops` keeps its signature.
- **Citation check:** every SOP cited in a ticket is verified to exist and to contain the supporting text; unsupported citations are removed and flagged.
- **Corpus growth:** SOPs grow from 10 to ~40 synthetic documents (procedures, troubleshooting guides, past incident reports) so retrieval quality matters.
- **Knowledge graph:** entities and relations (booth –has→ equipment, batch –used_in→ booth, defect –addressed_by→ SOP, incident –involved→ booth) stored in Postgres; a `graph_lookup` tool for specialists; multi-hop questions answered by combining graph traversal with retrieval (GraphRAG).
- **Measured:** recall@k, MRR, and citation accuracy before and after each technique, in the evaluation suite.
- **UI:** a retrieval inspector (query → candidates → reranked → cited) and a graph explorer.

### Phase 10 — Agent memory, self-critique, dynamic planning  *(lab L10; lesson 10)*
Branch `v3/10-agent-memory`.
- **Long-term memory:** LangGraph `Store` (Postgres-backed) holding past investigations, reviewer decisions and revision notes, and per-booth "known issues". Specialists recall similar past cases with semantic search; `notify` writes a memory after each outcome.
- **Critic agent:** a new node between `synthesise` and `route_decision` that challenges the analysis (unsupported claims, missing checks) and can send it back once for another specialist round. It can lower confidence, never raise severity.
- **Dynamic supervisor:** `plan_investigation` may use the LLM to **add** specialists or a second round on top of the deterministic map (`app/graph/specialists/__init__.py::plan_for`); it can never remove one.
- **New specialist:** `history_agent` (recurrence patterns across booths and shifts), using the same `SpecialistSpec` pattern in `app/graph/specialists/base.py`.
- **Time travel:** API + UI to fork an investigation from any checkpoint with edited state and compare the two runs side by side.
- **Human edits:** the reviewer can edit the ticket draft directly at the interrupt, not just approve/reject/revise.
- Routing and ticket creation rules stay deterministic and human-gated.

### Phase 11 — Vision defect model  *(lab L11; lesson 11)*
Branch `v3/11-vision`.
- **Data:** a procedural generator (`vision/generate.py`) producing synthetic panel images for the 6 defect types plus "no defect", with labelled train/validation/test splits.
- **Model:** fine-tune a small pretrained CNN in PyTorch on the GPU; report accuracy, confusion matrix, and calibration; export to ONNX.
- **Serving:** a `vision` container (FastAPI + ONNX Runtime, CPU-capable) with `/classify` returning defect type, confidence, and a heatmap (Grad-CAM).
- **Integration:** events may arrive with an image instead of a label; a new `classify_defect` node runs before `intake`'s validation result is used; low-confidence classifications route to a human labelling queue.
- **UI:** image upload and a gallery on the control room, heatmap overlay in the investigation view. n8n simulator sends images.
- GPU is shared: vLLM is stopped while training (documented in the lesson).

### Phase 12 — Fine-tuning the local LLM  *(lab L12; lesson 12)*
Branch `v3/12-finetune`.
- **Dataset:** built from stored investigation traces and approved tickets (inputs → tool calls → findings), with a held-out test split and a data card.
- **Training:** QLoRA fine-tune of the Phase 5 model family on the RTX 5060 (`finetune/train.py`, PEFT + Transformers), in its own container. If 8 GB is not enough for the 3B model, fall back to the 1.5B model of the same family — verified in the first step.
- **Serving:** load the adapter in vLLM beside the base model (adapter support with the quantised base is verified first; fallback is merging the adapter and serving the merged model).
- **Comparison:** base vs fine-tuned on the Phase 8 evaluation suite (tool-call validity, finding validity, judge score, latency), reported as measured, in Langfuse and the README.
- **UI:** a model switch and an A/B comparison view for the same event.

### Phase 13 — Kubernetes  *(lab L13; lesson 13)*
Branch `v3/13-kubernetes`.
- Local cluster with **kind**; raw manifests first (Deployments, Services, ConfigMaps, Secrets, a StatefulSet for Postgres, a Job for `init`), then the same stack as a **Helm chart** in `deploy/helm/paintops/`.
- Liveness/readiness probes, resource requests and limits, an Ingress, a HorizontalPodAutoscaler on the API, rolling updates and a rollback exercise.
- Investigations move to a **worker Deployment** fed by a Postgres-backed job queue, so API pods and workers scale separately.
- Prometheus and Grafana scrape the cluster. vLLM stays outside the cluster on the host GPU (documented), reached by URL.

### Phase 14 — CI/CD and free public deployment  *(lab L14; lesson 14)*
Branch `v3/14-cicd-deploy`.
- **Pipeline (GitHub Actions):** lint, tests, web build, evaluation gate (demo mode), image build with cache, vulnerability scan, push to GitHub Container Registry, Helm lint; release tags produce versioned images.
- **Free deployment:** the public demo runs **without a GPU**: scripted demo model by default, CPU vision model, and optionally a free-tier hosted LLM through the same OpenAI-compatible client.
- **Host choice is made at the start of this phase**, after checking current free-tier terms (they change): the leading candidate is one always-free cloud VM running the Compose stack or k3s with the Helm chart; the alternative is free container hosting for API + UI with a free managed Postgres. I will present the verified options and you pick; you create the accounts.
- HTTPS, a public read-only demo mode with a reset job, rate limiting, and a secrets checklist.

### Phase 15 — Capstone
Branch `v3/15-capstone`.
- Full end-to-end "shift" scenario: simulator runs, images classified, agents investigate with memory and critique, reviewer acts, notifications sent, everything visible in traces and dashboards.
- Final README, architecture diagrams, `docs/learn/00-index.md` (the whole learning path), a 3-minute demo script and recorded demo, portfolio write-up. Tag `v3.0`.

---

## One chat per phase

You will start a **new chat for every phase**. A new chat remembers nothing from this one,
so everything it needs must be in the repo. On approval of this plan, and before any phase
work, I do this handoff setup in the current chat (branch `v2/plan-handoff`, one PR):

- `docs/MASTER_PLAN.md` — this plan, versioned with the code.
- `docs/PROGRESS.md` — the running log: per phase its status, PR link, what was built,
  decisions and deviations agreed, known gaps handed to later phases, and a
  **"Next phase: start here"** section (branch name, lab, first steps, risks to check first).
- `CLAUDE.md` in the repo root — short project instructions loaded automatically in every
  chat: read `docs/MASTER_PLAN.md` and `docs/PROGRESS.md` first, follow the plan strictly,
  build only the one phase asked for, how to run tests, open PRs through the browser pane,
  stop at the end of the phase.
- A project memory entry pointing at those files.

Then I stop. Each phase, in its own chat, goes like this:

- You open a new chat and say "start phase N".
- I read the plan and the progress log, check that `main` contains the previous phase,
  and confirm in one short message what this phase will build. **I do not start building
  until that check passes.**
- I build the phase, and its last commit updates `docs/PROGRESS.md` (status, what was
  built, the next phase's "start here" notes).
- I open the PR and **stop. I never continue into the next phase in the same chat**, even
  if asked to "keep going": I remind you to open a new chat instead.

## How each phase is delivered

1. Branch from `main`; build exactly the phase scope.
2. The basics lab for that phase is written and verified first.
3. Tests green; I run the result myself (pytest, browser from Phase 3, Docker from Phase 4).
4. Lesson note `docs/learn/NN-<topic>.md`: concept → where it lives in the repo → things to break → exercises. Every claim in a lesson is checked by actually doing it.
5. Push and open a PR through the signed-in browser pane. **No attribution lines** in commits or PRs.
6. Update `docs/PROGRESS.md` in the phase's final commit.
7. **Stop.** Summarise and end the chat's work. You merge the PR, then open a new chat for the next phase.

## Existing code reused

- `app/graph/specialists/base.py` (`SpecialistSpec`, `build_specialist_graph`) — pattern for every new agent (history agent, critic)
- `app/graph/routing.py` (`decide_route`, `approval_route`, `dispatch_specialists`) — deterministic policy stays the authority
- `app/services/llm.py::get_chat_model` — single place the model is chosen (demo, vLLM, fine-tuned, hosted free tier)
- `app/tools/sop_search.py`, `app/rag/index.py` — extended in Phase 9, same tool signature
- `app/database/repository.py` — `add_investigation_step`, `enqueue_notification`, idempotent ticket/event creation
- `app/database/seed.py` — the synthetic plant, extended with images and incident history
- `evaluation/` — grows into the suite used by Phases 8, 9, 12, and the CI gate

## Still out of scope

Real PLC/MES/ERP connections, user login and roles, a second plant, live MQTT streaming,
a 3D scene, Slack/Telegram/Discord, any paid service.

## Known risks, checked at the start of the phase concerned

- Phase 5: RTX 50-series GPU passthrough to the vLLM container.
- Phases 11–12: 8 GB VRAM is shared; training and serving run one at a time; model size may drop.
- Phase 12: LoRA adapter serving on a quantised base in vLLM.
- Phase 14: free-tier terms and capacity at the time.

## Verification

- `pytest` and the evaluation suite green after every phase; CI green on every PR.
- From Phase 4: clean clone + `docker compose up --build` gives a working stack.
- Each new phase has an end-to-end check in the browser: trace visible for a run (8), retrieval inspector shows reranked and cited chunks (9), a recalled past case and a critic send-back (10), an uploaded image classified and investigated (11), base vs fine-tuned comparison (12), `helm install` on kind then a rollback (13), a green pipeline and a reachable public URL (14), the full shift scenario (15).

# Lesson 01 — LangGraph: state, reducers, subgraphs, `Send`, interrupts

Phase 1 turned PaintOps from one straight pipeline into a small team of agents. A
supervisor decides which specialists look at a defect, the specialists work in
parallel, a synthesiser merges what they found, and a human approves, rejects, or
sends the ticket back for revision. This note explains the five LangGraph ideas
that make that work, shows where each one lives in this repo, and gives you
things to break and exercises to try.

Versions used: `langgraph` 1.2.18, `langchain-core` 1.7.3.

## Watch it run first

```bash
DATABASE_URL=sqlite:///./data/lesson01.db python docs/learn/examples/01_watch_run.py
```

On Windows PowerShell:

```powershell
$env:DATABASE_URL="sqlite:///./data/lesson01.db"; python docs/learn/examples/01_watch_run.py
```

Delete `data/lesson01.db` before running it again. You will see something like:

```
[parent] ['intake']
[parent] ['triage']
[parent] ['plan_investigation']
[environment_agent] ['agent']
[equipment_agent] ['agent']
[process_agent] ['agent']
[environment_agent] ['tools']
[equipment_agent] ['tools']
...
[parent] ['synthesise']
[parent] ['route_decision']
[parent] ['draft_ticket']
[parent] ['__interrupt__']
paused before: ('human_review',)
```

Each line is one node finishing. `[parent]` lines come from the main graph; the
others come from inside a specialist's own subgraph. Notice the three specialists'
lines are interleaved: they really are running at the same time. Keep this output
in mind while reading the rest.

## 1. State: one shared dictionary

**Concept.** A LangGraph graph passes a single state object from node to node. A
node receives the whole state and returns a dictionary of *only the keys it
changed*. LangGraph merges that return value into the state.

**In this repo.** [`PaintOpsState`](../../app/graph/state.py) is a `TypedDict` with
everything an investigation needs: the event, the recurrence count, the findings,
the analysis, the ticket draft, the reviewer's decision. Look at
[`triage`](../../app/graph/nodes.py): it returns just
`{"recent_events": ..., "recurrence_count": ...}`. It never copies the rest of
the state.

**Why it matters.** Small return values keep nodes independent. A node does not
have to know about keys it does not touch.

## 2. Reducers: what happens when two nodes write the same key

**Concept.** By default, writing a key replaces its old value. A *reducer* changes
that. You attach one with `Annotated[type, reducer_function]`, and LangGraph calls
`reducer_function(old_value, new_value)` instead of replacing.

**In this repo.** One key has a reducer:

```python
findings: Annotated[list[dict[str, Any]], operator.add]
```

([state.py](../../app/graph/state.py)). Each specialist returns
`{"findings": [its_finding]}`. With `operator.add`, those lists are concatenated,
so after the parallel step the state holds all three findings.

**Why it matters.** Without the reducer, three nodes writing `findings` in the same
step is ambiguous, and LangGraph refuses to guess (see "Break it" below).

The specialists' private state has another reducer you will meet everywhere:
`messages: Annotated[list[AnyMessage], add_messages]`
([specialists/base.py](../../app/graph/specialists/base.py)). `add_messages`
appends new chat messages and updates existing ones by id.

## 3. Subgraphs: an agent with its own private state

**Concept.** A compiled graph is itself runnable, so one graph can run inside
another. The inner graph (the *subgraph*) can have its own state keys that the
parent never sees.

**In this repo.** Every specialist is built by
[`build_specialist_graph`](../../app/graph/specialists/base.py):

```
START -> agent -> tools -> agent -> ... -> report -> END
```

- `agent` asks the chat model what to do. The model either requests a tool call
  or says it is done.
- `tools` runs the requested tools against the database and feeds the results
  back as `ToolMessage`s.
- `report` turns the tool results into one [`Finding`](../../app/schemas/finding.py).

Its state, `SpecialistState`, has `messages`, `tool_log` and `rounds`. None of
those exist in `PaintOpsState`. The parent only receives the `Finding`.

The three specialists differ only in their `SpecialistSpec`: their tools, their
demo script, and their `assess` rules. Compare
[environment.py](../../app/graph/specialists/environment.py),
[equipment.py](../../app/graph/specialists/equipment.py) and
[process.py](../../app/graph/specialists/process.py).

**Two ways to add a subgraph.** You can add the compiled subgraph directly as a node
(`graph.add_node("x", compiled_subgraph)`), or call it from inside an ordinary
node function. PaintOps uses the second way, in
[`make_specialist_node`](../../app/graph/nodes.py), for one reason: the wrapper
can catch an exception that survives the retries and turn it into an honest
`status="failed"` finding, so one broken specialist cannot sink the whole
investigation. Passing `config` through to `.invoke()` keeps it a real nested
subgraph. That is why its steps showed up in the streamed output above.

**The demo model.** In `DEMO_MODE` the "LLM" is
[`ScriptedChatModel`](../../app/services/llm.py), a real LangChain chat model that
plays back a fixed list of tool calls. The loop, the tool execution, the retries
and the streaming are all real; only the model's choices are pre-written. The
hypotheses come from the `assess` rules applied to the real tool results, which is
why the BOOTH-03 run finds the humidity drift planted by the seed data. Phase 5
swaps in a real model through vLLM.

**Retries.** The `agent` node is added with a `RetryPolicy`
([base.py](../../app/graph/specialists/base.py)). LangGraph's default retry rule
skips every `OSError`, and Python's built-in `TimeoutError` is one, so a timed-out
model call would not be retried. `_retry_model_errors` adds it back.

## 4. `Send`: fanning out to parallel workers

**Concept.** A normal edge goes from one node to a fixed next node. A conditional
edge can instead return a list of `Send(node_name, payload)` objects. Each `Send`
starts one task of that node with that payload as its input, and all of them run
in the same step, in parallel. When they finish, a normal edge from each of them to
one node collects the results (*fan-in*).

**In this repo.**

- [`plan_investigation`](../../app/graph/nodes.py) (the supervisor) looks up which
  specialists apply in
  [`DEFECT_SPECIALISTS`](../../app/graph/specialists/__init__.py) and stores the
  list in `specialists_planned`.
- [`dispatch_specialists`](../../app/graph/routing.py) is the conditional edge. It
  returns one `Send(f"{name}_agent", payload)` per planned specialist.
- In [builder.py](../../app/graph/builder.py), every specialist node has a normal
  edge to `synthesise`. LangGraph runs `synthesise` once, after all dispatched
  specialists finish.

The plan is a fixed map on purpose. Which specialists look at a defect is a
safety-relevant decision, so it stays in plain Python. A model may later be
allowed to *add* a specialist, never to remove one.

**Why `Send` and not three fixed edges?** Fixed edges would run all three
specialists for every defect. `Send` lets the supervisor choose how many tasks to
start, and what each one receives, at run time.

## 5. Interrupts: pausing for a human

**Concept.** Calling `interrupt(payload)` inside a node stops the graph and saves
its state through the checkpointer. Whoever is driving the graph sees the payload.
Later you resume the same thread with `graph.invoke(Command(resume=value), config)`.
The interrupted node then **runs again from the top**, and this time `interrupt()`
returns `value` instead of stopping.

**In this repo.** [`human_review`](../../app/graph/nodes.py) interrupts with the
ticket draft, the evidence, and `allowed_decisions`. On resume it reads
`{"decision", "reviewer", "comment"}` and routes through
[`approval_route`](../../app/graph/routing.py):

| Decision | Goes to |
|---|---|
| `approved` | `create_ticket`, then `notify` |
| `rejected` (or anything unrecognised) | `record_rejection`, then `notify` |
| `revise` | back to `draft_ticket`, then `human_review` again |
| `revise` after `MAX_REVISIONS` (2) | `human_review` again, without `revise` allowed |

The revise loop is a cycle in the graph: `draft_ticket -> human_review -> draft_ticket`.
Cycles are normal in LangGraph; what stops this one is the counter.

**The rule that follows from "runs again from the top".** Anything before
`interrupt()` in a node runs twice: once when it pauses and once when it resumes.
So nothing irreversible may happen before the interrupt. In `human_review` the
audit rows are written *after* `interrupt()` returns, and tickets are only ever
created in the separate `create_ticket` node.

## The whole graph

```
intake -> triage -> plan_investigation =Send=> environment_agent ┐
   |                                     =Send=> equipment_agent   ├─> synthesise -> route_decision
   └─> record_invalid                    =Send=> process_agent     ┘        |
                                                     record_observation <───┴───> draft_ticket <──┐
                                                                                      |           | revise
                                                                                human_review ─────┘
                                                                 approved |              | rejected
                                                                  create_ticket   record_rejection
                                                                          └──> notify <──┘
```

You can print the real thing at any time:

```bash
python -c "from app.graph.builder import build_graph; print(build_graph().get_graph().draw_mermaid())"
```

and paste the output into <https://mermaid.live>.

## Break it (and see what happens)

Run `python -m pytest tests/test_multi_agent.py -q` after each change, then undo it.

1. **Remove the reducer.** In [state.py](../../app/graph/state.py), change
   `findings: Annotated[list[dict[str, Any]], operator.add]` to
   `findings: list[dict[str, Any]]`. The fan-out tests fail with
   `InvalidUpdateError`: several nodes wrote `findings` in one step and LangGraph
   would not pick a winner.
2. **Starve the agents.** Set `MAX_TOOL_ROUNDS = 2` in
   [base.py](../../app/graph/specialists/base.py). Each specialist now gets one
   tool result instead of two. The environment specialist, with no baseline to
   compare against, reports its check as incomplete. Then try `1`: no tool runs
   at all, because `after_agent` checks the cap *before* the `tools` node, and
   every finding says which tools were not run. That is deliberate: a check that
   never ran must not read as "nothing found"
   (`test_a_tool_that_never_ran_is_reported_as_not_checked`).
3. **Do something irreversible too early.** In `human_review`, move one of the
   `_record(...)` calls above the `interrupt(...)` call. Run the example script,
   approve, and count the audit rows for `human_review`: the row appears twice,
   because the node ran once to pause and once to resume.
4. **Break a tool.** Make `telemetry_window` in
   [plant_context.py](../../app/tools/plant_context.py) raise an exception. The
   environment finding comes back `failed`, the other two still succeed, and the
   analysis names the missing check in `uncertainty`. This is what
   `test_failed_specialist_does_not_block_the_investigation` checks.

## Exercises

**1. Re-plan a defect.** Make `runs_sags` also send the environment specialist
(sagging can follow a temperature drop). Then write a test that proves it.

> Hint: it is a one-line change in `DEFECT_SPECIALISTS`. Copy
> `test_fan_out_runs_only_the_mapped_specialists` and add a parameter row.

**2. Give the process specialist a line-wide view.** Add a tool
`get_line_batches(production_line)` that lists the active batch in every booth on
the line, and use it in `assess` to say "this batch is also running in BOOTH-0X".

> Hint: add the query to [plant_context.py](../../app/tools/plant_context.py)
> (`booth_line` and `LINES` in [seed.py](../../app/database/seed.py) know which
> booths share a line), add a `@tool` in `make_tools`, append a step to
> `demo_script`, and read it in `assess` via `results["get_line_batches"]`.
> Watch `MAX_TOOL_ROUNDS`: three tools need three rounds plus the final turn.

**3. Ask for a reason on rejection.** Change `human_review` so that rejecting
without a comment interrupts *again*, asking for one, before the rejection is
recorded.

> Hint: a node may call `interrupt()` more than once. On resume LangGraph matches
> resume values to `interrupt()` calls in order, so the second call needs a second
> `Command(resume=...)`. Think about what "runs again from the top" means for the
> first call.

## Where this goes next

Phase 2 makes runs asynchronous and streams these same updates to the browser
over Server-Sent Events, which is what the live workflow view in the UI will draw.

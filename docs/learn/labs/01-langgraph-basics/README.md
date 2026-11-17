# Lab L1 — LangGraph basics (catch-up)

Time: about 30 minutes. Nothing here uses PaintOps code. Do this before reading
lesson 02 if LangGraph still feels like magic.

Run it from the repo root:

```bash
.venv/Scripts/python.exe docs/learn/labs/01-langgraph-basics/graph_basics.py
```

Expected output:

```text
kitchen -> {'reading': 17.0, 'action': 'heater on'}
attic -> {'reading': 26.3, 'action': 'fan on'}
saved kitchen state: {'reading': 17.0, 'action': 'heater on'}
attic checkpoints: 4 next nodes: [(), ('cool',), ('measure',), ('__start__',)]
```

## The six ideas in `graph_basics.py`

1. **State** is a `TypedDict`. It is the only thing nodes share. `total=False` means a
   key may be missing until a node writes it.
2. **A node** is a plain function `state -> dict`. It returns only the keys it changed;
   LangGraph merges them into the state. (`measure` returns just `reading`.)
3. **A router** is a function `state -> str`. It does not change the state; it names
   the branch to take next.
4. **A normal edge** (`add_edge(A, B)`) always runs B after A. `START` and `END` are the
   graph's built-in entry and exit.
5. **A conditional edge** (`add_conditional_edges(A, router, [...])`) calls the router
   after A and runs whichever node it names.
6. **A checkpointer** saves the state after every step, keyed by `thread_id`. That is
   why `get_state` can read back the kitchen run, and why the attic run has 4
   checkpoints: input, after `measure`, after `cool`, and the end (`next == ()`).

`compile()` checks the wiring (for example, a missing node name fails here, not at run
time) and returns a runnable app with `invoke`, `stream`, `get_state`, and more.

## Watching a graph run step by step

`invoke` only returns the end state. `stream` yields one item per step. Try this in a
Python shell started in this folder:

```python
from graph_basics import app
cfg = {"configurable": {"thread_id": "garage"}}
for update in app.stream({"reading": 21}, cfg, stream_mode="updates"):
    print(update)
# {'measure': {'reading': 21}}
# {'wait': {'action': 'nothing to do'}}
```

`stream_mode="updates"` gives `{node_name: what_it_returned}` per step. Phase 2 streams a
real graph like this, live, to a web page.

## Exercises

1. Add a `"dehumidify"` branch taken when the reading is between 22 and 23. You need a
   node, a change to `decide`, and the branch name in the list.
2. Run the kitchen thread a second time with `{"reading": 25}`. What does
   `get_state_history` now return for `kitchen`? (Hint: a thread keeps every run.)
3. Remove `checkpointer=MemorySaver()` and run again. Which line fails, and why?

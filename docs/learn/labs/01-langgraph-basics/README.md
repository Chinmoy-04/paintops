# Lab L1: LangGraph basics

**Time:** about 30 minutes. **Needs:** only Python. Nothing here uses PaintOps code.

Do this before lesson 02 if LangGraph still feels like magic. By the end you will know
the six words the rest of the project uses: **state, node, router, edge, compile,
checkpointer**.

## The idea in one paragraph

A LangGraph app is a **flowchart that runs**. You draw boxes (nodes) and arrows
(edges). When you run it, LangGraph walks the arrows from `START` to `END` and calls
each box's function along the way. All the boxes read and write one shared notepad
(the state). PaintOps's investigation is the same thing, just with more boxes.

The example is a thermostat:

```text
               START
                 |
              measure          read the temperature
            /    |    \
         heat   wait   cool    pick ONE of these
            \    |    /
                END
```

- Below 19 degrees, it runs `heat`.
- Above 23 degrees, it runs `cool`.
- Anything else, it runs `wait`.

## Step 1: run it

From the repo root:

```bash
.venv/Scripts/python.exe docs/learn/labs/01-langgraph-basics/graph_basics.py
```

You should see four sections. Lines starting with `[...]` are printed by the nodes
themselves, so you can watch which box is running.

```text
=== 1. invoke(): run the whole graph, get the final state ===
    [measure] the reading is 17.0
    [heat] too cold
final state: {'reading': 17.0, 'action': 'heater on'}

=== 2. stream(): run the graph, get one update per node as it finishes ===
    [measure] the reading is 26.3
update: {'measure': {'reading': 26.3}}
    [cool] too hot
update: {'cool': {'action': 'fan on'}}

=== 3. get_state(): read a thread's saved state back later ===
kitchen: {'reading': 17.0, 'action': 'heater on'}

=== 4. get_state_history(): every saved checkpoint, newest first ===
state: {'reading': 26.3, 'action': 'fan on'} | runs next: ()
state: {'reading': 26.3} | runs next: ('cool',)
state: {'reading': 26.3} | runs next: ('measure',)
state: {} | runs next: ('__start__',)
```

## Step 2: what each section shows

1. **`invoke`** runs the whole flowchart and hands you the notepad at the end. 17.04
   is below 19, so it went `measure` → `heat`.
2. **`stream`** runs the same way but tells you after **each** node what that node
   changed: `{node name: what it returned}`. This is the key idea for Phase 2. PaintOps
   sends exactly these updates to the web page so you can watch an investigation live.
3. **`get_state`** reads the kitchen's notepad back *after* the run finished. That
   works because the checkpointer saved it.
4. **`get_state_history`** lists every save the checkpointer made for the attic,
   newest first. Read it bottom to top. It shows the empty start, then the state
   before `measure`, then the state before `cool`, then the finished state. `runs
   next: ()` means "nothing left to run".

## Step 3: the six ideas, in the code

Open `graph_basics.py`. The comments are numbered to match this list.

| # | Idea | In plain words | In the code |
|---|---|---|---|
| 1 | **State** | The shared notepad. A `TypedDict` listing its keys. | `class State` |
| 2 | **Node** | A function that gets the notepad and returns **only the keys it changed**. LangGraph writes them in. | `measure`, `heat`, `cool`, `wait` |
| 3 | **Router** | A function that looks at the notepad and returns the **name** of the next node. It changes nothing. | `decide` |
| 4 | **Edge** | An arrow. A normal edge always goes A → B. A conditional edge asks a router where to go. | `add_edge`, `add_conditional_edges` |
| 5 | **Compile** | Checks the wiring (a misspelt node name fails here, not later) and gives you the runnable `app`. | `graph.compile(...)` |
| 6 | **Checkpointer** | Saves the notepad after every node, under a `thread_id`. Each thread is a separate job with its own history. | `MemorySaver()` |

`MemorySaver` keeps the saves in memory, so they are lost when the script ends.
PaintOps uses a SQLite checkpointer instead, which writes them to a file.

## Exercises

Try each one, then open the hint if you get stuck.

**1. Add a fourth branch.** When the reading is between 22 and 23, run a new
`dehumidify` node that sets `action` to `"dehumidifier on"`.

<details><summary>Hint</summary>

You need three changes. Write a `dehumidify` function and register it with
`add_node`. Add an `if` to `decide` **before** the final `return "wait"`. Put
`"dehumidify"` in the list passed to `add_conditional_edges`. Also add an edge from
`dehumidify` to `END`.
</details>

**2. Run the same thread twice.** After the kitchen run, call `app.invoke` again
with `{"reading": 25}` and the same `kitchen` config. Then print
`get_state_history(kitchen)`. How many checkpoints are there now?

<details><summary>Hint</summary>

A thread keeps every run, so you see both runs' checkpoints, newest first. This is how
PaintOps can pause an investigation for human review and continue it later. The
history is still there.
</details>

**3. Remove the checkpointer.** Change the line to `app = graph.compile()` and run
the script. Which section fails, and why?

<details><summary>Hint</summary>

Sections 1 and 2 still work: running a graph needs no saving. Section 3 fails with
`ValueError: No checkpointer set`, because there is nothing to read back.
</details>

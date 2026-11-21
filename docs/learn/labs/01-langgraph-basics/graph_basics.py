"""Lab L1: the smallest useful LangGraph.

The story: a thermostat. It reads the temperature, then picks ONE of three actions.

    too cold (below 19)  ->  turn the heater on
    too hot  (above 23)  ->  turn the fan on
    anything else        ->  do nothing

Drawn as a graph:

               START
                 |
              measure
            /    |    \\
         heat   wait   cool
            \\    |    /
                END

Run it from the repo root:

    .venv/Scripts/python.exe docs/learn/labs/01-langgraph-basics/graph_basics.py
"""

from typing import TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph


# STEP 1. The STATE: the one shared notepad every node reads from and writes to.
#         `total=False` means a key can be missing until some node writes it
#         (`action` is empty until heat, cool or wait runs).
class State(TypedDict, total=False):
    reading: float  # the temperature
    action: str  # what the thermostat decided to do


# STEP 2. NODES: plain functions. Each one gets the state and returns ONLY the keys it
#         wants to change. LangGraph copies those keys into the state for you.
def measure(state: State) -> dict:
    reading = round(state["reading"], 1)
    print(f"    [measure] the reading is {reading}")
    return {"reading": reading}


def heat(state: State) -> dict:
    print("    [heat] too cold")
    return {"action": "heater on"}


def cool(state: State) -> dict:
    print("    [cool] too hot")
    return {"action": "fan on"}


def wait(state: State) -> dict:
    print("    [wait] just right")
    return {"action": "nothing to do"}


# STEP 3. A ROUTER: looks at the state and returns the NAME of the node to run next.
#         It never changes the state.
def decide(state: State) -> str:
    if state["reading"] < 19:
        return "heat"
    if state["reading"] > 23:
        return "cool"
    return "wait"


# STEP 4. Build the graph: register the nodes, then connect them with edges.
graph = StateGraph(State)
graph.add_node("measure", measure)
graph.add_node("heat", heat)
graph.add_node("cool", cool)
graph.add_node("wait", wait)

# A NORMAL EDGE always goes from A to B. START and END are built in.
graph.add_edge(START, "measure")

# A CONDITIONAL EDGE: after `measure`, call `decide` and go wherever it says.
# The list names every node `decide` is allowed to pick.
graph.add_conditional_edges("measure", decide, ["heat", "cool", "wait"])

graph.add_edge("heat", END)
graph.add_edge("cool", END)
graph.add_edge("wait", END)

# STEP 5. COMPILE: check the wiring and get back a runnable app.
# STEP 6. The CHECKPOINTER saves the state after every step. Each conversation or job
#         gets its own `thread_id`, so the saved states never mix.
app = graph.compile(checkpointer=MemorySaver())


def heading(text: str) -> None:
    print(f"\n=== {text} ===")


if __name__ == "__main__":
    kitchen = {"configurable": {"thread_id": "kitchen"}}
    attic = {"configurable": {"thread_id": "attic"}}

    heading("1. invoke(): run the whole graph, get the final state")
    final = app.invoke({"reading": 17.04}, kitchen)
    print("final state:", final)

    heading("2. stream(): run the graph, get one update per node as it finishes")
    for update in app.stream({"reading": 26.3}, attic, stream_mode="updates"):
        print("update:", update)

    heading("3. get_state(): read a thread's saved state back later")
    print("kitchen:", app.get_state(kitchen).values)

    heading("4. get_state_history(): every saved checkpoint, newest first")
    for snapshot in app.get_state_history(attic):
        print("state:", snapshot.values, "| runs next:", snapshot.next)

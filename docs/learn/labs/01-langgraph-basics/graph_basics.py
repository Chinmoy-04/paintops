"""L1: the smallest useful LangGraph. A thermostat that decides to heat, cool, or wait.

Run:  python graph_basics.py
"""

from typing import TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph


class State(TypedDict, total=False):  # 1. state: the data every node can read
    reading: float
    action: str


def measure(state: State) -> dict:  # 2. a node: read state, return only what changed
    return {"reading": round(state["reading"], 1)}


def decide(state: State) -> str:  # 3. a router: returns the NAME of the next branch
    return "heat" if state["reading"] < 19 else "cool" if state["reading"] > 23 else "wait"


graph = StateGraph(State)
graph.add_node("measure", measure)
graph.add_node("heat", lambda s: {"action": "heater on"})
graph.add_node("cool", lambda s: {"action": "fan on"})
graph.add_node("wait", lambda s: {"action": "nothing to do"})
graph.add_edge(START, "measure")  # 4. a normal edge: always go from A to B
graph.add_conditional_edges("measure", decide, ["heat", "cool", "wait"])  # 5. a conditional edge
for name in ("heat", "cool", "wait"):
    graph.add_edge(name, END)
app = graph.compile(checkpointer=MemorySaver())  # 6. a checkpointer: saves state per thread

if __name__ == "__main__":
    for thread, temp in [("kitchen", 17.04), ("attic", 26.3)]:
        config = {"configurable": {"thread_id": thread}}
        print(thread, "->", app.invoke({"reading": temp}, config))
    # The checkpointer remembers each thread's last state; read it back by thread id.
    print("saved kitchen state:", app.get_state({"configurable": {"thread_id": "kitchen"}}).values)
    # The history lists every checkpoint, newest first: one per step of the run.
    history = list(app.get_state_history({"configurable": {"thread_id": "attic"}}))
    print("attic checkpoints:", len(history), "next nodes:", [h.next for h in history])

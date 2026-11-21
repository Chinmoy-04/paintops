"""Lab L2, part 2: a Server-Sent Events (SSE) endpoint in FastAPI.

SSE = an HTTP response that stays open and sends one small message at a time.

Run it from the repo root (terminal 1):
    .venv/Scripts/python.exe -m uvicorn sse_app:app --app-dir docs/learn/labs/02-async-streaming --port 8765
Read it (terminal 2):
    curl -N "http://127.0.0.1:8765/countdown?start=3"
"""

import asyncio
from collections.abc import AsyncIterable

from fastapi import FastAPI
from fastapi.sse import EventSourceResponse, ServerSentEvent

app = FastAPI()


# `response_class=EventSourceResponse` tells FastAPI: this route is a stream.
# The function is an async GENERATOR: every `yield` is sent to the client at once as
# one event, and the response stays open until the function ends.
@app.get("/countdown", response_class=EventSourceResponse)
async def countdown(start: int = 5) -> AsyncIterable[ServerSentEvent]:
    for n in range(start, 0, -1):
        # event = a name for this kind of message, data = the payload,
        # id = a position number (used to resume after a dropped connection).
        yield ServerSentEvent(event="tick", data={"n": n}, id=str(n))
        await asyncio.sleep(1)  # pause without blocking the server
    yield ServerSentEvent(event="done", data={"message": "lift-off"})


# A normal endpoint. It still answers instantly while a countdown is streaming,
# because the countdown only `await`s and never blocks the event loop.
@app.get("/now")
async def now() -> dict:
    return {"ok": True}

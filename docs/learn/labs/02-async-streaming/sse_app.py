"""L2 part 2: a Server-Sent Events (SSE) endpoint in FastAPI.

Run:   python -m uvicorn sse_app:app --port 8765
Read:  curl -N http://127.0.0.1:8765/countdown?start=5
"""

import asyncio
from collections.abc import AsyncIterable

from fastapi import FastAPI
from fastapi.sse import EventSourceResponse, ServerSentEvent

app = FastAPI()


@app.get("/countdown", response_class=EventSourceResponse)
async def countdown(start: int = 5) -> AsyncIterable[ServerSentEvent]:
    # An async generator: each `yield` is sent to the client immediately as one event.
    # The HTTP response stays open until the generator returns.
    for n in range(start, 0, -1):
        yield ServerSentEvent(data={"n": n}, event="tick", id=str(n))
        await asyncio.sleep(1)
    yield ServerSentEvent(data={"message": "lift-off"}, event="done")


@app.get("/now")
async def now() -> dict:
    # A normal endpoint. It still answers while /countdown streams, because the
    # countdown awaits (sleeps without blocking the event loop).
    return {"ok": True}

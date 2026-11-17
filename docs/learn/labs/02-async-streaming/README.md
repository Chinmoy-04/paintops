# Lab L2 — async/await and Server-Sent Events

Time: about 45 minutes. Nothing here uses PaintOps code.

## Part 1 — async/await (`async_basics.py`)

```bash
cd docs/learn/labs/02-async-streaming
../../../../.venv/Scripts/python.exe async_basics.py
```

Expected output:

```text
sequential: 3.0s
gather:     1.0s ['a done', 'b done', 'c done']
task started, doing other work...
task result: background done
consumer got item 0
consumer got item 1
consumer got item 2
```

The ideas:

- `async def` makes a **coroutine**. Calling it does nothing yet; `await` runs it.
- One thread runs an **event loop**. At every `await` on something slow (a sleep, a
  socket), the loop switches to another coroutine that is ready. That is why three
  1-second waits take 1 second with `asyncio.gather`.
- Blocking calls (`time.sleep`, a slow synchronous database query) do **not** hand
  control back: they freeze every coroutine. Run them in a thread instead
  (`await asyncio.to_thread(fn)`).
- `asyncio.create_task(coro)` starts a coroutine in the background and returns a
  `Task` you can await later (or cancel).
- `asyncio.Queue` passes items from a producer to a consumer as they appear. A `None`
  sentinel says "finished".

## Part 2 — an SSE endpoint (`sse_app.py`)

**Server-Sent Events** is a plain HTTP response that never closes until the server is
done. The body is text in this shape, one blank line between events:

```text
event: tick
data: {"n": 3}
id: 3
```

The browser reads it with `new EventSource(url)`; if the connection drops, the browser
reconnects and sends the last `id` it saw in a `Last-Event-ID` header, so the server
can continue where it stopped. SSE is one-way (server → client), which is all a live
progress view needs. WebSockets are two-way and more work.

FastAPI has SSE built in: give the route `response_class=EventSourceResponse` and make
it an async generator that `yield`s `ServerSentEvent(...)`. FastAPI also sends a
keep-alive comment when the generator is quiet for a while, so proxies don't cut the
connection.

Start the server (terminal 1):

```bash
cd docs/learn/labs/02-async-streaming
../../../../.venv/Scripts/python.exe -m uvicorn sse_app:app --port 8765
```

Read the stream (terminal 2). `-N` turns off curl's buffering so each event prints as
it arrives, one per second:

```bash
curl -N "http://127.0.0.1:8765/countdown?start=3"
```

While it counts, call the normal endpoint from a third terminal. It answers at once,
because the countdown only `await`s:

```bash
curl http://127.0.0.1:8765/now
```

Look at the headers too: `curl -si "http://127.0.0.1:8765/countdown?start=1"` shows
`content-type: text/event-stream`.

## Exercises

1. Replace `await asyncio.sleep(1)` with `time.sleep(1)` (import `time`). Start a
   countdown and call `/now` during it. What happens, and why?
2. Add a `/numbers` stream that reads from an `asyncio.Queue` filled by a background
   task started in the route. Stop when the producer puts `None`.
3. Open `http://127.0.0.1:8765/docs` and the browser dev tools console, then run
   `const es = new EventSource("/countdown?start=3"); es.addEventListener("tick", e => console.log(e.data))`.
   Why does the browser start the countdown again after `done`? (Hint: the stream
   closed, and `EventSource` always reconnects. Call `es.close()` on `done`.)

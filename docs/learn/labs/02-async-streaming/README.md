# Lab L2: async/await and Server-Sent Events

**Time:** about 45 minutes. **Needs:** Python and `curl`. Nothing here uses PaintOps
code.

## Why this lab exists

A PaintOps investigation takes a few seconds and runs many steps. Phase 2 makes two
things possible:

1. **The server stays responsive while an investigation runs.** That needs
   `async`/`await` (part 1).
2. **A web page watches the steps arrive live**, instead of waiting for the end. That
   needs Server-Sent Events, or SSE (part 2).

## Part 1: async/await (`async_basics.py`)

### The picture: one cook in a kitchen

Python's async code runs on **one** thread, like a kitchen with **one** cook. Boiling
a kettle takes a while, but a good cook does not stand and stare at it. They start the
kettle, chop vegetables, and come back when it whistles.

- **`async def`** writes a recipe that is allowed to pause. (Python calls it a
  *coroutine*.)
- **`await`** is the cook saying "this will take a while, I'll do something else until
  it's ready". It only helps when the slow thing is waiting: a timer, a network call,
  a database reply.
- The **event loop** is the cook's attention. It jumps to whichever recipe is ready to
  continue. `asyncio.run(main())` starts it.

### Run it

```bash
.venv/Scripts/python.exe docs/learn/labs/02-async-streaming/async_basics.py
```

```text
=== 1. await one at a time: 3 kettles x 1 s ===
took 3.0s

=== 2. asyncio.gather: start all 3, wait for all 3 ===
took 1.0s, results: ['a done', 'b done', 'c done']

=== 3. asyncio.create_task: start it now, collect the result later ===
task started, the cook is free to do other work...
result: background kettle done

=== 4. asyncio.Queue: one coroutine hands items to another ===
producer put item 0
consumer got item 0
producer put item 1
consumer got item 1
producer put item 2
consumer got item 2
```

### What each demo shows

1. **`await` in a loop:** each kettle is waited for before the next starts, so the
   total is 1 + 1 + 1 = 3 seconds.
2. **`asyncio.gather`:** all three start together and wait *at the same time*, so the
   total is just 1 second. Same work, a third of the time.
3. **`asyncio.create_task`:** starts work in the background and gives you a `Task` to
   collect later with `await task`. PaintOps starts each investigation this way, which
   is why `POST /api/events` can answer `202` straight away.
4. **`asyncio.Queue`:** a conveyor belt between two coroutines. The producer puts
   items on, and the consumer takes each one off as soon as it arrives. `None` is the
   "that's everything" signal. PaintOps uses a queue to hand each new step to every
   open stream.

**The one trap:** `time.sleep()` or any slow *non-async* call does not pause politely.
It freezes the cook, so **every** coroutine stops. Use `await asyncio.sleep()`, or
push the slow call to another thread with `await asyncio.to_thread(slow_function)`.

## Part 2: Server-Sent Events (`sse_app.py`)

### The picture: a live ticker

A normal HTTP request is a letter: ask once, get one reply, done. SSE is a **live
ticker**. The client asks once, the server keeps the line open and sends small
messages whenever it has news, and finally the server closes the line.

Each message is plain text. A blank line separates one message from the next:

```text
event: tick          <- what kind of message
data: {"n": 3}       <- the content (often JSON)
id: 3                <- a position number
```

The `id` matters when the connection drops. A browser reconnects by itself and sends
the last id it saw (the `Last-Event-ID` header), so the server can continue from there
instead of starting over. SSE only goes one way, server → client, which is all a live
progress view needs.

In FastAPI, a stream is an `async def` that `yield`s `ServerSentEvent(...)` objects,
with `response_class=EventSourceResponse` on the route. Each `yield` is sent
immediately. Open `sse_app.py`: it is about 20 lines.

### Run it

You need two terminals, both in the repo root.

**Terminal 1** starts the server:

```bash
.venv/Scripts/python.exe -m uvicorn sse_app:app --app-dir docs/learn/labs/02-async-streaming --port 8765
```

**Terminal 2** reads the stream. `-N` tells curl to print each message as it arrives
instead of saving them up:

```bash
curl -N "http://127.0.0.1:8765/countdown?start=3"
```

One message arrives per second:

```text
event: tick
data: {"n": 3}
id: 3

event: tick
data: {"n": 2}
id: 2

event: tick
data: {"n": 1}
id: 1

event: done
data: {"message": "lift-off"}
```

Now start another countdown, and while it runs, call the normal endpoint from a third
terminal:

```bash
curl http://127.0.0.1:8765/now
```

It answers at once, because the countdown only `await`s and never freezes the cook.

Stop the server with `Ctrl+C` in terminal 1.

## Exercises

Try each one, then open the hint if you get stuck.

**1. Freeze the cook.** In `sse_app.py`, replace `await asyncio.sleep(1)` with
`time.sleep(1)` (and add `import time`). Restart the server, start a countdown, and
call `/now` during it. What happens?

<details><summary>Hint</summary>

`/now` hangs until the countdown is over. `time.sleep` blocks the one thread the
event loop runs on, so no other request can be served. This is why PaintOps runs its
slow database calls with `asyncio.to_thread`.
</details>

**2. Stream from a queue.** Add a `/numbers` stream. Inside the route, create an
`asyncio.Queue`, start a background task that puts 1, 2, 3 on it (one every half
second) and then `None`, and `yield` one event per item until you get `None`.

<details><summary>Hint</summary>

Combine demo 3 and demo 4 from part 1: `asyncio.create_task(producer())`, then
`while (item := await queue.get()) is not None: yield ServerSentEvent(data={"n": item})`.
This is the same shape as a PaintOps investigation stream.
</details>

**3. Watch it in a browser.** With the server running, open
`http://127.0.0.1:8765/docs`, open the browser's developer console (F12), and paste:

```js
const es = new EventSource("/countdown?start=3");
es.addEventListener("tick", (e) => console.log(e.data));
```

Watch for a while. Why does the countdown start again after it finishes?

<details><summary>Hint</summary>

When the server closes the stream, `EventSource` assumes the connection dropped and
reconnects. To stop, listen for `done` and close it:
`es.addEventListener("done", () => es.close())`. The PaintOps web page (Phase 3) does
the same with its `end` event.
</details>

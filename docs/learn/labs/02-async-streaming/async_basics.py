"""L2 part 1: async/await in 30 lines. Three slow "downloads", sequential vs concurrent.

Run:  python async_basics.py
"""

import asyncio
import time


async def download(name: str, seconds: float) -> str:
    # `await` hands control back to the event loop while we wait, so other
    # coroutines can run. time.sleep() here would block every one of them.
    await asyncio.sleep(seconds)
    return f"{name} done"


async def main() -> None:
    jobs = [("a", 1.0), ("b", 1.0), ("c", 1.0)]

    start = time.perf_counter()
    for name, s in jobs:
        await download(name, s)  # one after another
    print(f"sequential: {time.perf_counter() - start:.1f}s")

    start = time.perf_counter()
    results = await asyncio.gather(*(download(n, s) for n, s in jobs))  # all at once
    print(f"gather:     {time.perf_counter() - start:.1f}s", results)

    # A Task starts running in the background right away; you can await it later.
    task = asyncio.create_task(download("background", 0.5))
    print("task started, doing other work...")
    print("task result:", await task)

    # A Queue lets one coroutine hand items to another as they are produced.
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def producer() -> None:
        for i in range(3):
            await asyncio.sleep(0.2)
            await queue.put(f"item {i}")
        await queue.put(None)  # a sentinel: "no more items"

    asyncio.create_task(producer())
    while (item := await queue.get()) is not None:
        print("consumer got", item)


if __name__ == "__main__":
    asyncio.run(main())

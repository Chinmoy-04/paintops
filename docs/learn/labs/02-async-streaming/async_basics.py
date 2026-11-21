"""Lab L2, part 1: async/await, in four small demos.

Think of one cook in a kitchen. Boiling a kettle takes a while, but the cook does not
stand and stare at it: they start it, then go and do something else. `await` is the
cook saying "this will take a while, go do something else until it is ready".

Run it from the repo root:

    .venv/Scripts/python.exe docs/learn/labs/02-async-streaming/async_basics.py
"""

import asyncio
import time


# `async def` makes a COROUTINE: a function that is allowed to pause.
async def boil(name: str, seconds: float) -> str:
    # `await asyncio.sleep` pauses THIS coroutine and lets the others run meanwhile.
    # (A plain `time.sleep` would freeze everything; see the README's exercise 1.)
    await asyncio.sleep(seconds)
    return f"{name} done"


async def demo_1_one_after_another() -> None:
    print("\n=== 1. await one at a time: 3 kettles x 1 s ===")
    start = time.perf_counter()
    for name in ["a", "b", "c"]:
        await boil(name, 1.0)  # wait for this one to finish before starting the next
    print(f"took {time.perf_counter() - start:.1f}s")


async def demo_2_all_at_once() -> None:
    print("\n=== 2. asyncio.gather: start all 3, wait for all 3 ===")
    start = time.perf_counter()
    results = await asyncio.gather(boil("a", 1.0), boil("b", 1.0), boil("c", 1.0))
    print(f"took {time.perf_counter() - start:.1f}s, results: {results}")


async def demo_3_background_task() -> None:
    print("\n=== 3. asyncio.create_task: start it now, collect the result later ===")
    task = asyncio.create_task(boil("background kettle", 0.5))  # starts running now
    print("task started, the cook is free to do other work...")
    print("result:", await task)  # now wait for it


async def demo_4_queue() -> None:
    print("\n=== 4. asyncio.Queue: one coroutine hands items to another ===")
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def producer() -> None:
        for i in range(3):
            await asyncio.sleep(0.2)
            print(f"producer put item {i}")
            await queue.put(f"item {i}")
        await queue.put(None)  # None means "no more items"

    asyncio.create_task(producer())
    while True:
        item = await queue.get()  # waits here until something is in the queue
        if item is None:
            break
        print(f"consumer got {item}")


async def main() -> None:
    await demo_1_one_after_another()
    await demo_2_all_at_once()
    await demo_3_background_task()
    await demo_4_queue()


if __name__ == "__main__":
    asyncio.run(main())  # start the event loop and run main() on it

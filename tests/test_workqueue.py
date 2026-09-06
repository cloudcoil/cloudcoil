import asyncio

import pytest

from cloudcoil.controller import QueueClosed, WorkQueue


async def test_coalescing_fairness_and_dirty_during_processing():
    queue = WorkQueue[str]()
    for _ in range(100):
        queue.add("a")
    queue.add("b")
    assert await queue.get() == "a"
    for _ in range(100):
        queue.add("a")
    assert await queue.get() == "b"
    waiter = asyncio.create_task(queue.get())
    await asyncio.sleep(0)
    assert not waiter.done()  # a cannot run concurrently with itself
    queue.done("a")
    assert await waiter == "a"
    queue.done("b")
    queue.done("a")
    await queue.join()


async def test_delayed_coalescing_and_earliest_deadline():
    queue = WorkQueue[str]()
    queue.add_after("a", 60)
    queue.add_after("a", 0.01)
    queue.add_after("a", 60)
    async with asyncio.timeout(1):
        assert await queue.get() == "a"
    queue.done("a")
    await queue.join()
    assert not queue._delayed


async def test_fresh_event_cancels_timer_and_does_not_duplicate_work():
    queue = WorkQueue[str]()
    queue.add_after("a", 0.01)
    queue.add("a")
    assert await queue.get() == "a"
    queue.done("a")
    await asyncio.sleep(0.02)
    queue.shutdown()
    with pytest.raises(QueueClosed):
        await queue.get()
    await queue.join()


async def test_retry_cap_forget_and_successful_join():
    queue = WorkQueue[str](base_delay=0.001, max_delay=0.004, jitter=0)
    assert [queue.retry("a") for _ in range(5)] == [0.001, 0.002, 0.004, 0.004, 0.004]
    assert queue.num_retries("a") == 5
    queue.forget("a")
    assert queue.num_retries("a") == 0
    queue._retries["a"] = 1_000_000
    assert queue.retry("a") == 0.004
    assert await queue.get() == "a"
    queue.done("a")
    await queue.join()


async def test_delayed_retry_never_hides_an_update():
    queue = WorkQueue[str]()
    queue.add("a")
    await queue.get()
    queue.add("a")
    queue.retry("a")
    queue.done("a")
    assert await queue.get() == "a"
    assert not queue._delayed
    queue.forget("a")
    queue.done("a")
    await queue.join()


async def test_cancelled_get_does_not_consume_or_lock_a_key():
    queue = WorkQueue[str]()
    waiter = asyncio.create_task(queue.get())
    await asyncio.sleep(0)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    queue.add("a")
    assert await queue.get() == "a"
    queue.done("a")
    await queue.join()


@pytest.mark.parametrize("immediate", [False, True])
async def test_shutdown_drops_timers_and_drains_or_discards(immediate):
    queue = WorkQueue[str]()
    queue.add("a")
    await queue.get()
    queue.add("a")
    queue.add("b")
    queue.add_after("later", 60)
    queue.shutdown(immediate=immediate)
    queue.add("ignored")
    queue.done("a")
    if not immediate:
        assert await queue.get() == "b"
        queue.done("b")
        assert await queue.get() == "a"
        queue.done("a")
    with pytest.raises(QueueClosed):
        await queue.get()
    await queue.join()
    assert not queue._delayed
    assert queue.retry("ignored") == 0


async def test_shutdown_wakes_all_waiters():
    queue = WorkQueue[str]()
    waiters = [asyncio.create_task(queue.get()) for _ in range(5)]
    await asyncio.sleep(0)
    queue.shutdown()
    results = await asyncio.gather(*waiters, return_exceptions=True)
    assert all(isinstance(result, QueueClosed) for result in results)


async def test_workers_never_process_the_same_key_concurrently():
    queue = WorkQueue[int]()
    processing = set()
    processed = set()

    async def worker():
        while True:
            try:
                key = await queue.get()
            except QueueClosed:
                return
            try:
                assert key not in processing
                processing.add(key)
                await asyncio.sleep(0)
                processed.add(key)
                processing.remove(key)
            finally:
                queue.done(key)

    tasks = [asyncio.create_task(worker()) for _ in range(8)]
    for _ in range(10):
        for key in range(50):
            queue.add(key)
        await asyncio.sleep(0)
    await queue.join()
    queue.shutdown()
    await asyncio.gather(*tasks)
    assert processed == set(range(50))


@pytest.mark.parametrize(
    "kwargs", [{"base_delay": 0}, {"max_delay": 0.5}, {"jitter": 2}, {"base_delay": float("nan")}]
)
def test_invalid_retry_settings(kwargs):
    with pytest.raises(ValueError):
        WorkQueue(**kwargs)


async def test_invalid_done_and_delay():
    queue = WorkQueue[str]()
    with pytest.raises(ValueError):
        queue.done("a")
    for delay in (-1, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            queue.add_after("a", delay)


async def test_retry_reaches_cap_across_the_full_finite_float_range():
    queue = WorkQueue[str](base_delay=1e-300, max_delay=1e300, jitter=0)
    queue._retries["a"] = 1994
    assert queue.retry("a") == 1e300
    queue.shutdown()
    await queue.join()

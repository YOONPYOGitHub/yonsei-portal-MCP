"""Offline cache tests; producers never access credentials or the network."""
import asyncio

import pytest

from yonsei_portal_mcp import cache


@pytest.fixture(autouse=True)
def empty_cache():
    cache.clear()
    yield
    cache.clear()


async def test_same_key_concurrent_calls_share_one_producer():
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def produce():
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return {"result": "shared"}

    tasks = [asyncio.create_task(cache.cached(("account", "courses"), 60, produce))
             for _ in range(3)]
    await started.wait()
    await asyncio.sleep(0)
    release.set()
    results = await asyncio.gather(*tasks)
    assert calls == 1
    assert results == [{"result": "shared"}] * 3


async def test_cancelling_one_waiter_does_not_cancel_shared_work():
    started = asyncio.Event()
    release = asyncio.Event()

    async def produce():
        started.set()
        await release.wait()
        return "finished"

    first = asyncio.create_task(cache.cached("key", 60, produce))
    second = asyncio.create_task(cache.cached("key", 60, produce))
    await started.wait()
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    release.set()
    assert await second == "finished"


async def test_abandoned_producer_failure_is_retrieved():
    loop = asyncio.get_running_loop()
    errors = []
    previous_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: errors.append(context))
    started = asyncio.Event()
    release = asyncio.Event()
    finished = asyncio.Event()

    async def produce():
        started.set()
        await release.wait()
        finished.set()
        raise ValueError("offline failure")

    try:
        waiter = asyncio.create_task(cache.cached("abandoned", 60, produce))
        await started.wait()
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        release.set()
        await finished.wait()
        # Run the producer's completion callback and drop the last task reference.
        await asyncio.sleep(0)
        import gc
        gc.collect()
        assert errors == []
    finally:
        loop.set_exception_handler(previous_handler)


async def test_clear_prevents_inflight_result_repopulating_cache():
    started = asyncio.Event()
    release = asyncio.Event()

    async def old_producer():
        started.set()
        await release.wait()
        return "old"

    old = asyncio.create_task(cache.cached("key", 60, old_producer))
    await started.wait()
    cache.clear()
    release.set()
    assert await old == "old"
    assert cache._cache.get("key", 60) is None


@pytest.mark.parametrize("interaction", ["hit", "miss", "write"])
async def test_cache_interactions_sweep_other_expired_keys(monkeypatch, interaction):
    from types import SimpleNamespace
    now = [100.0]
    monkeypatch.setattr(cache, "time", SimpleNamespace(monotonic=lambda: now[0]))

    async def produce():
        return "value"

    await cache.cached("expired", 5, produce)
    await cache.cached("fresh", 60, produce)
    now[0] = 106.0
    if interaction == "write":
        cache._cache.set("another", "value")
    else:
        cache._cache.get("fresh" if interaction == "hit" else "missing", 60)
    assert "expired" not in cache._cache._store
    assert cache._cache.get("fresh", 60) == "value"


def test_cache_is_bounded_to_256_entries():
    store = cache.TTLCache()
    for index in range(257):
        store.set(index, str(index))
    assert len(store._store) == 256
    assert store.get(0, 60) is None
    assert store.get(256, 60) == "256"


async def test_different_account_keys_run_independently():
    started = asyncio.Event()
    release = asyncio.Event()

    async def account_a():
        started.set()
        await release.wait()
        return "account-a"

    async def account_b():
        return "account-b"

    first = asyncio.create_task(cache.cached(("courses", "a"), 60, account_a))
    await started.wait()
    try:
        assert await asyncio.wait_for(
            cache.cached(("courses", "b"), 60, account_b), timeout=1
        ) == "account-b"
    finally:
        release.set()
        assert await first == "account-a"
    assert cache._cache.get(("courses", "a"), 60) == "account-a"
    assert cache._cache.get(("courses", "b"), 60) == "account-b"


@pytest.mark.parametrize("failure", [ValueError, asyncio.CancelledError])
async def test_producer_failure_is_shared_but_not_cached(failure):
    calls = 0

    async def fail():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        raise failure("offline failure")

    results = await asyncio.gather(
        *(cache.cached("key", 60, fail) for _ in range(3)),
        return_exceptions=True,
    )
    assert calls == 1
    assert all(isinstance(result, failure) for result in results)
    assert cache._inflight == {}
    assert cache._cache.get("key", 60) is None

    async def retry():
        return "recovered"

    assert await cache.cached("key", 60, retry) == "recovered"


@pytest.mark.parametrize("old_finishes_first", [True, False])
async def test_clear_starts_new_flight_without_old_cleanup_removing_it(old_finishes_first):
    started_old = asyncio.Event()
    started_new = asyncio.Event()
    release_old = asyncio.Event()
    release_new = asyncio.Event()
    new_calls = 0

    async def old_producer():
        started_old.set()
        await release_old.wait()
        return "old"

    async def new_producer():
        nonlocal new_calls
        new_calls += 1
        started_new.set()
        await release_new.wait()
        return "new"

    old = asyncio.create_task(cache.cached("key", 60, old_producer))
    await started_old.wait()
    cache.clear()
    new = asyncio.create_task(cache.cached("key", 60, new_producer))
    try:
        await asyncio.wait_for(started_new.wait(), timeout=1)
        if old_finishes_first:
            release_old.set()
            assert await old == "old"
            assert cache._cache.get("key", 60) is None
        another = asyncio.create_task(cache.cached("key", 60, new_producer))
        await asyncio.sleep(0)
        release_new.set()
        assert await new == "new"
        assert await another == "new"
        release_old.set()
        assert await old == "old"
        assert new_calls == 1
        assert cache._cache.get("key", 60) == "new"
    finally:
        release_old.set()
        release_new.set()
        await asyncio.gather(old, new, return_exceptions=True)


def test_pending_flights_are_not_shared_between_event_loops():
    first_loop = asyncio.new_event_loop()
    second_loop = asyncio.new_event_loop()

    async def slow():
        await asyncio.Future()

    async def fast():
        return "second-loop"

    async def run_first():
        asyncio.create_task(cache.cached("same-key", 60, slow))
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    async def cancel_pending():
        pending = asyncio.all_tasks() - {asyncio.current_task()}
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    try:
        first_loop.run_until_complete(run_first())
        assert second_loop.run_until_complete(
            asyncio.wait_for(cache.cached("same-key", 60, fast), timeout=1)
        ) == "second-loop"
        first_loop.run_until_complete(cancel_pending())
        assert cache._inflight == {}
    finally:
        first_loop.run_until_complete(cancel_pending())
        second_loop.run_until_complete(cancel_pending())
        first_loop.close()
        second_loop.close()


async def test_ttl_starts_at_producer_completion_and_expires_at_boundary(monkeypatch):
    from types import SimpleNamespace
    now = [100.0]
    monkeypatch.setattr(cache, "time", SimpleNamespace(monotonic=lambda: now[0]))
    calls = 0

    async def produce():
        nonlocal calls
        calls += 1
        now[0] += 20
        return calls

    assert await cache.cached("key", 5, produce) == 1
    now[0] = 124.0
    assert await cache.cached("key", 5, produce) == 1
    now[0] = 125.0
    assert await cache.cached("key", 5, produce) == 2


@pytest.mark.parametrize("ttl", [0, -1])
async def test_nonpositive_ttl_does_not_reuse_a_completed_result(ttl):
    calls = 0

    async def produce():
        nonlocal calls
        calls += 1
        return calls

    assert await cache.cached("key", ttl, produce) == 1
    assert await cache.cached("key", ttl, produce) == 2


def test_clear_removes_cached_values():
    cache._cache.set("key", "value")
    cache.clear()
    assert cache._cache.get("key", 60) is None


async def test_clear_keeps_abandoned_work_alive_until_completion():
    import gc
    import weakref

    started = asyncio.Event()
    finished = asyncio.Event()
    references = []
    errors = []
    loop = asyncio.get_running_loop()
    previous_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: errors.append(context))

    async def produce():
        future = loop.create_future()
        references.append(weakref.ref(future))
        started.set()
        try:
            return await future
        finally:
            finished.set()

    try:
        waiter = asyncio.create_task(cache.cached("abandoned", 60, produce))
        await started.wait()
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        cache.clear()
        del waiter
        await asyncio.sleep(0)
        gc.collect()
        future = references[0]()
        assert future is not None, "clear dropped the last owner of active work"
        future.set_result("old")
        await finished.wait()
        await asyncio.sleep(0)
        assert errors == []
        assert cache._inflight == {}
        assert cache._cache.get("abandoned", 60) is None
    finally:
        loop.set_exception_handler(previous_handler)

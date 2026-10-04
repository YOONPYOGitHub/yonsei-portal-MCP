"""In-process TTL cache for read-only scraper results.

The MCP server is a single long-lived process, so a tiny monotonic-clock cache
collapses repeated identical tool/account/argument keys into one scrape.
Overview and its component tools currently use separate keys and TTLs.

Completed results are capped at 256 entries (oldest insertion evicted first).
Expiry is swept on reads and writes. TTL limits reuse from producer completion;
it is not hard background erasure: idle entries, active work, and references
already returned to callers can remain alive beyond that interval.

Same-key asyncio callers share work within an event loop. Keys are used intact,
including account identifiers supplied by callers; values remain shared refs.
Active producers are not subject to the completed-entry limit.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable, Hashable

# Per-resource TTLs in seconds.
COURSES_TTL = 1800
DEADLINES_TTL = 300
NOTICES_TTL = 300
ATTENDANCE_TTL = 300
COURSE_MATERIALS_TTL = 1800
OVERVIEW_TTL = 300
NOTICE_BODY_TTL = 1800
MY_LOANS_TTL = 300
LIBRARY_SEATS_TTL = 60
LIBRARY_SEAT_ROOMS_TTL = 60
LIBRARY_SEARCH_TTL = 300
LIBRARY_NOTICES_TTL = 300
ERP_PROFILE_TTL = 1800
ERP_TIMETABLE_TTL = 1800
ERP_GRADES_TTL = 1800

MAX_ENTRIES = 256


class TTLCache:
    """Small FIFO store; callers pass each result's TTL when writing it."""

    def __init__(self) -> None:
        self._store: dict[Hashable, tuple[float, float, Any]] = {}

    def _evict_expired(self, now: float) -> None:
        for key, (_, expires, _) in list(self._store.items()):
            if now >= expires:
                del self._store[key]

    def get(self, key: Hashable, ttl: float) -> Any | None:
        now = time.monotonic()
        self._evict_expired(now)
        item = self._store.get(key)
        if item is None:
            return None
        ts, _, value = item
        if now - ts >= ttl:
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: Hashable, value: Any, ttl: float = float("inf")) -> None:
        now = time.monotonic()
        self._evict_expired(now)
        self._store[key] = (now, now + ttl, value)
        while len(self._store) > MAX_ENTRIES:
            del self._store[next(iter(self._store))]

    def clear(self) -> None:
        self._store.clear()


_cache = TTLCache()
_generation = 0
# Keep strong references until completion, including work invalidated by clear().
# Loop-scoping prevents a future from one pytest/server loop reaching another.
_inflight: dict[tuple[asyncio.AbstractEventLoop, int, Hashable], asyncio.Task[Any]] = {}


async def cached(
    key: Hashable, ttl: float, producer: Callable[[], Awaitable[Any]]
) -> Any:
    """Reuse a result or share the first caller's producer and TTL on this loop.

    Cancelling a waiter does not cancel shared work. Producer failures (including
    cancellation during loop shutdown) propagate to waiters and are not cached.
    """
    hit = _cache.get(key, ttl)
    if hit is not None:
        return hit
    flight_key = (asyncio.get_running_loop(), _generation, key)
    task = _inflight.get(flight_key)
    if task is None:
        generation = _generation

        async def produce() -> Any:
            value = await producer()
            if generation == _generation:
                _cache.set(key, value, ttl)
            return value

        task = asyncio.create_task(produce())
        _inflight[flight_key] = task

        def finished(done: asyncio.Task[Any]) -> None:
            # All waiters may have gone away; still retrieve a producer failure.
            if not done.cancelled():
                done.exception()
            if _inflight.get(flight_key) is done:
                del _inflight[flight_key]

        task.add_done_callback(finished)
    return await asyncio.shield(task)


def clear() -> None:
    """Invalidate results and detach new callers from all pre-clear work.

    Existing callers may still receive their result, but it cannot refill the
    cleared cache. Completion callbacks release the invalidated active tasks.
    """
    global _generation
    _generation += 1
    _cache.clear()

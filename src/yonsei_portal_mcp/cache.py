"""In-process TTL cache for read-only scraper results (DESIGN §5.1).

The MCP server is a single long-lived process, so a tiny monotonic-clock cache
collapses repeated identical reads (e.g. an LLM calling get_lms_overview then
get_lms_deadlines seconds apart) into one scrape. Read-only data only.
"""
from __future__ import annotations

import time
from typing import Any, Awaitable, Callable, Hashable

# Per-resource TTLs in seconds (DESIGN §5.1: low-freq 30-60min, high-freq 5min).
COURSES_TTL = 1800
DEADLINES_TTL = 300
NOTICES_TTL = 300
ATTENDANCE_TTL = 300
OVERVIEW_TTL = 300
NOTICE_BODY_TTL = 1800
MY_LOANS_TTL = 300
LIBRARY_SEATS_TTL = 60
LIBRARY_SEAT_ROOMS_TTL = 60
ERP_PROFILE_TTL = 1800
ERP_TIMETABLE_TTL = 1800
ERP_GRADES_TTL = 1800


class TTLCache:
    def __init__(self) -> None:
        self._store: dict[Hashable, tuple[float, Any]] = {}

    def get(self, key: Hashable, ttl: float) -> Any | None:
        item = self._store.get(key)
        if item is None:
            return None
        ts, value = item
        if time.monotonic() - ts > ttl:
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: Hashable, value: Any) -> None:
        self._store[key] = (time.monotonic(), value)

    def clear(self) -> None:
        self._store.clear()


_cache = TTLCache()


async def cached(
    key: Hashable, ttl: float, producer: Callable[[], Awaitable[Any]]
) -> Any:
    """Return a cached value for ``key`` or run ``producer`` and cache it."""
    hit = _cache.get(key, ttl)
    if hit is not None:
        return hit
    value = await producer()
    _cache.set(key, value)
    return value


def clear() -> None:
    _cache.clear()

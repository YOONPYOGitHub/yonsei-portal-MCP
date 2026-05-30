"""Smoke test for the login-based reading-room seat tool (Playwright path).

Run: ``uv run python tests/smoke_seat_rooms.py``
"""
import asyncio
import os
import sys
from pathlib import Path

os.environ.setdefault("YONSEI_HEADED", "false")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from yonsei_portal_mcp.scrapers import library  # noqa: E402
from yonsei_portal_mcp.session import get_library_session  # noqa: E402


def _check(result: dict) -> None:
    assert isinstance(result, dict), "result must be a dict"
    for k in ("count", "rooms", "total", "in_use", "available", "usage_pct"):
        assert k in result, f"missing key: {k}"
    assert result["count"] == len(result["rooms"]), "count mismatch"
    assert result["rooms"], "no rooms parsed (selector drift?)"
    for r in result["rooms"]:
        for k in (
            "name",
            "assignable",
            "total",
            "capacity",
            "in_use",
            "available",
            "hours",
            "usage_pct",
            "note",
        ):
            assert k in r, f"room missing key: {k}"
        assert r["name"], "empty room name"
    assert 0 <= result["usage_pct"] <= 100, "usage_pct range"


async def main() -> None:
    result = await get_library_session().run(library.fetch_seat_rooms)
    _check(result)
    print(
        f"ROOMS: {result['count']} rooms, "
        f"in_use={result['in_use']}/{result['total']} "
        f"available={result['available']} usage={result['usage_pct']}%"
    )
    for r in result["rooms"][:8]:
        print(
            f"  {r['name']}: {r['in_use']}/{r['total']} "
            f"avail={r['available']} ({r['usage_pct']}%) {r['hours']}"
        )

    # Second run should be consistent in shape.
    again = await get_library_session().run(library.fetch_seat_rooms)
    _check(again)
    assert again["count"] == result["count"], "row count drift between runs"
    print("SEAT ROOMS SMOKE TEST PASSED")


if __name__ == "__main__":
    asyncio.run(main())

"""Smoke test for the no-login library seat tool (httpx path, no browser).

Run: ``uv run python tests/smoke_seats.py``
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from yonsei_portal_mcp.scrapers import seats  # noqa: E402


def _check_shape(result: dict) -> None:
    assert isinstance(result, dict), "result must be a dict"
    for k in ("rows", "total", "in_use", "remaining", "usage_pct"):
        assert k in result, f"missing top-level key: {k}"
    assert isinstance(result["rows"], list) and result["rows"], "rows empty"
    for r in result["rows"]:
        for k in (
            "building",
            "building_code",
            "seat_type",
            "seat_type_code",
            "total",
            "in_use",
            "remaining",
            "usage_pct",
        ):
            assert k in r, f"row missing key: {k}"
        assert r["remaining"] == max(r["total"] - r["in_use"], 0), "remaining math"
        assert 0 <= r["usage_pct"] <= 100, "usage_pct range"


async def main() -> None:
    result = await seats.fetch_seats()
    _check_shape(result)
    print(
        f"ALL: {len(result['rows'])} rows, "
        f"total={result['total']} in_use={result['in_use']} "
        f"remaining={result['remaining']} usage={result['usage_pct']}%"
    )
    for r in result["rows"]:
        print(
            f"  {r['building']}/{r['seat_type']}: "
            f"{r['in_use']}/{r['total']} ({r['usage_pct']}%)"
        )

    # Filtered view consistency.
    pc = await seats.fetch_seats("pc")
    _check_shape(pc) if pc["rows"] else None
    assert all(r["seat_type_code"] == "pc" for r in pc["rows"]), "filter leaked"
    print(f"PC filter: {len(pc['rows'])} rows, total={pc['total']}")

    print("SEATS SMOKE TEST PASSED")


if __name__ == "__main__":
    asyncio.run(main())

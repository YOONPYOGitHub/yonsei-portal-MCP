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
    assert isinstance(result["rows"], list)
    assert result["semantics_verified"] is False
    assert result["scope"] == "public_widget_api"
    for item in [result, *result["rows"]]:
        assert all(item[key] is None for key in ("in_use", "remaining", "usage_pct"))
        assert all(type(item[key]) is int and item[key] >= 0 for key in ("total", "raw_use", "raw_total_minus_use"))
        assert item["total"] == item["raw_use"] + item["raw_total_minus_use"]
    for row in result["rows"]:
        for field in (
            "building",
            "building_code",
            "seat_type",
            "seat_type_code",
        ):
            assert field in row, f"row missing key: {field}"
    for field in ("total", "raw_use", "raw_total_minus_use"):
        assert result[field] == sum(row[field] for row in result["rows"])


async def main() -> None:
    result = await seats.fetch_seats()
    _check_shape(result)
    print(
        f"ALL: {len(result['rows'])} rows, "
        f"raw total={result['total']} raw_use={result['raw_use']} "
        "occupancy/availability=UNKNOWN"
    )
    for row in result["rows"]:
        print(
            f"  {row['building']}/{row['seat_type']}: "
            f"raw_use={row['raw_use']} raw_total={row['total']}"
        )

    # Filtered view consistency.
    pc = await seats.fetch_seats("pc")
    _check_shape(pc)
    assert all(row["seat_type_code"] == "pc" for row in pc["rows"]), "filter leaked"
    print(f"PC filter: {len(pc['rows'])} rows, total={pc['total']}")

    print("SEATS SMOKE TEST PASSED")


if __name__ == "__main__":
    asyncio.run(main())

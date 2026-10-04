"""Smoke test for the anonymous homepage seat tool (Chromium required).

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
    assert result["display_verified"] is True
    assert result["scope"] == "homepage_display"
    for item in [result, *result["rows"]]:
        assert item["usage_pct"] is None
        assert all(type(item[key]) is int and item[key] >= 0 for key in ("total", "in_use", "remaining"))
    for row in result["rows"]:
        for field in (
            "building",
            "building_code",
            "seat_type",
            "seat_type_code",
        ):
            assert field in row, f"row missing key: {field}"
        assert row["source_totals_match"] == (row["total"] == row["in_use"] + row["remaining"])
    assert result["source_totals_match"] == all(row["source_totals_match"] for row in result["rows"])
    for field in ("total", "in_use", "remaining"):
        assert result[field] == sum(row[field] for row in result["rows"])


async def main() -> None:
    result = await seats.fetch_seats()
    _check_shape(result)
    print(
        f"ALL: {len(result['rows'])} rows, "
        f"displayed total={result['total']} usage={result['in_use']} "
        f"remaining={result['remaining']}"
    )
    for row in result["rows"]:
        print(
            f"  {row['building']}/{row['seat_type']}: "
            f"displayed usage={row['in_use']} remaining={row['remaining']} total={row['total']}"
        )

    # Filtered view consistency.
    pc = await seats.fetch_seats("pc")
    _check_shape(pc)
    assert all(row["seat_type_code"] == "pc" for row in pc["rows"]), "filter leaked"
    print(f"PC filter: {len(pc['rows'])} rows, total={pc['total']}")

    print("SEATS SMOKE TEST PASSED")


if __name__ == "__main__":
    asyncio.run(main())

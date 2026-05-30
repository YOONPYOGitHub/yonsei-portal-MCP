"""End-to-end smoke test for the Yonsei Library tools.

Logs in to library.yonsei.ac.kr using the credentials in ``.env`` and calls the
read-only loan scraper, printing a masked summary. Run with:

    uv run python tests/smoke_library.py

Personal data (book titles, registration numbers) is masked in this output.
"""
from __future__ import annotations

import asyncio
import os

os.environ.setdefault("YONSEI_HEADED", "false")

from yonsei_portal_mcp.scrapers import library  # noqa: E402
from yonsei_portal_mcp.session import get_library_session  # noqa: E402


def _mask(value: str | None) -> str:
    if not value:
        return "-"
    return value[:2] + "***" if len(value) > 2 else "***"


async def main() -> None:
    session = get_library_session()
    try:
        result = await session.run(library.fetch_my_loans)

        assert isinstance(result, dict), "fetch_my_loans must return a dict"
        assert "count" in result and "loans" in result, "missing count/loans keys"
        assert result["count"] == len(result["loans"]), "count/loans length mismatch"

        print(f"[OK] login + my loans: count={result['count']}")
        for loan in result["loans"][:5]:
            # Mask PII (title/author + reg number) in the smoke output.
            print(
                f"   - {_mask(loan.get('title_author'))} | "
                f"due={loan.get('due_date')} | renew={loan.get('renew_count')} "
                f"| fee={loan.get('overdue_fee')}"
            )

        # Each loan dict carries the full contract key set.
        expected_keys = {
            "title_author", "location", "reg_no", "loan_date",
            "due_date", "overdue_fee", "renew_count",
        }
        for loan in result["loans"]:
            assert expected_keys <= set(loan), "loan missing contract keys"

        # session.run() retry wrapper returns the same shape on a second call.
        again = await session.run(library.fetch_my_loans)
        assert again["count"] == result["count"], "second run count mismatch"

        print("\nLIBRARY SMOKE TEST PASSED")
    finally:
        await session.close()


if __name__ == "__main__":
    asyncio.run(main())

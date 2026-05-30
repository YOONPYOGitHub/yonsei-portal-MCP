"""End-to-end smoke test for search_notices (LearnUs 통합 공지 검색).

Logs in to LearnUs, fetches notices, and exercises the in-process keyword
filter that backs the ``search_notices`` MCP tool. Run with:

    uv run python tests/smoke_search.py
"""
from __future__ import annotations

import asyncio
import os

os.environ.setdefault("YONSEI_HEADED", "false")

from yonsei_portal_mcp import server  # noqa: E402
from yonsei_portal_mcp.session import get_session  # noqa: E402


async def main() -> None:
    try:
        await _run()
    finally:
        await get_session().close()


async def _run() -> None:
    # Empty query → returns everything (count == len(results) up to limit).
    everything = await server.search_notices(query="", scope="all", limit=100)
    assert isinstance(everything, dict), "search_notices must return a dict"
    assert {"query", "scope", "count", "results"} <= set(everything), "missing keys"
    total = everything["count"]
    print(f"[OK] baseline notices: count={total}")

    if total == 0:
        print("\nSEARCH SMOKE TEST PASSED (no notices to filter)")
        return

    # Pick a token from the first notice title and confirm it self-matches.
    sample = everything["results"][0]
    title = (sample.get("title") or "").strip()
    token = next((w for w in title.split() if len(w) >= 2), None)
    print(f"   sample title: {title[:60]!r} | token={token!r}")

    if token:
        res = await server.search_notices(query=token, scope="all", limit=100)
        assert res["count"] >= 1, "keyword search should match its own source title"
        assert all(
            token.lower()
            in " ".join(
                str(r.get(k) or "") for k in ("title", "course", "type")
            ).lower()
            for r in res["results"]
        ), "every result must contain the query token"
        print(f"[OK] keyword '{token}': count={res['count']}")

    # A nonsense token should match nothing.
    none = await server.search_notices(
        query="zzzqqq_no_such_notice_xyz", scope="all"
    )
    assert none["count"] == 0, "nonsense query should return zero matches"
    print("[OK] nonsense query: count=0")

    # limit is honoured.
    limited = await server.search_notices(query="", scope="all", limit=1)
    assert len(limited["results"]) <= 1, "limit must cap results length"
    print(f"[OK] limit=1: results={len(limited['results'])} (count={limited['count']})")

    print("\nSEARCH SMOKE TEST PASSED")


if __name__ == "__main__":
    asyncio.run(main())

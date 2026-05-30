"""End-to-end smoke test for the Yonsei Portal MCP server.

Logs in to LearnUs using the credentials in ``.env`` and calls the read-only
scrapers, printing a short masked summary. Run with:

    uv run python tests/smoke.py

Requires Playwright system dependencies (one-time):

    sudo $(which uv) run playwright install-deps chromium
"""
from __future__ import annotations

import asyncio
import os

# Force headless for an unattended smoke run unless the caller overrides it.
os.environ.setdefault("YONSEI_HEADED", "false")

from yonsei_portal_mcp.scrapers import learnus  # noqa: E402
from yonsei_portal_mcp.session import get_session  # noqa: E402


async def main() -> None:
    session = get_session()
    try:
        async with session.page() as page:
            courses = await learnus.fetch_courses(page)
            course_map = {c["id"]: c["name"] for c in courses if c.get("id")}
            deadlines = await learnus.fetch_deadlines(page, course_map=course_map)
            notices = await learnus.fetch_notices(page, scope="all")

        print(f"[OK] courses: {len(courses)}")
        for c in courses[:5]:
            print(
                f"   - {c['name']} | code={c['code']} | prof={c['professor']} "
                f"| {c['progress_percent']}%"
            )

        print(f"[OK] deadlines: {len(deadlines)}")
        for d in deadlines[:5]:
            print(f"   - {d['title']} | due={d['due']} | course={d['course']}")

        print(f"[OK] notices: {len(notices)}")
        for n in notices[:5]:
            print(f"   - [{n['type']}] {n['date']} {n['title']}")

        assert courses, "no courses returned - login or scraping failed"

        # --- new contract behaviour (DESIGN §4-ter / §5.1) ------------------
        # deadlines carry a source field and come back sorted by due ascending.
        for d in deadlines:
            assert d.get("source") == "calendar", "deadline missing source field"
        dues = [d["due"] for d in deadlines if d.get("due")]
        assert dues == sorted(dues), "deadlines not sorted by due ascending"

        # session.run() should perform the same work via the retry wrapper.
        run_courses = await session.run(learnus.fetch_courses)
        assert len(run_courses) == len(courses), "session.run course mismatch"

        # course_id filter narrows deadlines to a single course (if any exist).
        if deadlines:
            cid = next((d["course_id"] for d in deadlines if d.get("course_id")), None)
            if cid:
                filtered = await session.run(
                    lambda page: learnus.fetch_deadlines(page, course_id=cid)
                )
                assert all(d["course_id"] == cid for d in filtered), (
                    "course_id filter leaked other courses"
                )
                print(f"[OK] deadline filter course_id={cid}: {len(filtered)}")

        # get_notice body round-trip on the first notice URL.
        if notices:
            url = notices[0]["url"]
            body = await session.run(
                lambda page: learnus.fetch_notice_body(page, url)
            )
            print(
                f"[OK] notice body: title={body['title']!r} "
                f"len(body)={len(body['body'] or '')}"
            )

        print("\nSMOKE TEST PASSED")
    finally:
        await session.close()


if __name__ == "__main__":
    asyncio.run(main())

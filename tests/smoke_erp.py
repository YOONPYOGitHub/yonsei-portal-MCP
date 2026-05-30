"""End-to-end smoke test for the Yonsei ERP (학사행정) tools.

Logs in to underwood1.yonsei.ac.kr using the credentials in ``.env`` and calls
the read-only profile / timetable / grades scrapers, printing a masked summary.
Run with:

    uv run python tests/smoke_erp.py

Personal data (name, student number) is masked in this output. Grades are
expected to be EMPTY for a brand-new graduate student (no completed term yet) —
that is a valid, passing result.
"""
from __future__ import annotations

import asyncio
import os

os.environ.setdefault("YONSEI_HEADED", "false")

from yonsei_portal_mcp.scrapers import erp  # noqa: E402
from yonsei_portal_mcp.session import get_erp_session  # noqa: E402


def _mask(value) -> str:
    if value is None:
        return "-"
    s = str(value)
    return s[:2] + "***" if len(s) > 2 else "***"


async def main() -> None:
    session = get_erp_session()
    try:
        # --- profile -------------------------------------------------------- #
        profile = await session.run(erp.fetch_student_profile)
        assert isinstance(profile, dict), "profile must be a dict"
        assert profile.get("name"), "profile missing name"
        assert profile.get("student_no"), "profile missing student_no"
        print(
            f"[OK] profile: name={_mask(profile['name'])} "
            f"no={_mask(profile['student_no'])} "
            f"dept={profile.get('department')} "
            f"term={profile.get('current_term')} "
            f"credits={profile.get('current_term_credits')} "
            f"terms={len(profile.get('terms') or [])}"
        )

        # --- timetable ------------------------------------------------------ #
        tt = await session.run(erp.fetch_timetable)
        assert isinstance(tt, dict), "timetable must be a dict"
        assert "courses" in tt and "count" in tt, "timetable missing keys"
        assert tt["count"] == len(tt["courses"]), "count/courses mismatch"
        print(
            f"[OK] timetable: term={tt.get('term')} count={tt['count']} "
            f"credits={tt.get('total_credits')}"
        )
        for c in tt["courses"]:
            assert "course_code" in c and "course_name" in c, "course missing keys"
            slot = ", ".join(
                f"{s['day']}{s['period']}" for s in c.get("slots", [])
            )
            print(
                f"   - {c.get('course_code')} {c.get('course_name')} "
                f"[{c.get('credits')}학점] {c.get('professor')} "
                f"@{c.get('room')} ({c.get('time_raw')} -> {slot})"
            )

        # --- grades (expected empty for a new grad student) ----------------- #
        grades = await session.run(erp.fetch_grades)
        assert isinstance(grades, dict), "grades must be a dict"
        assert "count" in grades and "courses" in grades, "grades missing keys"
        assert grades["count"] == len(grades["courses"]), "grade count mismatch"
        note = grades.get("note", "")
        print(f"[OK] grades: count={grades['count']} note={note!r}")

        # --- cache parity: a second call returns the same shape ------------- #
        again = await session.run(erp.fetch_student_profile)
        assert again.get("student_no") == profile.get("student_no"), (
            "second profile run mismatch"
        )

        print("\nERP SMOKE TEST PASSED")
    finally:
        await session.close()


if __name__ == "__main__":
    asyncio.run(main())

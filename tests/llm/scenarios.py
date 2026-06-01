"""Scenario test runner for the LLM <-> MCP harness.

Runs a batch of realistic Korean questions through the *real* LLM
(``LLM_PROVIDER``) against the **real** MCP server over stdio (real portal
login + scraping). For each scenario it records which MCP tools the model chose
and the final answer, then scores tool selection against an ``expected`` set of
acceptable tools.

This logs in to the live portal and sends the resulting real data to the
configured LLM, so it is gated behind ``RUN_LIVE_LLM=1``.

Usage::

    RUN_LIVE_LLM=1 uv run python -m tests.llm.scenarios
    RUN_LIVE_LLM=1 uv run python -m tests.llm.scenarios --provider azure-openai

Exit code is the number of FAILED scenarios (0 = all good).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time

try:
    from dotenv import load_dotenv

    load_dotenv(override=True)
except ImportError:  # pragma: no cover
    pass

from .mcp_host import run_agent, stdio_client_session
from .providers import ProviderUnavailable, make_provider


# Each scenario: (id, question, {acceptable tool names}). A scenario passes if
# the model called at least one tool from the acceptable set.
SCENARIOS: list[tuple[str, str, set[str]]] = [
    ("timetable", "이번 학기 내 시간표 알려줘", {"get_my_timetable"}),
    ("deadlines", "이번 주에 마감인 과제 뭐 있어?", {"get_lms_deadlines", "get_lms_overview"}),
    ("overview", "오늘 처리할 일 정리해줘", {"get_lms_overview", "get_lms_deadlines"}),
    ("grades", "내 전체 성적 보여줘", {"get_grades"}),
    ("courses", "내가 수강 중인 과목 목록 알려줘", {"get_lms_courses"}),
    ("seats_public", "지금 도서관 빈자리 있어?", {"get_library_seats", "get_library_seat_rooms"}),
    ("seat_rooms", "중앙도서관 열람실별 실시간 좌석 현황 알려줘", {"get_library_seat_rooms", "get_library_seats"}),
    ("loans", "내가 빌린 책 반납일 언제야?", {"get_my_loans"}),
    ("profile", "내 학적 프로필이랑 이수학점 알려줘", {"get_student_profile"}),
    ("notices", "최근 공지사항 보여줘", {"get_lms_notices", "search_notices"}),
    ("search_notice", "장학금 관련 공지 검색해줘", {"search_notices", "get_lms_notices"}),
    ("attendance", "인공지능 과목 출석 현황 알려줘", {"get_lms_attendance", "get_lms_courses"}),
    ("course_materials", "인공지능 과목 주차별 강의자료 목록 알려줘", {"get_lms_course_materials", "get_lms_courses"}),
    ("export_ics", "내 과제 마감이랑 도서 반납일을 캘린더 파일로 내보내줘", {"export_calendar_ics"}),
]


async def _run_one(session, provider, question: str) -> dict:
    t0 = time.perf_counter()
    error = None
    try:
        run = await run_agent(session, provider, question, max_turns=8)
        tools = list(run.called_tool_names)
        answer = run.final_text or ""
    except Exception as exc:  # surface tool/model failures per scenario
        tools, answer = [], ""
        error = f"{type(exc).__name__}: {exc}"
    return {
        "tools": tools,
        "answer": answer,
        "error": error,
        "elapsed_s": round(time.perf_counter() - t0, 2),
    }


async def _main(args: argparse.Namespace) -> int:
    try:
        provider = make_provider(args.provider)
    except ProviderUnavailable as exc:
        print(f"[scenarios] provider unavailable: {exc}", flush=True)
        return 99

    if os.getenv("RUN_LIVE_LLM") != "1":
        print(
            "[scenarios] refusing live run: set RUN_LIVE_LLM=1 to confirm "
            "(real portal login + real data sent to the LLM)",
            flush=True,
        )
        return 98

    print(f"[scenarios] provider = {provider.name}", flush=True)
    print("[scenarios] mode     = LIVE portal (real login + real data)", flush=True)
    print(f"[scenarios] count    = {len(SCENARIOS)}", flush=True)
    print("=" * 72, flush=True)

    results: list[dict] = []
    async with stdio_client_session() as session:
        for sid, question, expected in SCENARIOS:
            res = await _run_one(session, provider, question)
            called = set(res["tools"])
            hit = bool(called & expected)
            ok = hit and not res["error"]
            status = "PASS" if ok else "FAIL"
            results.append({"id": sid, "status": status, "expected": sorted(expected), **res})

            print(f"[{status}] {sid} ({res['elapsed_s']}s)", flush=True)
            print(f"  Q: {question}", flush=True)
            print(f"  expected tools : {sorted(expected)}", flush=True)
            print(f"  called   tools : {res['tools'] or '(none)'}", flush=True)
            if res["error"]:
                print(f"  ERROR: {res['error']}", flush=True)
            ans = res["answer"].replace("\n", " ").strip()
            if len(ans) > 280:
                ans = ans[:280] + " …"
            print(f"  answer : {ans or '(empty)'}", flush=True)
            print("-" * 72, flush=True)

    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = len(results) - passed
    print("=" * 72, flush=True)
    print(f"[scenarios] PASS={passed}  FAIL={failed}  TOTAL={len(results)}", flush=True)
    print("[scenarios] JSON_SUMMARY " + json.dumps(results, ensure_ascii=False), flush=True)
    return failed


def main() -> None:
    p = argparse.ArgumentParser(description="LLM <-> MCP scenario runner")
    p.add_argument(
        "--provider",
        default=os.getenv("LLM_PROVIDER", "azure-openai"),
        help="azure-openai | openai | anthropic (default: LLM_PROVIDER)",
    )
    args = p.parse_args()
    sys.exit(asyncio.run(_main(args)))


if __name__ == "__main__":
    main()

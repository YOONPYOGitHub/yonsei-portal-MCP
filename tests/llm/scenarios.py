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

    load_dotenv(override=False)
except ImportError:  # pragma: no cover
    pass

from .mcp_host import agent_run_error, run_agent, stdio_client_session
from .providers import ProviderUnavailable, make_provider


# Each scenario: (id, question, {acceptable tool names}). A scenario passes if
# the model successfully called an expected tool and produced a final answer.
SCENARIOS: list[tuple[str, str, set[str]]] = [
    ("timetable", "이번 학기 내 시간표 알려줘", {"get_my_timetable"}),
    ("deadlines", "이번 주에 마감인 과제 뭐 있어?", {"get_lms_deadlines", "get_lms_overview"}),
    ("overview", "오늘 처리할 일 정리해줘", {"get_lms_overview", "get_lms_deadlines", "get_my_schedule"}),
    ("grades", "내 전체 성적 보여줘", {"get_grades"}),
    ("courses", "내가 수강 중인 과목 목록 알려줘", {"get_lms_courses"}),
    ("seats_public", "지금 도서관 빈자리 있어?", {"get_library_seats", "get_library_seat_rooms"}),
    ("seat_rooms", "중앙도서관 열람실별 잔여석과 배정 가능 여부를 구분해서 알려줘", {"get_library_seat_rooms"}),
    ("loans", "내가 빌린 책 반납일 언제야?", {"get_my_loans"}),
    ("profile", "내 학적 프로필이랑 이수학점 알려줘", {"get_student_profile"}),
    ("notices", "최근 공지사항 보여줘", {"get_lms_notices", "search_notices"}),
    ("search_notice", "장학금 관련 공지 검색해줘", {"search_notices", "get_lms_notices"}),
    ("attendance", "수강 강좌 목록의 첫 번째 강좌로 출석 현황을 조회해줘. 추가 선택 질문 없이 진행해줘.", {"get_lms_attendance"}),
    ("course_materials", "수강 강좌 목록의 첫 번째 강좌로 주차별 자료를 조회해줘. 추가 선택 질문 없이 진행해줘.", {"get_lms_course_materials"}),
    ("export_ics", "내 과제 마감이랑 도서 반납일을 캘린더 파일로 내보내줘", {"export_calendar_ics"}),
    ("assignments", "수강 강좌 목록의 첫 번째 강좌를 선택해서 그 강좌의 실제 제출 과제 목록을 조회해줘. 추가 선택 질문 없이 첫 번째 강좌로 진행해줘.", {"get_lms_assignments"}),
    ("book_search", "도서관에서 인공지능 관련 소장자료를 3건 검색해줘", {"search_library_books"}),
    ("library_notices", "도서관 휴관이나 이용시간 변경 관련 공지를 확인해줘", {"get_library_notices"}),
    ("reservations", "내가 예약한 도서와 예약순위를 알려줘. 변경하지 말고 조회만 해줘.", {"get_my_reservations"}),
    ("scholarship_history", "내 장학금 수혜 내역을 조회해줘", {"get_scholarship_history"}),
    ("exam_schedule", "현재 조회 가능한 시험시간표를 확인해줘. 조회기간 미등록과 시험 없음을 구분해줘.", {"get_exam_schedule"}),
    ("course_catalog", "수강편람에서 인공지능 교과목을 3개 검색해줘", {"search_courses"}),
    ("course_history", "내 LearnUs 과거강좌 목록을 조회해줘", {"get_lms_course_history"}),
    ("schedule", "오늘부터 7일간 마감과 도서 반납일을 주간 수업 시간표와 함께 조회해줘", {"get_my_schedule"}),
    ("grades_filtered", "2026년 1학기 성적만 필터해서 보여줘. 누적 GPA와는 구분해줘.", {"get_grades"}),
    ("exam_final", "중간시험 말고 기말시험 시간표를 조회해줘", {"get_exam_schedule"}),
    ("academic_calendar", "학교 공식 홈페이지의 이번 학기 학사일정에서 개강과 시험 기간을 확인해줘", {"get_academic_calendar"}),
    ("catalog_filtered", "수강편람에서 2026년 1학기 대학원(신촌)의 인공지능 교과목을 3개 검색해줘", {"search_courses"}),
    ("lms_gradebook", "현재 수강 강좌 목록의 첫 번째 강좌로 LearnUs 성적부를 조회해줘. ERP 확정 성적이 아니라 LMS 항목별 표시 점수이며 피드백은 제외해줘. 추가 선택 질문 없이 진행해줘.", {"get_lms_gradebook"}),
    ("book_detail", "도서관에서 인공지능을 검색하고 첫 번째 자료의 복본별 소장처, 청구기호, 대출 상태와 반납예정일을 조회해줘. 예약은 하지 마.", {"get_library_book_detail"}),
    ("loan_history", "현재 빌린 책 말고 이전 대출 기록과 실제 반납일을 조회해줘. 현재 표시 페이지와 날짜 필터 범위만 알려주고 전체 이력이라고 단정하지 마.", {"get_my_loan_history"}),
    ("reservation_history", "현재 예약 목록 말고 이전 도서 예약 이력을 조회해줘. 현재 표시 페이지의 과거 상태로 설명하고 취소나 변경은 하지 마.", {"get_my_reservation_history"}),
    ("course_boards", "현재 수강 강좌 목록의 첫 번째 강좌에 있는 게시판 목록과 표시된 게시물 수를 조회해줘. 추가 선택 질문 없이 진행해줘.", {"get_lms_boards"}),
    ("board_posts", "현재 수강 강좌 목록의 첫 번째 강좌에서 첫 번째 게시판의 글 목록을 조회해줘. 글이 없으면 빈 결과라고 알려주고 작성자나 본문은 읽지 마. 추가 선택 질문 없이 진행해줘.", {"get_lms_board_posts"}),
]


SCENARIO_ARGUMENTS: dict[str, dict] = {
    "grades_filtered": {"year": 2026, "term_code": "10"},
    "exam_final": {"exam_type": "final"},
    "catalog_filtered": {
        "keyword": "인공지능", "limit": 3, "year": 2026,
        "term_code": "10", "campus_code": "s3",
    },
}


async def _run_one(session, provider, question: str, *, scenario_id: str | None = None) -> dict:
    t0 = time.perf_counter()
    error = None
    try:
        run = await run_agent(session, provider, question, max_turns=8)
        tools = list(run.called_tool_names)
        answer = run.final_text or ""
        expected = next(names for sid, _, names in SCENARIOS if sid == scenario_id) if scenario_id is not None else None
        error = agent_run_error(run, expected)
        if error is None and expected is not None:
            relevant = [call for call in run.tool_calls if call.name in expected]
            required = SCENARIO_ARGUMENTS.get(scenario_id, {})
            if not all(all(call.arguments.get(key) == value for key, value in required.items()) for call in relevant):
                error = "Scenario tool arguments do not match requested filters"
            if scenario_id == "lms_gradebook" and any(call.arguments.get("include_feedback", False) is not False for call in relevant):
                error = "Gradebook feedback was not requested"
            if scenario_id == "board_posts" and "get_notice" in tools:
                error = "Board post body was not requested"
    except Exception as exc:  # surface tool/model failures per scenario
        tools, answer = [], ""
        error = type(exc).__name__
    return {
        "tools": tools,
        "answer": answer,
        "error": error,
        "elapsed_s": round(time.perf_counter() - t0, 2),
    }


async def _main(args: argparse.Namespace) -> int:
    if os.getenv("RUN_LIVE_LLM") != "1":
        print(
            "[scenarios] refusing live run: set RUN_LIVE_LLM=1 to confirm "
            "(real portal login + real data sent to the LLM)",
            flush=True,
        )
        return 98

    try:
        provider = make_provider(args.provider)
    except ProviderUnavailable:
        print("[scenarios] provider unavailable (details suppressed)", flush=True)
        return 99

    print(f"[scenarios] provider = {provider.name}", flush=True)
    print("[scenarios] mode     = LIVE portal (real login + real data)", flush=True)
    print(f"[scenarios] count    = {len(SCENARIOS)}", flush=True)
    print("=" * 72, flush=True)

    results: list[dict] = []
    async with stdio_client_session() as session:
        for sid, question, expected in SCENARIOS:
            res = await _run_one(session, provider, question, scenario_id=sid)
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
        help=(
            "azure-openai | openai | anthropic | gemini "
            "(default: LLM_PROVIDER)"
        ),
    )
    args = p.parse_args()
    sys.exit(asyncio.run(_main(args)))


if __name__ == "__main__":
    main()

"""Tool-selection tests: does the host call the right MCP tool for a question?

L1 (always runs): StubProvider drives the loop with no network.
L2 (runs when a real LLM is configured): the real model must pick the tool we
expect from a Korean question, using in-memory fixture tools (no PII).
"""
from __future__ import annotations

import pytest

from .providers import StubProvider


# --- L1: stub provider, no API key ----------------------------------------


async def test_stub_drives_tool_loop(run_question):
    provider = StubProvider(planned_calls=[("get_my_timetable", {})])
    run = await run_question(provider, "내 시간표 알려줘", max_turns=4)
    assert "get_my_timetable" in run.called_tool_names
    assert run.final_text  # produced a final answer
    # The stub echoes tool output; fixture term should surface.
    assert "2026-1" in run.final_text or "운영체제" in run.final_text


async def test_stub_can_call_public_seat_tool(run_question):
    provider = StubProvider(planned_calls=[("get_library_seats", {})])
    run = await run_question(provider, "도서관 빈자리 있어?", max_turns=4)
    assert "get_library_seats" in run.called_tool_names


# --- L2: real LLM, mocked tools -------------------------------------------
# expected_tools is a set of acceptable choices: some questions have more than
# one defensible tool (e.g. aggregate vs per-room seat counts).

_CASES = [
    ("이번 학기 내 시간표 알려줘", {"get_my_timetable"}),
    ("내가 빌린 책 목록 보여줘", {"get_my_loans"}),
    (
        "중앙도서관 열람실 빈자리 몇 개야?",
        {"get_library_seats", "get_library_seat_rooms"},
    ),
    ("이번 주 과제 마감일 알려줘", {"get_lms_deadlines"}),
    ("내 학적 정보 알려줘", {"get_student_profile"}),
]


@pytest.mark.llm
@pytest.mark.parametrize("question, expected_tools", _CASES)
async def test_real_llm_selects_expected_tool(
    run_question, provider, question, expected_tools
):
    run = await run_question(provider, question, max_turns=6)
    assert expected_tools.intersection(run.called_tool_names), (
        f"{provider.name} for {question!r} called {run.called_tool_names}, "
        f"expected one of {sorted(expected_tools)}"
    )
    assert run.final_text, "model produced no final answer"

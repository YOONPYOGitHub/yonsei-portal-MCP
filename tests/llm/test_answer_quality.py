"""Answer-quality test (L2): the model's final answer reflects tool output.

Runs only when a real LLM is configured. Uses in-memory fixture tools so the
expected facts are known and no real PII is sent to the model.
"""
from __future__ import annotations

import pytest


@pytest.mark.llm
async def test_answer_mentions_fixture_deadline(run_question, provider):
    run = await run_question(
        provider,
        "다가오는 과제 마감일을 날짜와 함께 알려줘.",
        max_turns=6,
    )
    assert run.tool_calls, "expected at least one tool call"
    # Fixture deadlines are 2026-05-20 and 2026-05-23.
    assert "05-20" in run.final_text or "5월 20" in run.final_text or (
        "05-23" in run.final_text or "5월 23" in run.final_text
    ), f"answer did not reflect fixture deadlines: {run.final_text!r}"

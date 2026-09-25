"""L3 end-to-end test: real LLM + real Yonsei portal over stdio. Opt-in only.

This actually logs in to the portal and sends the resulting (real) data to the
configured external LLM. It is therefore gated behind ``RUN_LIVE_LLM=1`` AND a
configured provider, and is skipped by default.
"""
from __future__ import annotations

import os
import json
from contextlib import asynccontextmanager
from urllib.parse import parse_qs, urlsplit

import pytest

from .mcp_host import agent_run_error, call_result_to_text, run_agent, stdio_client_session
from .providers import ProviderUnavailable, make_provider


@asynccontextmanager
async def _live_session():
    try:
        async with stdio_client_session() as session:
            yield session
    except Exception:
        pass
    else:
        return
    raise pytest.fail.Exception("Live MCP/LLM operation failed (details suppressed)", pytrace=False) from None


@pytest.mark.live
@pytest.mark.llm
@pytest.mark.asyncio
async def test_live_end_to_end():
    if os.getenv("RUN_LIVE_LLM") != "1":
        pytest.skip("set RUN_LIVE_LLM=1 to run the live portal+LLM test")
    if (os.getenv("LLM_PROVIDER") or "stub").strip().lower() == "stub":
        pytest.skip("configure a real LLM_PROVIDER for the live test")
    try:
        provider = make_provider()
    except ProviderUnavailable:
        pytest.skip("LLM provider unavailable (details suppressed)")
    except Exception:
        provider = None
    if provider is None:
        pytest.fail("LLM provider initialization failed (details suppressed)", pytrace=False)

    async with _live_session() as session:
        run = await run_agent(
            session, provider, "이번 학기 내 시간표를 알려줘.", max_turns=8
        )
    error = agent_run_error(run, {"get_my_timetable"})
    if error:
        pytest.fail(error, pytrace=False)


@pytest.mark.live
@pytest.mark.llm
@pytest.mark.asyncio
async def test_live_assignment_answer_matches_source(provider):
    if os.getenv("RUN_LIVE_LLM") != "1":
        pytest.skip("set RUN_LIVE_LLM=1 for real model/source comparison")
    async with _live_session() as session:
        async def read(name, arguments):
            result = await session.call_tool(name, arguments)
            if result.isError:
                pytest.fail(f"{name}: tool error (payload suppressed)", pytrace=False)
            payload = json.loads(call_result_to_text(result))
            return payload.get("result", payload) if isinstance(payload, dict) else payload

        history = await read("get_lms_course_history", {})
        assignment_id = None
        for course in history["courses"]:
            listing = await read("get_lms_assignments", {"course_id": course["id"]})
            if listing["assignments"]:
                assignment_id = parse_qs(urlsplit(listing["assignments"][0]["url"]).query)["id"][0]
                break
        if assignment_id is None:
            pytest.fail("No accessible assignment for answer validation", pytrace=False)
        original = await read("get_lms_assignment_status", {"assignment_id": assignment_id})
        run = await run_agent(
            session, provider,
            f"과제 ID {assignment_id}의 상태를 조회한 뒤 JSON 객체만 답해줘. "
            "키는 submission_status, due, grading_status_raw이고 도구의 값을 그대로 사용해. null도 그대로 유지해.",
            max_turns=5,
        )
    error = agent_run_error(run, {"get_lms_assignment_status"})
    if error:
        pytest.fail(error, pytrace=False)
    try:
        actual = json.loads(run.final_text.strip().removeprefix("```json").removesuffix("```").strip())
    except ValueError:
        pytest.fail("Assignment answer was not JSON (payload suppressed)", pytrace=False)
    expected = {key: original[key] for key in ("submission_status", "due", "grading_status_raw")}
    matches = actual == expected
    if not matches:
        pytest.fail("Assignment answer differs from source fields (payload suppressed)", pytrace=False)

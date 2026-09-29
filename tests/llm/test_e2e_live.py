"""L3 end-to-end test: real LLM + real Yonsei portal over stdio. Opt-in only.

This actually logs in to the portal and sends the resulting (real) data to the
configured external LLM. It is therefore gated behind ``RUN_LIVE_LLM=1`` AND a
configured provider, and is skipped by default.
"""
from __future__ import annotations

import os
import json
import re
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


@pytest.mark.live
@pytest.mark.llm
@pytest.mark.asyncio
async def test_live_catalog_answer_covers_all_records_and_copy_status(provider):
    if os.getenv("RUN_LIVE_LLM") != "1":
        pytest.skip("set RUN_LIVE_LLM=1 for real catalog model/source comparison")
    from yonsei_portal_mcp.scrapers import library

    expected_records, total = {}, None
    arguments = {"query": "위키드", "campus": "sinchon_international"}
    while arguments is not None:
        result = await library.fetch_book_search(**arguments)
        total = result["total"] if total is None else total
        assert result["total"] == total and not result["page_limit_reached"]
        assert not result["source_limited"]
        for record in result["results"]:
            assert record["catalog_id"] not in expected_records
            expected_records[record["catalog_id"]] = record
        arguments = result["next_request"]
    assert len(expected_records) == total
    korean_ids = {key for key, record in expected_records.items() if re.match(r"^위키드\s*\.\s*[1-6]\s*,", record["title"])}
    assert korean_ids, "Need Korean Wicked editions for copy verification"
    sinchon_copies = {}
    for catalog_id in korean_ids:
        detail = await library.fetch_book_detail(catalog_id)
        for copy in detail["copies"]:
            if copy["location"].startswith("[신촌]"):
                assert copy["reg_no"] not in sinchon_copies
                sinchon_copies[copy["reg_no"]] = copy
    expected_counts = {
        "catalog_count": total,
        "sinchon_copy_count": len(sinchon_copies),
        "available_count": sum(copy["status_raw"] == "대출가능" for copy in sinchon_copies.values()),
        "on_loan_count": sum(copy["status_raw"] == "대출중" for copy in sinchon_copies.values()),
        "other_count": sum(copy["status_raw"] not in {"대출가능", "대출중"} for copy in sinchon_copies.values()),
    }
    captured = []
    async with _live_session() as session:
        class CatalogOnlySession:
            async def list_tools(self):
                listed = await session.list_tools()
                listed.tools = [tool for tool in listed.tools if tool.name in {"search_library_books", "get_library_book_detail"}]
                return listed

            async def call_tool(self, name, arguments):
                if name not in {"search_library_books", "get_library_book_detail"}:
                    raise ValueError("Only public catalog reads are permitted")
                response = await session.call_tool(name, arguments)
                payload = json.loads(call_result_to_text(response))
                captured.append((name, arguments, payload.get("result", payload)))
                return response

        run = await run_agent(
            CatalogOnlySession(), provider,
            "도서관에서 '위키드'를 신촌+국제 캠퍼스, 전체 항목으로 검색해 전체 자료 목록을 빠짐없이 확인해줘. "
            "그중 한국어 소설 위키드 1~6권의 모든 판본에 대해 신촌 복본이 몇 권이고 대출가능/대출중인지 확인해줘. "
            "JSON 객체만 답해줘. 키는 catalog_count(전체 검색 자료 수), catalog_ids(전체 자료 ID 목록), "
            "korean_catalog_ids(해당 한국어 소설 자료 ID 목록), sinchon_copy_count(신촌 복본 수), "
            "available_count(대출가능 복본 수), on_loan_count(대출중 복본 수), other_count(그 밖의 상태 복본 수)야.",
            max_turns=14,
        )
    error = agent_run_error(run, {"search_library_books"})
    if error:
        pytest.fail(error, pytrace=False)
    try:
        answer = json.loads(run.final_text.strip().removeprefix("```json").removesuffix("```").strip())
    except ValueError:
        pytest.fail("Catalog answer was not JSON (payload suppressed)", pytrace=False)
    searches = [data for name, arguments, data in captured if name == "search_library_books" and data.get("filters") == {"campus": "sinchon_international", "search_field": "all"} and data.get("query") == "위키드"]
    visited_ids = {record["catalog_id"] for data in searches for record in data["results"]}
    detail_ids = {data["catalog_id"] for name, arguments, data in captured if name == "get_library_book_detail"}
    assert visited_ids == set(expected_records), "Model did not collect every scoped catalog record"
    assert korean_ids <= detail_ids, "Model did not verify all Korean edition copies"
    matches = (
        all(answer.get(key) == value for key, value in expected_counts.items())
        and len(answer.get("catalog_ids", [])) == total
        and set(answer.get("catalog_ids", [])) == set(expected_records)
        and len(answer.get("korean_catalog_ids", [])) == len(korean_ids)
        and set(answer.get("korean_catalog_ids", [])) == korean_ids
    )
    assert matches, "Catalog answer counts or IDs differ from actual source data"
    print(f"catalog LLM: {total} records, {len(korean_ids)} Korean editions, {json.dumps(expected_counts)}, {len(captured)} public tool calls", flush=True)

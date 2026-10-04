"""Offline regressions for the public tool and parser contracts."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from yonsei_portal_mcp import server
from yonsei_portal_mcp.scrapers import learnus, erp
from yonsei_portal_mcp.errors import ScrapeFailedError
from types import SimpleNamespace
from test_additional_reads import local_learnus_dom


@pytest.mark.asyncio
async def test_empty_seat_filter_keeps_documented_all_behavior(monkeypatch):
    fetch = AsyncMock(return_value={"synthetic": True})
    monkeypatch.setattr(server.seats, "fetch_seats", fetch)
    server.cache.clear()
    try:
        assert await server.get_library_seats("") == {"synthetic": True}
        fetch.assert_awaited_once_with("")
    finally:
        server.cache.clear()



@pytest.mark.asyncio
@pytest.mark.parametrize("rows", [
    '<tr><th>Week</th><th>Status</th></tr>',
    '<tr><th>Week</th><th>Status</th></tr><tr><td colspan="2">Loading</td></tr>',
    '<tr><th>Week</th><th>Status</th></tr><tr><td></td><td> </td></tr>',
])
async def test_attendance_dom_does_not_call_loading_tables_ready(local_learnus_dom, rows):
    await local_learnus_dom.set_content('<table class="user_progress_table">' + rows + '</table>')
    assert await local_learnus_dom.evaluate(learnus._ATTENDANCE_JS) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("query", [
    "id=123&action=delete", "id=123&sesskey=secret", "id=123&unsupported=1",
    "id=123&id=123", "id=123&id=", "id=123&bwid=4&bwid=4", "bwid=4", "id=１２３",
])
async def test_notice_query_rejected_before_auth_or_navigation(monkeypatch, query):
    def forbidden():
        pytest.fail("Invalid notice URL reached credentials")
    monkeypatch.setattr(server, "_account", forbidden)
    page = SimpleNamespace(goto=AsyncMock())
    url = "https://ys.learnus.org/mod/ubboard/article.php?" + query
    with pytest.raises(ValueError):
        await server.get_notice(url)
    with pytest.raises(ValueError):
        await learnus.fetch_notice_body(page, url)
    page.goto.assert_not_awaited()


@pytest.mark.asyncio
async def test_notice_normalizes_query_once_before_cache_and_navigation(monkeypatch):
    monkeypatch.setattr(server, "_account", lambda: "synthetic")
    expected = "https://ys.learnus.org/mod/ubboard/article.php?id=123&bwid=456&lang=ko"
    calls = []
    async def cached(key, ttl, fetch):
        calls.append(key)
        return await fetch()
    page = SimpleNamespace(goto=AsyncMock(), wait_for_function=AsyncMock(), evaluate=AsyncMock(return_value={"body": "synthetic"}), url=expected.replace("&lang=ko", ""))
    async def run(fetch):
        return await fetch(page)
    monkeypatch.setattr(server.cache, "cached", cached)
    monkeypatch.setattr(server, "get_session", lambda: SimpleNamespace(run=run))
    result = await server.get_notice("https://ys.learnus.org:443/mod/ubboard/article.php?lang=en&bwid=456&id=123&lang=en#post")
    assert calls[0][-1] == expected
    assert page.goto.call_args.args[0] == expected
    assert result["url"] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("rows", [
    [["주차", "상태", "상태"], ["1", "출석", "완료"]],
    [["col1", "", "상태"], ["1", "출석", "완료"]],
    [["주차", "상태"]],
    [["주차", "상태"], ["", " "]],
    [["주차", "상태"], ["1"]],
    [["주차", "상태"], ["1", "출석", "unmapped"]],
    [["주차", None], ["1", "출석"]],
    [["주차", " 상태", "상태"], ["1", "출석", "완료"]],
])
async def test_attendance_damaged_or_header_only_tables_fail(rows):
    page = SimpleNamespace(goto=AsyncMock(), wait_for_function=AsyncMock(), evaluate=AsyncMock(return_value=rows), url=learnus.PROGRESS_URL.format(course_id="123"))
    with pytest.raises(ScrapeFailedError, match="출석"):
        await learnus.fetch_attendance(page, "123")


@pytest.mark.asyncio
async def test_attendance_preserves_every_unambiguous_cell():
    page = SimpleNamespace(goto=AsyncMock(), wait_for_function=AsyncMock(), evaluate=AsyncMock(return_value=[["주차", "출석", "완료"], ["1", "", "0%"]]), url=learnus.PROGRESS_URL.format(course_id="123"))
    result = await learnus.fetch_attendance(page, "123")
    assert result["weeks"] == [{"주차": "1", "출석": "", "완료": "0%"}]


@pytest.mark.asyncio
async def test_attendance_preserves_normal_blank_index_heading():
    # Synthetic row matching the observed public table layout, no student data.
    header = ["", "강의 자료", "출석인정 요구시간", "총 학습시간", "출석", "주차 출석"]
    values = ["1", "synthetic activity", "10", "0", "", ""]
    page = SimpleNamespace(goto=AsyncMock(), wait_for_function=AsyncMock(),
                           evaluate=AsyncMock(return_value=[header, values]),
                           url=learnus.PROGRESS_URL.format(course_id="123"))
    result = await learnus.fetch_attendance(page, "123")
    assert result["header"] == header
    assert result["weeks"] == [dict(zip(["col0", *header[1:]], values))]


@pytest.mark.asyncio
@pytest.mark.parametrize("url", [
    "https://underwood1.yonsei.ac.kr.evil.test/sch/sgra/SgrargCtr/findAllGradeDtlAsSyySmtList.do",
    "https://evil.test/?host=underwood1.yonsei.ac.kr&endpoint=findAllGradeDtlAsSyySmtList.do",
    "https://user@underwood1.yonsei.ac.kr/sch/sgra/SgrargCtr/findAllGradeDtlAsSyySmtList.do",
    "http://underwood1.yonsei.ac.kr/sch/sgra/SgrargCtr/findAllGradeDtlAsSyySmtList.do",
    "https://underwood1.yonsei.ac.kr:444/sch/sgra/SgrargCtr/findAllGradeDtlAsSyySmtList.do",
    "https://underwood1.yonsei.ac.kr/other?endpoint=findAllGradeDtlAsSyySmtList.do",
    "https://underwood1.yonsei.ac.kr/sch/sgra/SgrargCtr/findAllGradeDtlAsSyySmtList.do.other",
    "https://underwood1.yonsei.ac.kr/other/findAllGradeDtlAsSyySmtList.do",
])
async def test_erp_capture_ignores_origin_or_path_confusion(url):
    response = SimpleNamespace(url=url, headers={"content-type": "application/json"}, text=AsyncMock(return_value='{"synthetic": true}'))
    listeners = {}
    async def wait(milliseconds):
        await listeners["response"](response)
    page = SimpleNamespace(url="https://underwood1.yonsei.ac.kr/", on=lambda event, callback: listeners.update({event: callback}), remove_listener=lambda *args: None, wait_for_timeout=wait)
    page.main_frame = SimpleNamespace(get_by_text=lambda *args, **kwargs: SimpleNamespace(first=SimpleNamespace(click=AsyncMock())))
    result = await erp._open_menu_and_capture(page, "synthetic", "synthetic", {"grades": "findAllGradeDtlAsSyySmtList.do"}, settle_ms=1)
    assert result == {}
    response.text.assert_not_awaited()


@pytest.mark.asyncio
async def test_erp_capture_accepts_exact_endpoint_and_query():
    response = SimpleNamespace(url="https://underwood1.yonsei.ac.kr/sch/sgra/SgrargCtr/findAllGradeDtlAsSyySmtList.do?view=1", headers={"content-type": "application/json"}, text=AsyncMock(return_value='{"synthetic": true}'))
    listeners = {}
    async def wait(milliseconds):
        await listeners["response"](response)
    page = SimpleNamespace(url="https://underwood1.yonsei.ac.kr/", on=lambda event, callback: listeners.update({event: callback}), remove_listener=lambda *args: None, wait_for_timeout=wait)
    page.main_frame = SimpleNamespace(get_by_text=lambda *args, **kwargs: SimpleNamespace(first=SimpleNamespace(click=AsyncMock())))
    result = await erp._open_menu_and_capture(page, "synthetic", "synthetic", {"grades": "findAllGradeDtlAsSyySmtList.do"}, settle_ms=1)
    assert result == {"grades": {"synthetic": True}}


def test_grade_terms_allowlist_preserves_documented_academic_fields_only():
    row = {"syy": "2025", "smtDivCd": "20", "smtDivNm": "2학기", "fullNm": "2025-2학기", "acqsCdt": 3, "bwa": 4.0,
           "stdntNm": "PRIVATE_SENTINEL", "persNo": "PRIVATE_SENTINEL", "futurePrivateField": {"token": "PRIVATE_SENTINEL"}}
    result = erp._parse_grades({"dsSgra100": [], "dsSgra120": [row]})
    assert result["terms"] == [{key: row[key] for key in ("syy", "smtDivCd", "smtDivNm", "fullNm", "acqsCdt", "bwa")}]
    assert "PRIVATE_SENTINEL" not in str(result)
    assert "futurePrivateField" in row  # no mutation of upstream data


@pytest.mark.asyncio
async def test_tools_have_read_only_advisory_annotations():
    for tool in await server.mcp.list_tools():
        assert tool.annotations is not None, tool.name
        assert tool.annotations.readOnlyHint is True
        assert tool.annotations.destructiveHint is False
        assert tool.annotations.openWorldHint is True
        # Read operations can still affect server-side access logs / view counts.
        assert tool.annotations.idempotentHint is None


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"start_date": "not-a-date"}, {"end_date": "2024-01-01"}, {"end_date": "2030-01-01"},
    {"period_times": {"0": {"start": "10:00", "end": "10:50"}}},
    {"period_times": {"1": {"start": "11:00", "end": "10:50"}}},
    {"period_times": {"1": {"start": "10:00", "end": "10:50", "typo": "private"}}},
    {"exclude_dates": ["2024-01-01"]},
])
async def test_timetable_export_options_reject_before_authentication(monkeypatch, changes):
    def forbidden():
        pytest.fail("Invalid export options reached authentication")
    monkeypatch.setattr(server, "_account", forbidden)
    arguments = {"start_date": "2025-01-01", "end_date": "2025-01-31", "period_times": {"1": {"start": "10:00", "end": "10:50"}}}
    with pytest.raises(ValueError):
        await server.export_timetable_ics(**(arguments | changes))


@pytest.mark.asyncio
async def test_all_tool_unknown_arguments_are_errors_over_stdio(tmp_path):
    import os
    import sys
    from pathlib import Path
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=sys.executable, args=["-B", "-m", "yonsei_portal_mcp"], cwd=str(tmp_path),
        env={"PYTHONPATH": str(Path(__file__).resolve().parents[1]), "PYTHON_DOTENV_DISABLED": "1", "RUN_LIVE_PORTAL": "0", "RUN_LIVE_LLM": "0", "PYTHONDONTWRITEBYTECODE": "1", "YONSEI_ID": "", "YONSEI_PASSWORD": ""},
    )
    with open(os.devnull, "w") as errlog:
        async with stdio_client(params, errlog=errlog) as streams:
            async with ClientSession(*streams) as client:
                await client.initialize()
                tools = (await client.list_tools()).tools
                assert len(tools) == 38
                for tool in tools:
                    assert tool.inputSchema["additionalProperties"] is False
                    result = await client.call_tool(tool.name, {"unsupported_argument": "PRIVATE_SENTINEL"})
                    assert result.isError, tool.name
                    assert "PRIVATE_SENTINEL" not in str(result)
                    assert any("지원하지 않는 조회 인자" in getattr(part, "text", "") for part in result.content)


@pytest.mark.asyncio
@pytest.mark.parametrize(("name", "arguments"), [
    ("fetch_notices", {"scope": "typo"}),
    ("fetch_deadlines", {"course_id": "1&action=delete"}),
])
async def test_scraper_filters_reject_before_navigation(name, arguments):
    with pytest.raises(ValueError):
        await getattr(learnus, name)(None, **arguments)


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    import socket
    def blocked(*args, **kwargs):
        pytest.fail("Network access is forbidden in contract tests")
    monkeypatch.setattr(socket.socket, "connect", blocked)


@pytest.mark.asyncio
async def test_every_tool_rejects_unknown_arguments_before_dispatch(monkeypatch):
    dispatched = AsyncMock(return_value=[])
    monkeypatch.setattr(server.FastMCP, "call_tool", dispatched)
    tools = await server.mcp.list_tools()
    assert len(tools) == 38
    for tool in tools:
        with pytest.raises(ToolError, match="지원하지 않는"):
            await server.mcp.call_tool(tool.name, {"unexpected_private_argument": "sentinel"})
    dispatched.assert_not_awaited()


@pytest.mark.asyncio
async def test_every_tool_schema_disallows_unknown_arguments():
    for tool in await server.mcp.list_tools():
        assert tool.inputSchema.get("additionalProperties") is False, tool.name


@pytest.mark.asyncio
async def test_normal_named_grade_filters_survive_dispatch(monkeypatch):
    monkeypatch.setattr(server, "_account", lambda: "synthetic")
    run = AsyncMock(return_value={"count": 0, "courses": []})
    from types import SimpleNamespace
    monkeypatch.setattr(server, "get_erp_session", lambda: SimpleNamespace(run=run))
    async def uncached(key, ttl, fetch):
        return await fetch()
    monkeypatch.setattr(server.cache, "cached", uncached)
    await server.mcp.call_tool("get_grades", {"year": 2025, "term_code": "20"})
    fetch = AsyncMock(return_value={})
    monkeypatch.setattr(server.erp, "fetch_grades", fetch)
    await run.call_args.args[0]("synthetic-page")
    fetch.assert_awaited_once_with("synthetic-page", 2025, "20")
    with pytest.raises(ToolError):
        await server.mcp.call_tool("get_grades", {"year": 2025, "term_cod": "20"})
    assert run.await_count == 1


def test_disabled_dotenv_never_reads_file_or_changes_sdk_globals(tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path

    # Synthetic bait: the audit hook must stop any attempt before bytes are read.
    (tmp_path / ".env").write_text("FASTMCP_DEBUG=true\n", encoding="utf-8")
    script = '''
import os, sys
from mcp.server.fastmcp import server as sdk
original_settings = sdk.Settings
original_config = dict(sdk.Settings.model_config)
def audit(event, args):
    if event == "open" and isinstance(args[0], (str, bytes)) and os.path.basename(os.fsdecode(args[0])) == ".env":
        raise AssertionError("DOTENV_READ_BLOCKED")
sys.addaudithook(audit)
from yonsei_portal_mcp import server
assert sdk.Settings is original_settings
assert sdk.Settings.model_config == original_config
assert server.mcp.settings.debug is False
assert server.PortalMCP("another-test-server").settings.debug is False
'''
    env = {**os.environ, "PYTHON_DOTENV_DISABLED": "1", "RUN_LIVE_PORTAL": "0", "RUN_LIVE_LLM": "0", "PYTHONDONTWRITEBYTECODE": "1"}
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    result = subprocess.run([sys.executable, "-B", "-c", script], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


@pytest.mark.asyncio
@pytest.mark.parametrize("name", [
    "get_lms_deadlines", "get_lms_attendance", "get_lms_course_materials",
    "get_lms_assignments", "get_lms_gradebook", "get_lms_boards", "export_calendar_ics",
])
@pytest.mark.parametrize("course_id", ["", "1&id=2", "１２３", "1" * 21])
async def test_course_ids_rejected_before_account(monkeypatch, name, course_id):
    def forbidden():
        pytest.fail("Invalid input reached credentials")
    monkeypatch.setattr(server, "_account", forbidden)
    with pytest.raises(ValueError):
        await getattr(server, name)(course_id=course_id)


@pytest.mark.asyncio
@pytest.mark.parametrize(("name", "arguments"), [
    ("get_lms_notices", {"scope": "typo"}),
    ("search_notices", {"query": "test", "scope": "typo"}),
    ("search_notices", {"query": "test", "limit": 0}),
    ("search_notices", {"query": "test", "limit": True}),
    ("search_notices", {"query": "test", "limit": 1.5}),
    ("get_grades", {"year": 2025.5}),
    ("get_grades", {"term_code": "typo"}),
    ("get_exam_schedule", {"exam_type": "typo"}),
    ("get_my_schedule", {"days": True}),
    ("get_my_schedule", {"days": 1.5}),
    ("get_my_schedule", {"days": 91}),
    ("search_courses", {"keyword": "test", "limit": True}),
    ("search_courses", {"keyword": "test", "limit": 1.5}),
    ("get_library_notices", {"limit": True}),
    ("get_library_notices", {"limit": 21}),
    ("get_library_seats", {"seat_type": " "}),
])
async def test_invalid_filters_never_reach_account_or_cache(monkeypatch, name, arguments):
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid filter reached credentials/cache")
    monkeypatch.setattr(server, "_account", forbidden)
    monkeypatch.setattr(server.cache, "cached", forbidden)
    with pytest.raises(ValueError):
        await getattr(server, name)(**arguments)


@pytest.mark.asyncio
@pytest.mark.parametrize(("name", "arguments"), [
    ("get_student_profile", {"include_pii": "true"}),
    ("get_lms_gradebook", {"course_id": "123", "include_feedback": 1}),
    ("get_grades", {"year": "2025"}),
    ("search_library_books", {"query": "test", "limit": True}),
])
async def test_mcp_rejects_coercion_before_authentication(monkeypatch, name, arguments):
    def forbidden():
        pytest.fail("Invalid type reached credentials")
    monkeypatch.setattr(server, "_account", forbidden)
    with pytest.raises(ToolError):
        await server.mcp.call_tool(name, arguments)

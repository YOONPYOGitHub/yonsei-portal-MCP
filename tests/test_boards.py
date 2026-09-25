from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from yonsei_portal_mcp.errors import ScrapeFailedError
from yonsei_portal_mcp.scrapers import boards


INDEX = '''<a href="/mod/ubboard/view.php?id=999">Navigation</a>
<table class="ubboard_table"><thead><tr><th>게시판명</th><th>게시물 수</th><th>최근 업데이트일</th></tr></thead>
<tbody><tr><td><a href="/mod/ubboard/view.php?id=123">Announcements</a></td><td>2</td><td>2026-09-25 10:00</td></tr></tbody></table>
<table class="ubboard_table"><thead><tr><th>구분</th><th>게시판명</th><th>게시물 수</th><th>최근 업데이트일</th></tr></thead>
<tbody><tr><td colspan="4">생성된 게시판이 없습니다.</td></tr></tbody></table>'''

POSTS = '''<table class="ubboard_table"><thead><tr><th>번호</th><th>제목</th><th>작성자</th><th>작성일</th><th>조회수</th></tr></thead>
<tbody><tr><td>2</td><td><a href="/mod/ubboard/article.php?id=123&amp;bwid=456">Public post</a></td><td>Private author</td><td>2026-09-25</td><td>12</td></tr>
<tr><td>1</td><td><span>Restricted title</span></td><td>Private student</td><td>2026-09-24</td><td>3</td></tr></tbody></table>'''


def test_boards_only_read_course_tables():
    result = boards.parse_boards(INDEX, "100")
    assert result["count"] == 1
    assert result["boards"] == [{"board_id": "123", "name": "Announcements", "post_count": 2, "updated_raw": "2026-09-25 10:00", "url": "https://ys.learnus.org/mod/ubboard/view.php?id=123"}]
    assert "999" not in str(result)


def test_posts_exclude_authors_and_unlinked_titles():
    result = boards.parse_posts(POSTS, "123")
    assert result["count"] == 1 and result["unlinked_count"] == 1
    assert result["posts"] == [{"post_id": "456", "title": "Public post", "date_raw": "2026-09-25", "url": "https://ys.learnus.org/mod/ubboard/article.php?id=123&bwid=456"}]
    assert "Private" not in str(result) and "Restricted title" not in str(result)


def test_board_titles_exclude_inline_hidden_text_and_links():
    hidden_text = POSTS.replace("Public post</a>", 'Public post<span style="display: none">PRIVATE</span></a>')
    assert boards.parse_posts(hidden_text, "123")["posts"][0]["title"] == "Public post"
    hidden_link = POSTS.replace('<td><a href=', '<td><span style="display:none"><a href=').replace('</a></td>', '</a></span></td>')
    result = boards.parse_posts(hidden_link, "123")
    assert result["posts"] == [] and "Public post" not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize(("fetch", "html", "path"), [
    ("fetch_boards", INDEX, "index.php"), ("fetch_posts", POSTS, "view.php"),
])
async def test_board_read_rechecks_destination_after_wait(monkeypatch, fetch, html, path):
    from yonsei_portal_mcp.scrapers import learnus
    page = SimpleNamespace(url=f"https://ys.learnus.org/mod/ubboard/{path}?id=123", content=AsyncMock(return_value=html))
    async def redirect(*args, **kwargs):
        page.url = f"https://ys.learnus.org/mod/ubboard/{path}?id=999"
    page.wait_for_selector = redirect
    monkeypatch.setattr(learnus, "_goto_korean", AsyncMock())
    with pytest.raises(ScrapeFailedError):
        await getattr(boards, fetch)(page, "123")


@pytest.mark.parametrize("html", ["<h1>Login</h1>", INDEX.replace("게시물 수", "Changed"), INDEX.replace("</td><td>2</td>", "</td><td>unknown</td>")])
def test_boards_reject_unknown_schema(html):
    with pytest.raises(ScrapeFailedError):
        boards.parse_boards(html, "100")


@pytest.mark.parametrize("href", ["https://evil.test/mod/ubboard/article.php?id=123&bwid=456", "/mod/ubboard/article.php?id=999&bwid=456", "/mod/ubboard/delete.php?id=123&bwid=456", "/mod/ubboard/article.php?id=123&bwid=456&bwid=789"])
def test_post_links_keep_board_identity(href):
    html = POSTS.replace("/mod/ubboard/article.php?id=123&amp;bwid=456", href.replace("&", "&amp;"))
    with pytest.raises(ScrapeFailedError):
        boards.parse_posts(html, "123")


def test_posts_only_explicit_empty_is_zero():
    prefix = POSTS.split("<tbody>")[0]
    empty = prefix + '<tbody><tr><td colspan="5">등록된 게시글이 없습니다.</td></tr></tbody></table>'
    assert boards.parse_posts(empty, "123")["count"] == 0
    with pytest.raises(ScrapeFailedError):
        boards.parse_posts(empty.replace("등록된 게시글이 없습니다.", "Loading"), "123")


@pytest.mark.asyncio
@pytest.mark.parametrize("identifier", ["", "123&userid=456", "../1", "１２３"])
async def test_board_inputs_reject_before_browser(identifier):
    with pytest.raises(ValueError):
        await boards.fetch_boards(None, identifier)
    with pytest.raises(ValueError):
        await boards.fetch_posts(None, identifier)


@pytest.mark.asyncio
async def test_board_tools_registered_and_cache_separates_account_and_id(monkeypatch):
    from yonsei_portal_mcp import server, cache

    monkeypatch.setattr(cache, "_cache", cache.TTLCache())
    monkeypatch.setattr(server, "_account", lambda: "account-a")
    names = {tool.name for tool in await server.mcp.list_tools()}
    assert {"get_lms_boards", "get_lms_board_posts"} <= names
    async def run(action):
        return await action(None)
    monkeypatch.setattr(server, "get_session", lambda: SimpleNamespace(run=run))
    fetch = AsyncMock(return_value={"count": 0, "boards": []})
    posts = AsyncMock(return_value={"count": 0, "posts": []})
    monkeypatch.setattr(boards, "fetch_boards", fetch)
    monkeypatch.setattr(boards, "fetch_posts", posts)
    await server.get_lms_boards("100")
    await server.get_lms_boards("100")
    await server.get_lms_boards("101")
    await server.get_lms_board_posts("123")
    await server.get_lms_board_posts("123")
    monkeypatch.setattr(server, "_account", lambda: "account-b")
    await server.get_lms_boards("100")
    assert fetch.await_count == 3 and posts.await_count == 1


@pytest.mark.asyncio
async def test_history_tools_only_expose_verified_options(monkeypatch):
    from yonsei_portal_mcp import server, cache
    from yonsei_portal_mcp.scrapers import library, learnus

    monkeypatch.setattr(cache, "_cache", cache.TTLCache())
    monkeypatch.setattr(server, "_account", lambda: "account-a")
    async def run(action):
        return await action(None)
    monkeypatch.setattr(server, "get_library_session", lambda: SimpleNamespace(run=run))
    monkeypatch.setattr(server, "get_session", lambda: SimpleNamespace(run=run))
    fetch = AsyncMock(return_value={"count": 0, "loans": []})
    reserve = AsyncMock(return_value={"count": 0, "reservations": []})
    courses = AsyncMock(return_value={"count": 0, "courses": []})
    monkeypatch.setattr(library, "fetch_loan_history", fetch)
    monkeypatch.setattr(library, "fetch_reservation_history", reserve)
    monkeypatch.setattr(learnus, "fetch_course_history", courses)
    schemas = {tool.name: tool.inputSchema for tool in await server.mcp.list_tools()}
    assert schemas["get_my_loan_history"]["properties"] == {}
    assert schemas["get_my_reservation_history"]["properties"] == {}
    assert set(schemas["get_lms_course_history"]["properties"]) == {"year", "semester"}
    assert all(schemas[name]["additionalProperties"] is False for name in (
        "get_my_loan_history", "get_my_reservation_history", "get_lms_course_history",
    ))
    await server.get_my_loan_history()
    await server.get_my_loan_history()
    fetch.assert_awaited_once_with(None)
    await server.get_my_reservation_history()
    reserve.assert_awaited_once_with(None)
    await server.get_lms_course_history(year=2026, semester="20")
    courses.assert_awaited_once_with(None, 2026, "20")
    await server.mcp.call_tool("get_my_loan_history", {})
    await server.mcp.call_tool("get_my_reservation_history", {})
    await server.mcp.call_tool("get_lms_course_history", {"year": 2026, "semester": "20"})
    assert fetch.await_count == reserve.await_count == courses.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(("name", "arguments"), [
    ("get_lms_boards", {"course_id": "../1"}),
    ("get_lms_board_posts", {"board_id": "1&userid=2"}),
    ("get_lms_course_history", {"year": 2000}),
])
async def test_extension_inputs_rejected_before_credentials(monkeypatch, name, arguments):
    from yonsei_portal_mcp import server
    def forbidden():
        raise AssertionError("Credentials must not be accessed")
    monkeypatch.setattr(server, "_account", forbidden)
    with pytest.raises(ValueError):
        await getattr(server, name)(**arguments)


@pytest.mark.asyncio
@pytest.mark.parametrize(("name", "arguments"), [
    ("get_my_loan_history", {"start_date": "2026-09-01"}),
    ("get_my_reservation_history", {"page": 2}),
    ("get_lms_course_history", {"page": 2}),
])
async def test_mcp_rejects_unverified_history_arguments_before_credentials(monkeypatch, name, arguments):
    from yonsei_portal_mcp import server
    from mcp.server.fastmcp.exceptions import ToolError
    account = Mock()
    def forbidden():
        account()
        raise AssertionError("Credentials must not be accessed")
    monkeypatch.setattr(server, "_account", forbidden)
    with pytest.raises(ToolError):
        await server.mcp.call_tool(name, arguments)
    assert account.call_count == 0


@pytest.mark.asyncio
async def test_unverified_history_inputs_are_rejected_over_stdio():
    import os
    import sys
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=sys.executable, args=["-m", "yonsei_portal_mcp"],
        env={"PYTHON_DOTENV_DISABLED": "1", "YONSEI_ID": "", "YONSEI_PASSWORD": ""},
    )
    with open(os.devnull, "w") as errlog:
        async with stdio_client(params, errlog=errlog) as streams:
            async with ClientSession(*streams) as client:
                await client.initialize()
                for name, arguments in (
                    ("get_my_loan_history", {"start_date": "2026-09-01"}),
                    ("get_my_reservation_history", {"page": 2}),
                    ("get_lms_course_history", {"page": 1}),
                ):
                    result = await client.call_tool(name, arguments)
                    assert result.isError
                    assert any("지원하지 않는 이력 조회 인자" in getattr(part, "text", "") for part in result.content)


@pytest.mark.asyncio
async def test_history_argument_validation_does_not_echo_rejected_value():
    from yonsei_portal_mcp import server
    from mcp.server.fastmcp.exceptions import ToolError
    with pytest.raises(ToolError) as caught:
        await server.mcp.call_tool("get_lms_course_history", {"year": "PRIVATE_SENTINEL"})
    assert "PRIVATE_SENTINEL" not in str(caught.value)


@pytest.mark.asyncio
async def test_board_scenario_rejects_unrequested_body_read(monkeypatch):
    from tests.llm import scenarios
    from tests.llm.mcp_host import AgentRun
    from tests.llm.providers import ToolCall
    result = AgentRun(final_text="Synthetic result", tool_calls=[
        ToolCall("first", "get_lms_board_posts", {"board_id": "123"}),
        ToolCall("second", "get_notice", {"url": "https://ys.learnus.org/mod/ubboard/article.php?id=123&bwid=456"}),
    ])
    monkeypatch.setattr(scenarios, "run_agent", AsyncMock(return_value=result))
    response = await scenarios._run_one(None, None, "Synthetic question", scenario_id="board_posts")
    assert response["error"] is not None
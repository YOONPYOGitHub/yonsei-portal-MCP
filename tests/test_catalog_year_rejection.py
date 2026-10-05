"""Offline year-commit regressions using Playwright's real async event context."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from playwright._impl._async_base import AsyncEventContextManager
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from yonsei_portal_mcp.config import Settings
from yonsei_portal_mcp.errors import ScrapeFailedError
from yonsei_portal_mcp.scrapers import erp
from yonsei_portal_mcp.session import BrowserSession


YEAR_URL = "https://underwood1.yonsei.ac.kr/sch/sles/SlescsCtr/findSchSlesHandbList.do"
SEARCH_URL = "https://underwood1.yonsei.ac.kr/sch/sles/SlessyCtr/findAtnlcHandbList.do"
YEAR_ERROR = "수강편람 요청 연도가 화면에 반영되지 않았습니다."


class ObservedResponseContext(AsyncEventContextManager):
    """Keep real Playwright cancellation/wait semantics, observing context exit."""

    def __init__(self, predicate, timeout):
        self.future = asyncio.get_running_loop().create_future()
        super().__init__(self.future)
        self.predicate = predicate
        self.timeout = timeout
        self.exit_error = None
        self.normal_exits = 0
        # Compress only the synthetic timeout; production timeout is asserted.
        self.timer = asyncio.get_running_loop().call_later(0.1, self.expire)

    def expire(self):
        if not self.future.done():
            self.future.set_exception(PlaywrightTimeoutError("synthetic response timeout"))

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.exit_error = exc_val
        self.normal_exits += exc_val is None
        try:
            return await super().__aexit__(exc_type, exc_val, exc_tb)
        finally:
            self.timer.cancel()


class YearInput:
    def __init__(self, page, current, reject):
        self.page = page
        self.current = current
        self.original = current
        self.reject = reject
        self.events = []

    async def input_value(self):
        self.events.append(("read", self.current))
        return self.current

    async def click(self):
        self.events.append(("click", self.current))

    async def press_sequentially(self, value):
        self.current = value
        self.events.append(("type", value))

    async def press(self, key):
        self.events.append(("press", key))
        if key == "Tab":
            if self.reject:
                self.current = self.original
            else:
                self.page.emit(self.page.year_response)


class CatalogPage:
    def __init__(self, *, current="2026", requested="2027", reject=False, server_year=None):
        self.contexts = []
        self.year = YearInput(self, current, reject)
        self.year_response = SimpleNamespace(
            url=YEAR_URL, request=SimpleNamespace(post_data_json={"@d1#syy": requested}),
            finished=AsyncMock(),
        )
        actual = requested if server_year is None else server_year
        self.search_response = SimpleNamespace(
            url=SEARCH_URL, ok=True,
            request=SimpleNamespace(post_data_json={
                "@d1#kwd": "AI", "@d1#searchGbn": "2", "@d1#kwdDivCd": "2",
                "@d1#syy": actual, "@d1#smtDivCd": "10", "@d1#campsBusnsCd": "s3",
            }),
            json=AsyncMock(return_value={"dsSles251": [{
                "subjtnb": "SYNTH101", "subjtNm": "Synthetic AI", "corseDvclsNo": "01",
                "syy": actual, "smtDivCd": "10", "campsBusnsCd": "s3",
            }]}),
        )
        self.keyword = SimpleNamespace(fill=AsyncMock())
        self.keyword_type = SimpleNamespace(
            focus=AsyncMock(), press=AsyncMock(), input_value=AsyncMock(return_value="교과목명"),
        )
        self.combos = SimpleNamespace(
            last=self.keyword_type,
            nth=lambda index: SimpleNamespace(input_value=AsyncMock(return_value=("1학기", "대학원(신촌)")[index])),
        )
        self.search_click = AsyncMock(side_effect=lambda: self.emit(self.search_response))
        self.close = AsyncMock()

    def locator(self, selector):
        if 'role="spinbutton"' in selector:
            return self.year
        if 'role="combobox"' in selector:
            return self.combos
        assert selector == '.div_search input:not([role]):visible'
        return SimpleNamespace(nth=lambda index: self.keyword)

    def get_by_text(self, text, *, exact):
        assert text == "조회" and exact
        return SimpleNamespace(last=SimpleNamespace(click=self.search_click))

    def expect_response(self, predicate, *, timeout):
        context = ObservedResponseContext(predicate, timeout)
        self.contexts.append(context)
        return context

    def emit(self, response):
        for context in self.contexts:
            if not context.future.done() and context.predicate(response):
                context.future.set_result(response)


@pytest.fixture
def catalog_session(monkeypatch, tmp_path):
    monkeypatch.setattr(erp, "_open_menu_and_capture", AsyncMock())

    def make(page):
        settings = Settings("", "", False, tmp_path / "synthetic-state.json")
        session = BrowserSession(settings, settings.storage_state_path)
        session.start = AsyncMock()
        monkeypatch.setattr(session, "_context", SimpleNamespace(new_page=AsyncMock(return_value=page)))
        session._is_authenticated = AsyncMock(return_value=True)
        session._login = AsyncMock()
        session._invalidate_session = AsyncMock()
        return session

    return make


async def test_rejected_year_cancels_response_context_without_session_retry(catalog_session):
    page = CatalogPage(reject=True)
    session = catalog_session(page)

    with pytest.raises(ScrapeFailedError, match=YEAR_ERROR) as caught:
        await session.run(lambda p: erp.fetch_course_catalog(p, "AI", year=2027, term_code="10", campus_code="s3"))

    assert caught.value.code == "SCRAPE_FAILED"
    assert caught.value.message == YEAR_ERROR
    assert page.year.events == [
        ("read", "2026"), ("click", "2026"), ("press", "ControlOrMeta+A"),
        ("type", "2027"), ("press", "Tab"), ("read", "2026"),
    ]
    assert len(page.contexts) == 1
    context = page.contexts[0]
    assert context.timeout == 20_000
    assert context.exit_error is caught.value
    assert context.normal_exits == 0
    assert context.future.cancelled()
    page.year_response.finished.assert_not_awaited()
    page.search_click.assert_not_awaited()
    page.search_response.json.assert_not_awaited()
    session._invalidate_session.assert_not_awaited()
    session._login.assert_not_awaited()
    session.start.assert_awaited_once()
    page.close.assert_awaited_once()


@pytest.mark.parametrize("current", ["2026", "2025"])
async def test_valid_and_already_selected_year_keep_verified_catalog_flow(catalog_session, current):
    page = CatalogPage(current=current, requested="2025")
    session = catalog_session(page)

    result = await session.run(lambda p: erp.fetch_course_catalog(p, "AI", year=2025, term_code="10", campus_code="s3"))

    assert result["requested_filters"] == {"year": 2025, "term_code": "10", "campus_code": "s3"}
    assert result["filters"]["year"] == "2025"
    assert result["courses"][0]["year"] == "2025"
    assert result["count"] == 1
    assert result["result_status"] == "ok"
    assert result["warnings"] == []
    assert all(field["status"] == "matched" for field in result["filter_consistency"]["fields"].values())
    if current == "2025":
        assert page.year.events == [("read", "2025")]
        assert len(page.contexts) == 1
        page.year_response.finished.assert_not_awaited()
    else:
        assert page.year.events[-3:] == [("type", "2025"), ("press", "Tab"), ("read", "2025")]
        assert len(page.contexts) == 2
        page.year_response.finished.assert_awaited_once()
        context = page.contexts[0]
        assert context.timeout == 20_000
        assert context.predicate(page.year_response)
        for url, year in [
            (YEAR_URL, "2026"),
            (YEAR_URL.replace("https://", "http://"), "2025"),
            (YEAR_URL.replace("underwood1.yonsei.ac.kr", "example.test"), "2025"),
            (YEAR_URL + "/unexpected", "2025"),
        ]:
            assert not context.predicate(SimpleNamespace(url=url, request=SimpleNamespace(post_data_json={"@d1#syy": year})))
    assert page.contexts[-1].timeout == 45_000
    assert all(context.normal_exits == 1 and context.exit_error is None for context in page.contexts)
    assert all(context.future.done() and not context.future.cancelled() for context in page.contexts)
    page.search_click.assert_awaited_once()
    session._invalidate_session.assert_not_awaited()
    session._login.assert_not_awaited()


async def test_accepted_ui_year_still_requires_matching_server_conditions(catalog_session):
    page = CatalogPage(requested="2025", server_year="2026")
    session = catalog_session(page)

    with pytest.raises(ScrapeFailedError, match="요청 필터와 서버 조회 조건"):
        await session.run(lambda p: erp.fetch_course_catalog(p, "AI", year=2025))

    page.year_response.finished.assert_awaited_once()
    page.search_click.assert_awaited_once()
    page.search_response.json.assert_not_awaited()
    session._invalidate_session.assert_not_awaited()


async def test_mcp_year_rejection_is_scrape_error_not_empty_data_or_auth(catalog_session, monkeypatch):
    from mcp.server.fastmcp.exceptions import ToolError
    from yonsei_portal_mcp import cache, server

    page = CatalogPage(reject=True)
    session = catalog_session(page)
    monkeypatch.setattr(server, "get_erp_session", lambda: session)
    monkeypatch.setattr(server, "_account", lambda: "synthetic-year-rejection")
    cache.clear()
    try:
        with pytest.raises(ToolError, match=r"\[SCRAPE_FAILED\]") as caught:
            await server.mcp.call_tool("search_courses", {
                "keyword": "AI", "year": 2027, "term_code": "10", "campus_code": "s3",
            })
        assert YEAR_ERROR in str(caught.value)
        assert "SESSION_EXPIRED" not in str(caught.value)
        assert "AUTH" not in str(caught.value)
        assert "source_empty" not in str(caught.value)
        assert len(page.contexts) == 1 and page.contexts[0].future.cancelled()
        assert page.contexts[0].normal_exits == 0
        page.search_click.assert_not_awaited()
        session._invalidate_session.assert_not_awaited()
        session._login.assert_not_awaited()
        session.start.assert_awaited_once()
    finally:
        cache.clear()


async def test_mcp_protocol_returns_error_instead_of_zero_courses(catalog_session, monkeypatch):
    from mcp.shared.memory import create_connected_server_and_client_session
    from yonsei_portal_mcp import cache, server

    page = CatalogPage(reject=True)
    session = catalog_session(page)
    monkeypatch.setattr(server, "get_erp_session", lambda: session)
    monkeypatch.setattr(server, "_account", lambda: "synthetic-year-protocol")
    monkeypatch.setattr(server, "close_sessions", AsyncMock())
    cache.clear()
    try:
        async with create_connected_server_and_client_session(server.mcp) as client:
            result = await client.call_tool("search_courses", {
                "keyword": "AI", "year": 2027, "term_code": "10", "campus_code": "s3",
            })
        assert result.isError is True
        assert result.structuredContent is None
        assert len(result.content) == 1
        assert result.content[0].type == "text"
        text = result.content[0].text
        assert "[SCRAPE_FAILED] " + YEAR_ERROR in text
        assert "SESSION_EXPIRED" not in text and "AUTH" not in text
        assert len(page.contexts) == 1 and page.contexts[0].future.cancelled()
        assert page.contexts[0].normal_exits == 0
        page.search_click.assert_not_awaited()
        session._invalidate_session.assert_not_awaited()
        session._login.assert_not_awaited()
        session.start.assert_awaited_once()
    finally:
        cache.clear()

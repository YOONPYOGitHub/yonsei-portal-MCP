"""MCP wiring contracts: synthetic data only, no account configuration required."""
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from yonsei_portal_mcp import server, cache
from yonsei_portal_mcp.scrapers import boards, university


@pytest.mark.asyncio
async def test_new_public_sources_and_bounded_board_search_are_registered(monkeypatch):
    tools = {tool.name: tool for tool in await server.mcp.list_tools()}
    expected = {"list_notice_sources", "get_university_notices", "get_university_notice", "search_lms_board_posts"}
    assert expected <= tools.keys()
    for name in expected:
        assert tools[name].annotations.readOnlyHint is True
        assert tools[name].inputSchema.get("additionalProperties") is False
    monkeypatch.setattr(server, "_account", lambda: pytest.fail("public notice must not read credentials"))
    cache.clear()
    fake_list = AsyncMock(return_value={"notices": [], "synthetic": True})
    fake_detail = AsyncMock(return_value={"body": "synthetic"})
    monkeypatch.setattr(university, "fetch_notices", fake_list)
    monkeypatch.setattr(university, "fetch_notice", fake_detail)
    try:
        sources = await server.list_notice_sources()
        assert sources["count"] == len(sources["sources"]) == 3
        assert await server.get_university_notices("university", page=2, limit=20) == {"notices": [], "synthetic": True}
        assert await server.get_university_notice("graduate", "456") == {"body": "synthetic"}
        fake_list.assert_awaited_once_with("university", 2, 20)
        fake_detail.assert_awaited_once_with("graduate", "456")
    finally:
        cache.clear()


@pytest.mark.asyncio
async def test_new_tools_validate_before_account_cache_or_fetch(monkeypatch):
    monkeypatch.setattr(server, "_account", lambda: pytest.fail("validation must precede account"))
    monkeypatch.setattr(cache, "cached", lambda *a: pytest.fail("validation must precede cache"))
    for args in [("bad", 1, 10), ("university", True, 10), ("graduate", 1, 0)]:
        with pytest.raises(ValueError):
            await server.get_university_notices(*args)
    for args in [("bad", "123"), ("graduate", "00123")]:
        with pytest.raises(ValueError):
            await server.get_university_notice(*args)
    for args in [("123", " ", 3, 20), ("123", "시험", True, 20), ("123", "시험", 3, 0)]:
        with pytest.raises(ValueError):
            await server.search_lms_board_posts(*args)


@pytest.mark.asyncio
async def test_board_title_search_is_account_scoped_and_cached(monkeypatch):
    async def run(action):
        return await action(None)
    monkeypatch.setattr(server, "_account", lambda: "synthetic")
    monkeypatch.setattr(server, "get_session", lambda: SimpleNamespace(run=run))
    fake = AsyncMock(return_value={"count": 0, "has_more_pages": True})
    monkeypatch.setattr(boards, "search_posts", fake)
    cache.clear()
    try:
        for _ in range(2):
            assert (await server.search_lms_board_posts("123", "시험", max_pages=2))["has_more_pages"] is True
        fake.assert_awaited_once_with(None, "123", "시험", 2, 20)
    finally:
        cache.clear()

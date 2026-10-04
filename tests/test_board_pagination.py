"""Synthetic LearnUs paging contracts; no account data or network calls."""
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from yonsei_portal_mcp.errors import ScrapeFailedError
from yonsei_portal_mcp.scrapers import boards


def table(post_id="456", hint=""):
    return ('<table class="ubboard_table"><thead><tr>'
            '<th>번호</th><th>제목</th><th>작성자</th><th>작성일</th><th>조회수</th>'
            '</tr></thead><tbody><tr><td>1</td><td>'
            f'<a href="/mod/ubboard/article.php?id=123&amp;bwid={post_id}{hint}">시험 안내</a>'
            '</td><td>DO NOT RETURN AUTHOR</td><td>2026-01-01</td><td>1</td>'
            '</tr></tbody></table>')


def pager(current):
    return '<ul class="pagination">' + ''.join(
        f'<li class="page-item {"active" if n == current else ""}"><a href="'
        + ('#' if n == current else f'https://ys.learnus.org/mod/ubboard/view.php?id=123&amp;lang=ko&amp;page={n}')
        + f'" class="page-link">{n}</a></li>' for n in (1, 2)
    ) + '</ul>'


def test_first_page_returns_verified_next_request():
    result = boards.parse_posts(table() + pager(1), "123")
    assert result["page"] == 1
    assert result["has_next"] is True
    assert result["next_request"] == {"board_id": "123", "page": 2}
    assert "DO NOT RETURN AUTHOR" not in str(result)


def test_second_page_keeps_article_identity_not_navigation_hint():
    result = boards.parse_posts(table("457", "&amp;page=2") + pager(2), "123", page_number=2)
    assert result["posts"][0]["url"] == "https://ys.learnus.org/mod/ubboard/article.php?id=123&bwid=457"
    assert result["page"] == 2 and result["has_next"] is False
    assert result["next_request"] is None


def post(identifier, title):
    return {"post_id": identifier, "title": title, "date_raw": "2026-01-01",
            "url": f"https://ys.learnus.org/mod/ubboard/article.php?id=123&bwid={identifier}"}


@pytest.mark.asyncio
async def test_title_search_follows_pages_and_deduplicates_pinned_posts(monkeypatch):
    calls = []
    async def fetch(browser, board_id, page_number=1):
        calls.append(page_number)
        rows = ([post("1", "시험 안내"), post("2", "과제 안내")] if page_number == 1
                else [post("1", "시험 안내"), post("3", "기말 시험")])
        return {"page": page_number, "posts": rows, "unlinked_count": 0,
                "has_next": page_number == 1, "next_page": 2 if page_number == 1 else None,
                "next_request": {"board_id": board_id, "page": 2} if page_number == 1 else None,
                "source_url": "https://ys.learnus.org/mod/ubboard/view.php?id=123"}
    monkeypatch.setattr(boards, "fetch_posts", fetch)
    result = await boards.search_posts(None, "123", "시험", max_pages=3, limit=1)
    assert calls == [1, 2]
    assert result["matching_count"] == 2 and result["count"] == 1
    assert result["scanned_posts"] == 3 and result["duplicates_removed"] == 1
    assert result["has_more_pages"] is False and result["result_truncated"] is True
    calls.clear()
    result = await boards.search_posts(None, "123", "기말", max_pages=1)
    assert calls == [1] and result["count"] == 0 and result["has_more_pages"] is True
    assert result["next_request"]["arguments"] == {"board_id": "123", "page": 2}


@pytest.mark.asyncio
async def test_title_search_does_not_hide_a_later_page_error(monkeypatch):
    async def fetch(browser, board_id, page_number=1):
        if page_number == 2:
            raise ScrapeFailedError("synthetic failure")
        return {"page": 1, "posts": [post("1", "시험")], "unlinked_count": 0,
                "has_next": True, "next_page": 2, "next_request": {"board_id": board_id, "page": 2}}
    monkeypatch.setattr(boards, "fetch_posts", fetch)
    with pytest.raises(ScrapeFailedError):
        await boards.search_posts(None, "123", "시험")


@pytest.mark.parametrize("href", [
    "https://evil.invalid/view.php?id=123&page=2",
    "/mod/ubboard/view.php?id=999&page=2",
    "/mod/ubboard/view.php?id=123&page=2&page=3",
    "/mod/ubboard/view.php?id=123&page=0",
    "/mod/ubboard/view.php?id=123&page=02",
    "/mod/ubboard/view.php?id=123&page=2&action=delete",
])
def test_paginator_rejects_unverified_navigation(href):
    html = pager(1).replace('https://ys.learnus.org/mod/ubboard/view.php?id=123&amp;lang=ko&amp;page=2', href.replace('&', '&amp;'))
    with pytest.raises(ScrapeFailedError):
        boards.parse_posts(table() + html, "123")


def test_wrong_or_missing_active_page_is_not_an_empty_page():
    for html in (table() + pager(1), table()):
        with pytest.raises(ScrapeFailedError):
            boards.parse_posts(html, "123", page_number=2)


@pytest.mark.asyncio
@pytest.mark.parametrize("page_number", [0, 101, True, 1.5, "2"])
async def test_page_bounds_reject_before_browser(page_number):
    with pytest.raises(ValueError):
        await boards.fetch_posts(None, "123", page_number)


@pytest.mark.asyncio
async def test_mcp_page_validation_and_cache_include_page(monkeypatch):
    from yonsei_portal_mcp import server, cache
    cache.clear()
    calls = []
    async def fetch(browser_page, board_id, page_number=1):
        calls.append(page_number)
        return {"synthetic": page_number}
    async def run(action):
        return await action(None)
    monkeypatch.setattr(server, "_account", lambda: "synthetic")
    monkeypatch.setattr(server, "get_session", lambda: SimpleNamespace(run=run))
    monkeypatch.setattr(boards, "fetch_posts", fetch)
    try:
        assert await server.get_lms_board_posts("123") == {"synthetic": 1}
        assert await server.get_lms_board_posts("123", page=2) == {"synthetic": 2}
        await server.get_lms_board_posts("123", page=2)
        assert calls == [1, 2]
    finally:
        cache.clear()

"""Synthetic public-board fixtures only; no live calls or school credentials."""
import importlib
import importlib.util
from unittest.mock import AsyncMock

import pytest


def module():
    assert importlib.util.find_spec("yonsei_portal_mcp.scrapers.university") is not None, "public notice scraper is missing"
    return importlib.import_module("yonsei_portal_mcp.scrapers.university")


def test_curated_sources_are_detached_from_immutable_registry():
    u = module()
    result = u.list_sources()
    assert result["count"] == len(result["sources"]) == 3
    assert {s["source"] for s in result["sources"]} == {"university", "graduate", "ai_graduate"}
    assert all(s["label"] and s["description"] and s["source_url"].startswith("https://") for s in result["sources"])
    result["sources"][0]["source_url"] = "https://evil.test"
    assert "evil.test" not in str(u.list_sources())
    with pytest.raises(TypeError):
        u._SOURCES["evil"] = object()


MAIN_ROW = '''<li class="board-noti"><a href="/bbs/sc/58/123/artclView.do"><div class="con"><div class="title"><strong>합성 공지</strong></div><div class="info"><div class="date-area"><span>작성일</span>2026.10.02</div><div class="etc-area">PRIVATE AUTHOR</div></div></div></a></li>'''
MAIN_LIST = '<nav>PRIVATE NAV</nav><div class="board-list"><div class="srch_counts">총 25 개의 게시물</div><div class="boardWrap"><ul>' + MAIN_ROW + MAIN_ROW + '</ul></div><div class="_paging"><span class="_curPage">1</span><span class="_totPage">3</span><a href="javascript:page_link(\'2\')">2</a></div></div>'


@pytest.mark.asyncio
async def test_university_list_scopes_deduplicates_and_reports_verified_paging(monkeypatch):
    u = module()
    get = AsyncMock(return_value=MAIN_LIST)
    monkeypatch.setattr(u.httpclient, "get_html", get)
    result = await u.fetch_notices("university")
    assert result["count"] == len(result["notices"]) == 1
    assert result["notices"][0] == {"notice_id": "123", "title": "합성 공지", "date_raw": "2026.10.02", "url": "https://www.yonsei.ac.kr/bbs/sc/58/123/artclView.do", "pinned": True}
    assert "PRIVATE" not in str(result)
    assert result["source"]["source"] == "university" and result["fetched_at"]
    assert result["pagination"]["has_next"] is True
    assert result["pagination"]["next_request"] == {"source": "university", "page": 2, "limit": 10}
    assert result["pagination"]["total"] == 25
    assert result["pagination"]["complete_history"] is False
    get.assert_awaited_once_with("https://www.yonsei.ac.kr/bbs/sc/58/artclList.do", params={"page": 1}, same_path=True)


GRAD_ROW = '''<tr class="c-board-top-wrap"><td>공지</td><td class="text-left"><a class="c-board-title" href="?mode=view&amp;articleNo=456&amp;article.offset=10&amp;articleLimit=10"><span class="c-board-top-num-m">[공지]</span>대학원 합성 공지</a><div class="c-board-info-m"><span>PRIVATE AUTHOR</span><span>2026.10.01</span></div></td><td>PRIVATE AUTHOR</td><td>26.10.01</td></tr>'''
GRAD_LIST = '<div class="board-wrap"><table class="board-table"><thead><tr><th>번호</th><th>제목</th><th>작성자</th><th>등록일</th></tr></thead><tbody>' + GRAD_ROW + GRAD_ROW + '</tbody></table><ul class="paging-wrap"><li><a class="active" href="#curPage">2</a></li><li><a href="?mode=list&amp;&amp;articleLimit=10&amp;article.offset=20">3</a></li><li><a class="page-last" href="?mode=list&amp;articleLimit=10&amp;article.offset=40">끝</a></li></ul></div>'


@pytest.mark.asyncio
@pytest.mark.parametrize("source,path", [("graduate", "graduate/board/notice.do"), ("ai_graduate", "gcomputing/community/noticeBoard.do")])
async def test_graduate_list_uses_observed_offset_and_scoped_fields(monkeypatch, source, path):
    u = module()
    get = AsyncMock(return_value=GRAD_LIST)
    monkeypatch.setattr(u.httpclient, "get_html", get)
    result = await u.fetch_notices(source, page=2)
    get.assert_awaited_once_with("https://graduate.yonsei.ac.kr/" + path, params={"mode": "list", "articleLimit": 10, "article.offset": 10}, same_path=True)
    assert result["count"] == 1
    assert result["notices"][0] == {"notice_id": "456", "title": "대학원 합성 공지", "date_raw": "2026.10.01", "pinned": True, "url": "https://graduate.yonsei.ac.kr/" + path + "?mode=view&articleNo=456"}
    assert "PRIVATE" not in str(result)
    assert result["pagination"]["has_next"] is True
    assert result["pagination"]["next_request"] == {"source": source, "page": 3, "limit": 10}
    assert "total" not in result["pagination"]


MAIN_DETAIL = '<header>PRIVATE NAV</header><div class="board-view"><input id="clip_tmp" value="https://www.yonsei.ac.kr/bbs/sc/58/123/artclView.do?layout=unknown"><div class="viewCont"><div class="title"><strong>합성 상세</strong><ul class="detail"><li><span>작성자</span>PRIVATE AUTHOR</li><li><span>작성일</span>2026.10.02</li></ul></div><div class="txt"><p>공개 본문</p><img src="/image.png"></div><div class="attachment"><a href="/bbs/sc/58/987/download.do">안내.pdf</a><a href="https://evil.test/file.pdf">위험.pdf</a></div></div></div>'
GRAD_DETAIL = '<div class="ys-board view"><div class="board-wrap"><input name="articleNo" value="456"><div class="board-write-wrap"><dl class="board-write-box"><dt>제목</dt><dd>합성 상세</dd></dl><dl class="board-write-box"><dt>작성자</dt><dd>PRIVATE AUTHOR</dd></dl><dl class="board-write-box"><dt>작성일</dt><dd>2026.10.02</dd></dl><dl class="board-write-box"><dt>게시글 내용</dt><dd><div class="fr-view"><p>공개 본문</p><img src="/image.png"></div></dd></dl><dl><dt>첨부</dt><dd><a class="file-down-btn" href="?mode=download&amp;articleNo=456&amp;attachNo=987">안내.pdf</a><a class="file-down-btn" href="https://evil.test/file.pdf">위험.pdf</a></dd></dl></div></div></div><footer>PRIVATE NAV</footer>'


@pytest.mark.asyncio
@pytest.mark.parametrize("source,notice_id,html", [("university", "123", MAIN_DETAIL), ("graduate", "456", GRAD_DETAIL), ("ai_graduate", "456", GRAD_DETAIL)])
async def test_detail_scopes_content_and_only_returns_validated_attachment_metadata(monkeypatch, source, notice_id, html):
    u = module()
    get = AsyncMock(return_value=html)
    monkeypatch.setattr(u.httpclient, "get_html", get)
    result = await u.fetch_notice(source, notice_id)
    assert result["notice_id"] == notice_id
    assert result["title"] == "합성 상세" and result["date_raw"] == "2026.10.02"
    assert result["body"] == "공개 본문" and result["has_images"] is True
    assert "OCR" in result["content_note"]
    assert "PRIVATE" not in str(result) and "evil.test" not in str(result)
    assert len(result["attachments"]) == 1 and result["attachments"][0]["name"] == "안내.pdf"
    assert result["attachments"][0]["url"].startswith(result["source"]["source_url"].split("/", 3)[0] + "//")
    assert result["fetched_at"] and result["source_url"]
    assert get.await_count == 1  # Never fetch images or attachments.


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs", [{"source": "https://evil.test"}, {"source": "Graduate"}, {"source": []}, {"source": "graduate", "page": 0}, {"source": "graduate", "page": 1001}, {"source": "graduate", "page": True}, {"source": "graduate", "page": "2"}, {"source": "graduate", "limit": 0}, {"source": "graduate", "limit": 101}, {"source": "graduate", "limit": False}, {"source": "graduate", "limit": 1.5}])
async def test_list_invalid_inputs_fail_before_network(monkeypatch, kwargs):
    u = module()
    get = AsyncMock(return_value=GRAD_LIST)
    monkeypatch.setattr(u.httpclient, "get_html", get)
    with pytest.raises(ValueError):
        await u.fetch_notices(**kwargs)
    get.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("notice_id", ["", "0", "01", "123/../../", "1&mode=delete", "１２３", "123\n", " 123", "1" * 13, 123, True, None])
async def test_detail_ids_are_literal_ascii_positive_ids(monkeypatch, notice_id):
    u = module()
    get = AsyncMock(return_value=MAIN_DETAIL)
    monkeypatch.setattr(u.httpclient, "get_html", get)
    with pytest.raises(ValueError):
        await u.fetch_notice("university", notice_id)
    get.assert_not_awaited()


@pytest.mark.asyncio
async def test_detail_rejects_unknown_source_before_network(monkeypatch):
    u = module()
    get = AsyncMock(return_value=MAIN_DETAIL)
    monkeypatch.setattr(u.httpclient, "get_html", get)
    with pytest.raises(ValueError):
        await u.fetch_notice("https://evil.test", "123")
    get.assert_not_awaited()


@pytest.mark.asyncio
async def test_graduate_paging_is_sibling_of_table_wrapper(monkeypatch):
    u = module()
    html = '<div class="ys-board list">' + GRAD_LIST.replace('</table><ul', '</table></div><ul').removesuffix('</div>') + '</div>'
    monkeypatch.setattr(u.httpclient, "get_html", AsyncMock(return_value=html))
    result = await u.fetch_notices("graduate", page=2)
    assert result["pagination"]["has_next"] is True
    assert result["pagination"]["next_request"]["page"] == 3


@pytest.mark.asyncio
async def test_limit_explicitly_reports_local_truncation_without_losing_recovery(monkeypatch):
    u = module()
    html = MAIN_LIST.replace(MAIN_ROW + MAIN_ROW, MAIN_ROW + MAIN_ROW.replace('/123/', '/124/'))
    monkeypatch.setattr(u.httpclient, "get_html", AsyncMock(return_value=html))
    result = await u.fetch_notices("university", limit=1)
    assert result["count"] == len(result["notices"]) == 1
    paging = result["pagination"]
    assert paging["available_count"] == 2 and paging["truncated"] is True
    assert paging["same_page_request"] == {"source": "university", "page": 1, "limit": 2}
    assert paging["next_request"] == {"source": "university", "page": 2, "limit": 1}
    assert "상단 고정" in paging["note"]


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["university", "graduate", "ai_graduate"])
async def test_duplicate_rows_still_validate_date(monkeypatch, source):
    u = module()
    main = source == "university"
    row, html = (MAIN_ROW, MAIN_LIST) if main else (GRAD_ROW, GRAD_LIST)
    malformed = row.replace("2026.10.02" if main else "2026.10.01", "INVALID DATE")
    monkeypatch.setattr(u.httpclient, "get_html", AsyncMock(return_value=html.replace(row + row, row + malformed)))
    with pytest.raises(u.ScrapeFailedError, match="작성일"):
        await u.fetch_notices(source, page=1 if main else 2)


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["university", "graduate", "ai_graduate"])
@pytest.mark.parametrize("field", ["title", "date"])
async def test_duplicate_rows_reject_conflicting_stable_fields(monkeypatch, source, field):
    u = module()
    main = source == "university"
    row, html = (MAIN_ROW, MAIN_LIST) if main else (GRAD_ROW, GRAD_LIST)
    changed = row.replace("합성 공지", "DIFFERENT TITLE") if field == "title" else row.replace("2026.10.02" if main else "2026.10.01", "2026.09.30")
    monkeypatch.setattr(u.httpclient, "get_html", AsyncMock(return_value=html.replace(row + row, row + changed)))
    with pytest.raises(u.ScrapeFailedError):
        await u.fetch_notices(source, page=1 if main else 2)


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["university", "graduate", "ai_graduate"])
@pytest.mark.parametrize("pinned_first", [True, False])
async def test_duplicate_pinned_presentation_merges_without_reordering(monkeypatch, source, pinned_first):
    u = module()
    main = source == "university"
    row, html = (MAIN_ROW, MAIN_LIST) if main else (GRAD_ROW, GRAD_LIST)
    regular = row.replace('class="board-noti"' if main else 'class="c-board-top-wrap"', '')
    if not main:
        regular = regular.replace('<span class="c-board-top-num-m">[공지]</span>', '').replace('&amp;article.offset=10&amp;articleLimit=10', '')
    other = regular.replace('/123/', '/124/') if main else regular.replace('articleNo=456', 'articleNo=457')
    rows = row + other + regular if pinned_first else regular + other + row
    monkeypatch.setattr(u.httpclient, "get_html", AsyncMock(return_value=html.replace(row + row, rows)))
    result = await u.fetch_notices(source, page=1 if main else 2)
    assert result["count"] == result["pagination"]["available_count"] == 2
    assert [item["notice_id"] for item in result["notices"]] == (["123", "124"] if main else ["456", "457"])
    assert result["notices"][0]["pinned"] is True
    assert result["notices"][1]["pinned"] is False
    assert result["notices"][0]["title"] == ("합성 공지" if main else "대학원 합성 공지")


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["university", "graduate", "ai_graduate"])
async def test_duplicate_rows_cannot_change_board_url(monkeypatch, source):
    u = module()
    main = source == "university"
    row, html = (MAIN_ROW, MAIN_LIST) if main else (GRAD_ROW, GRAD_LIST)
    changed = row.replace('/bbs/sc/58/123/', '/bbs/sc/99/123/') if main else row.replace('?mode=view', '/other/notice.do?mode=view')
    monkeypatch.setattr(u.httpclient, "get_html", AsyncMock(return_value=html.replace(row + row, row + changed)))
    with pytest.raises(u.ScrapeFailedError):
        await u.fetch_notices(source, page=1 if main else 2)


@pytest.mark.asyncio
async def test_missing_paging_is_unknown_not_false(monkeypatch):
    u = module()
    html = '<div class="board-list"><div class="boardWrap"><ul>' + MAIN_ROW + '</ul></div></div>'
    monkeypatch.setattr(u.httpclient, "get_html", AsyncMock(return_value=html))
    result = await u.fetch_notices("university")
    assert result["pagination"]["has_next"] is None
    assert result["pagination"]["next_request"] is None
    assert "total" not in result["pagination"]


@pytest.mark.asyncio
@pytest.mark.parametrize("source,html,page", [
    ("university", MAIN_LIST.replace('<span class="_curPage">1</span>', ''), 2),
    ("graduate", GRAD_LIST.replace('class="active"', 'class="unknown"'), 3),
    ("ai_graduate", GRAD_LIST.replace('class="active"', 'class="unknown"'), 3),
], ids=["university", "graduate", "ai_graduate"])
async def test_subsequent_page_requires_current_marker(monkeypatch, source, html, page):
    u = module()
    monkeypatch.setattr(u.httpclient, "get_html", AsyncMock(return_value=html))
    with pytest.raises(u.ScrapeFailedError):
        await u.fetch_notices(source, page=page)


@pytest.mark.asyncio
async def test_current_page_cannot_exceed_displayed_last_page(monkeypatch):
    u = module()
    html = MAIN_LIST.replace('class="_curPage">1', 'class="_curPage">2').replace('class="_totPage">3', 'class="_totPage">1')
    monkeypatch.setattr(u.httpclient, "get_html", AsyncMock(return_value=html))
    with pytest.raises(u.ScrapeFailedError):
        await u.fetch_notices("university", page=2)


@pytest.mark.asyncio
async def test_repeated_or_clamped_upstream_page_is_error(monkeypatch):
    u = module()
    monkeypatch.setattr(u.httpclient, "get_html", AsyncMock(return_value=MAIN_LIST))
    with pytest.raises(u.ScrapeFailedError):
        await u.fetch_notices("university", page=2)


@pytest.mark.asyncio
@pytest.mark.parametrize("href", ["https://evil.test/x?mode=view&articleNo=456", "//evil.test/x?mode=view&articleNo=456", "https://graduate.yonsei.ac.kr/other?mode=view&articleNo=456", "?mode=delete&articleNo=456", "?mode=view&articleNo=456&articleNo=789", "?mode=view&articleNo=456&unexpected=1", "?mode=view&articleNo=%34%35%36", " ?mode=view&articleNo=456"])
async def test_graduate_links_cannot_change_source_or_action(monkeypatch, href):
    u = module()
    original = '?mode=view&amp;articleNo=456&amp;article.offset=10&amp;articleLimit=10'
    monkeypatch.setattr(u.httpclient, "get_html", AsyncMock(return_value=GRAD_LIST.replace(original, href.replace('&', '&amp;'))))
    with pytest.raises(u.ScrapeFailedError):
        await u.fetch_notices("graduate", page=2)


@pytest.mark.asyncio
@pytest.mark.parametrize("source,notice_id,html", [("university", "123", MAIN_DETAIL.replace('/123/artclView', '/999/artclView')), ("graduate", "456", GRAD_DETAIL.replace('value="456"', 'value="999"'))], ids=["main", "graduate"])
async def test_detail_identity_must_match_requested_id(monkeypatch, source, notice_id, html):
    u = module()
    monkeypatch.setattr(u.httpclient, "get_html", AsyncMock(return_value=html))
    with pytest.raises(u.ScrapeFailedError):
        await u.fetch_notice(source, notice_id)


@pytest.mark.asyncio
async def test_detail_excludes_hidden_and_active_content_without_inventing_image_text(monkeypatch):
    u = module()
    html = MAIN_DETAIL.replace('<p>공개 본문</p>', '<p hidden>PRIVATE HIDDEN</p><p aria-hidden="true">PRIVATE ARIA</p><p style="display: none">PRIVATE CSS</p><script>PRIVATE JS</script><iframe>PRIVATE EMBED</iframe><form>PRIVATE INPUT</form>')
    monkeypatch.setattr(u.httpclient, "get_html", AsyncMock(return_value=html))
    result = await u.fetch_notice("university", "123")
    assert result["body"] == ""
    assert result["has_images"] is True and "PRIVATE" not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("html", ['<h1>Login</h1>', '<div class="board-list"><div class="boardWrap"><ul></ul></div></div>'])
async def test_unknown_or_unexplained_empty_list_is_parser_error(monkeypatch, html):
    u = module()
    monkeypatch.setattr(u.httpclient, "get_html", AsyncMock(return_value=html))
    with pytest.raises(u.ScrapeFailedError):
        await u.fetch_notices("university")


@pytest.mark.asyncio
async def test_explicit_zero_count_is_empty_not_parser_error(monkeypatch):
    u = module()
    html = '<div class="board-list"><div class="srch_counts">총 0 개의 게시물</div><div class="boardWrap"><ul></ul></div></div>'
    monkeypatch.setattr(u.httpclient, "get_html", AsyncMock(return_value=html))
    result = await u.fetch_notices("university")
    assert result["count"] == 0 and result["notices"] == []
    assert result["pagination"]["total"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["list", "detail"])
@pytest.mark.parametrize("timeout", [True, False])
async def test_network_errors_are_redacted_and_typed(monkeypatch, kind, timeout):
    import httpx
    from yonsei_portal_mcp.errors import ScrapeFailedError, UpstreamTimeoutError
    u = module()
    exc = httpx.ReadTimeout("PRIVATE TOKEN") if timeout else httpx.HTTPError("PRIVATE TOKEN")
    monkeypatch.setattr(u.httpclient, "get_html", AsyncMock(side_effect=exc))
    expected = UpstreamTimeoutError if timeout else ScrapeFailedError
    with pytest.raises(expected) as caught:
        if kind == "list":
            await u.fetch_notices("university")
        else:
            await u.fetch_notice("university", "123")
    assert "PRIVATE" not in str(caught.value)


@pytest.mark.asyncio
async def test_paging_links_need_same_board_and_current_page(monkeypatch):
    u = module()
    html = GRAD_LIST.replace('?mode=list&amp;&amp;articleLimit=10&amp;article.offset=20', 'https://evil.test/?mode=list&amp;articleLimit=10&amp;article.offset=20')
    monkeypatch.setattr(u.httpclient, "get_html", AsyncMock(return_value=html))
    with pytest.raises(u.ScrapeFailedError):
        await u.fetch_notices("graduate", page=2)


@pytest.mark.asyncio
async def test_page_bound_never_returns_invalid_next_request(monkeypatch):
    u = module()
    html = MAIN_LIST.replace('class="_curPage">1', 'class="_curPage">1000').replace('class="_totPage">3', 'class="_totPage">1001')
    monkeypatch.setattr(u.httpclient, "get_html", AsyncMock(return_value=html))
    result = await u.fetch_notices("university", page=1000)
    assert result["pagination"]["has_next"] is True
    assert result["pagination"]["next_request"] is None
    assert result["pagination"]["page_limit_reached"] is True


@pytest.mark.asyncio
async def test_titles_and_attachment_names_exclude_hidden_text(monkeypatch):
    u = module()
    hidden = '<span style="display:none"><span style="display:none">PRIVATE NESTED</span></span>'
    html = MAIN_DETAIL.replace('합성 상세</strong>', '합성 상세' + hidden + '</strong>').replace('안내.pdf</a>', '안내.pdf' + hidden + '</a>')
    monkeypatch.setattr(u.httpclient, "get_html", AsyncMock(return_value=html))
    result = await u.fetch_notice("university", "123")
    assert result["title"] == "합성 상세"
    assert result["attachments"][0]["name"] == "안내.pdf"
    assert "PRIVATE" not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("href", ['?mode=download&amp;articleNo=999&amp;attachNo=987', '?mode=download&amp;articleNo=456&amp;attachNo=987&amp;extra=', '?mode=download&amp;articleNo=456&amp;attachNo=%39%38%37', 'https://[malformed', ' ?mode=download&amp;articleNo=456&amp;attachNo=987'])
async def test_unsafe_attachment_metadata_is_omitted_without_fetch(monkeypatch, href):
    u = module()
    html = GRAD_DETAIL.replace('?mode=download&amp;articleNo=456&amp;attachNo=987', href)
    get = AsyncMock(return_value=html)
    monkeypatch.setattr(u.httpclient, "get_html", get)
    result = await u.fetch_notice("graduate", "456")
    assert result["attachments"] == []
    assert get.await_count == 1


@pytest.mark.asyncio
async def test_graduate_empty_marker_is_not_unexplained_missing_rows(monkeypatch):
    u = module()
    html = '<div class="board-wrap"><table class="board-table"><thead><tr><th>번호</th><th>제목</th><th>등록일</th></tr></thead><tbody><tr><td colspan="3">등록된 게시물이 없습니다.</td></tr></tbody></table></div>'
    monkeypatch.setattr(u.httpclient, "get_html", AsyncMock(return_value=html))
    result = await u.fetch_notices("graduate")
    assert result["count"] == 0 and result["notices"] == []
    assert result["pagination"]["has_next"] is None and "total" not in result["pagination"]


@pytest.mark.asyncio
async def test_paging_without_current_marker_does_not_claim_verified_continuation(monkeypatch):
    u = module()
    html = GRAD_LIST.replace('class="active"', 'class="unknown"')
    monkeypatch.setattr(u.httpclient, "get_html", AsyncMock(return_value=html))
    result = await u.fetch_notices("graduate")
    assert result["pagination"]["has_next"] is None
    assert result["pagination"]["next_request"] is None

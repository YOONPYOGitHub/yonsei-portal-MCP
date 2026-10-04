"""Synthetic redirect regressions using real get_html and no network."""
import httpx
import pytest

from yonsei_portal_mcp import httpclient
from yonsei_portal_mcp.scrapers import university
from test_university import GRAD_DETAIL, GRAD_LIST, MAIN_DETAIL, MAIN_LIST


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["university", "graduate", "ai_graduate"])
@pytest.mark.parametrize("kind", ["list", "detail"])
async def test_notice_path_redirect_is_blocked_before_second_request(monkeypatch, source, kind):
    requests = []
    main = source == "university"
    notice_id = "123" if main else "456"
    other_path = {
        "university": "/bbs/sc/99/123/artclView.do",
        "graduate": "/gcomputing/community/noticeBoard.do",
        "ai_graduate": "/graduate/board/notice.do",
    }[source]
    html = (MAIN_DETAIL if main else GRAD_DETAIL) if kind == "detail" else (MAIN_LIST if main else GRAD_LIST)

    def handle(request):
        requests.append(request)
        if len(requests) == 1:
            # Preserve identity/query: rejecting only the HTML is too late.
            target = request.url.copy_with(path=other_path)
            return httpx.Response(302, headers={"Location": str(target)})
        return httpx.Response(200, text=html)

    client_class = httpx.AsyncClient
    monkeypatch.setattr(httpclient.httpx, "AsyncClient", lambda **kwargs: client_class(transport=httpx.MockTransport(handle), **kwargs))
    try:
        with pytest.raises(university.ScrapeFailedError):
            if kind == "detail":
                await university.fetch_notice(source, notice_id)
            else:
                await university.fetch_notices(source, page=1 if main else 2)
    finally:
        assert len(requests) == 1, "must not request the other board even if its HTML is rejected"


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["university", "graduate", "ai_graduate"])
async def test_notice_same_path_redirect_preserves_provenance(monkeypatch, source):
    requests = []
    main = source == "university"
    notice_id, html = ("123", MAIN_DETAIL) if main else ("456", GRAD_DETAIL)

    def handle(request):
        requests.append(request)
        if len(requests) == 1:
            target = request.url.copy_merge_params({"layout": "public"})
            return httpx.Response(302, headers={"Location": str(target)})
        return httpx.Response(200, text=html)

    client_class = httpx.AsyncClient
    monkeypatch.setattr(httpclient.httpx, "AsyncClient", lambda **kwargs: client_class(transport=httpx.MockTransport(handle), **kwargs))
    result = await university.fetch_notice(source, notice_id)
    assert len(requests) == 2
    assert requests[0].url.path == requests[1].url.path
    assert result["source"]["source"] == source
    assert result["source_url"] == str(requests[0].url)
    assert result["body"] == "공개 본문"
    expected_attachment = str(requests[0].url.join('/bbs/sc/58/987/download.do' if main else '?mode=download&articleNo=456&attachNo=987'))
    assert result["attachments"] == [{"name": "안내.pdf", "url": expected_attachment}]

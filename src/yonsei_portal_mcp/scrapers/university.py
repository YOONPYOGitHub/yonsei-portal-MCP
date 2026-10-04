"""Curated official public notice boards; no login, arbitrary URLs or downloads.

Endpoint provenance: the university landing page links /bbs/sc/58/<id>/artclView.do
and submits its list form to /bbs/sc/58/artclList.do with ``page``. Graduate
boards publish ``mode=view&articleNo`` links and ``article.offset`` pagination
with articleLimit=10. No encoded route, board ID or configurable URL is guessed.

All fixtures are synthetic. Public HTML is untrusted content, not instructions.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import re
from types import MappingProxyType
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from .. import httpclient
from ..errors import ScrapeFailedError, UpstreamTimeoutError


@dataclass(frozen=True)
class _Source:
    source: str
    label: str
    source_url: str
    description: str


_SOURCES = MappingProxyType({
    s.source: s for s in (
        _Source("university", "연세대학교 공지사항", "https://www.yonsei.ac.kr/sc/254/subview.do", "대학 공식 공지사항입니다. 개별 대학원에 적용되는지는 원문을 확인하세요."),
        _Source("graduate", "일반대학원 교내공지사항", "https://graduate.yonsei.ac.kr/graduate/board/notice.do", "일반대학원 교내 공지이며 전문·특수대학원 공지와 다릅니다."),
        _Source("ai_graduate", "인공지능융합대학원 공지사항", "https://graduate.yonsei.ac.kr/gcomputing/community/noticeBoard.do", "인공지능융합대학원의 공개 공지사항입니다."),
    )
})


def list_sources() -> dict:
    """Return copies of the fixed, reviewed official source metadata."""
    return {"count": len(_SOURCES), "sources": [asdict(s) for s in _SOURCES.values()]}


def _source(source: str) -> _Source:
    if type(source) is not str or source not in _SOURCES:
        raise ValueError("source는 list_sources()의 등록된 식별자여야 합니다.")
    return _SOURCES[source]


async def _get_html(url: str, *, params: dict | None = None) -> str:
    try:
        return await httpclient.get_html(url, params=params, same_path=True)
    except httpx.TimeoutException:
        raise UpstreamTimeoutError("공식 공지 응답 시간이 초과되었습니다.") from None
    except httpx.HTTPError:
        raise ScrapeFailedError("공식 공지를 불러오지 못했습니다.") from None


def _graduate_query(href: str, spec: _Source, mode: str) -> dict:
    # No arbitrary URL is ever fetched, even after successful link validation.
    if not href or href != href.strip() or re.search(r"[\x00-\x20\\%]", href):
        raise ScrapeFailedError("공식 공지 링크를 확인하지 못했습니다.")
    try:
        target, base = urlsplit(urljoin(spec.source_url, href)), urlsplit(spec.source_url)
        query = parse_qs(target.query, keep_blank_values=True)
    except ValueError:
        raise ScrapeFailedError("공식 공지 링크를 확인하지 못했습니다.") from None
    if (target.scheme, target.netloc, target.path) != (base.scheme, base.netloc, base.path) or target.fragment or query.get("mode") != [mode] or any(len(v) != 1 for v in query.values()):
        raise ScrapeFailedError("공식 공지 링크의 게시판/동작이 다릅니다.")
    allowed = {"mode", "articleNo", "article.offset", "articleLimit"} if mode == "view" else {"mode", "article.offset", "articleLimit"}
    if not set(query) <= allowed or ("articleLimit" in query and query["articleLimit"] != ["10"]) or ("article.offset" in query and not re.fullmatch(r"[0-9]+", query["article.offset"][0])):
        raise ScrapeFailedError("공식 공지 링크의 매개변수가 변경되었습니다.")
    return query


def _clean(node) -> None:
    for item in list(node.select("script,style,iframe,object,embed,form,template,[hidden],[aria-hidden='true']")):
        item.decompose()
    for item in list(node.select("[style]")):
        if item.attrs is not None and re.search(r"(?:display\s*:\s*none|visibility\s*:\s*hidden)", str(item.get("style", "")), re.I):
            item.decompose()


def _text(node) -> str:
    if node is None:
        return ""
    clean = BeautifulSoup(str(node), "html.parser")
    _clean(clean)
    return " ".join(clean.get_text(" ", strip=True).split())


def _date(node) -> str:
    match = re.search(r"\b[0-9]{4}[.-][0-9]{2}[.-][0-9]{2}\b", _text(node))
    if not match:
        raise ScrapeFailedError("공식 공지의 작성일을 확인하지 못했습니다.")
    return match[0]


def validate_list(source: str, page: int, limit: int) -> None:
    _source(source)
    if type(page) is not int or not 1 <= page <= 1000:
        raise ValueError("page는 1~1000 정수여야 합니다.")
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit은 1~100 정수여야 합니다.")


def validate_detail(source: str, notice_id: str) -> None:
    _source(source)
    if type(notice_id) is not str or not re.fullmatch(r"[1-9][0-9]{0,11}", notice_id):
        raise ValueError("notice_id는 공지 목록에서 얻은 1~12자리 ASCII 양의 정수 문자열이어야 합니다.")


async def fetch_notices(source: str, page: int = 1, limit: int = 10) -> dict:
    """Read one upstream page with local deduplication of pinned notices.

    ``page`` is the source page (1..1000); ``limit`` (1..100) caps returned rows,
    NOT upstream page size. Follow ``same_page_request`` before ``next_request``
    when truncated. Expanded results overlap previously returned rows.
    ``has_next=None`` means unknown, not exhausted. ``total``, when present,
    is the board's displayed counter, not an inferred full-history count.
    """
    validate_list(source, page, limit)
    spec = _source(source)
    main = source == "university"
    url = "https://www.yonsei.ac.kr/bbs/sc/58/artclList.do" if main else spec.source_url
    params = {"page": page} if main else {"mode": "list", "articleLimit": 10, "article.offset": (page - 1) * 10}
    soup = BeautifulSoup(await _get_html(url, params=params), "html.parser")
    box = soup.select_one(".board-list" if main else ".board-wrap:has(table.board-table)")
    if box is None:
        raise ScrapeFailedError("공식 공지 목록 구조를 확인하지 못했습니다.")
    notices, seen = [], {}
    verified_empty = False
    for row in box.select(".boardWrap > ul > li" if main else "table.board-table tbody tr"):
        if not main and row.select_one("td[colspan]") is not None and _text(row) == "등록된 게시물이 없습니다.":
            verified_empty = True
            continue
        link = row.select_one("a[href]" if main else "a.c-board-title[href]")
        href = str(link.get("href", "")) if link else ""
        if main:
            title = _text(row.select_one(".title strong"))
            match = re.fullmatch(r"/bbs/sc/58/([1-9][0-9]{0,11})/artclView.do", href)
            notice_id = match[1] if match else ""
        else:
            if link:
                for label in link.select(".c-board-top-num-m"):
                    label.decompose()
            title = _text(link)
            query = _graduate_query(href, spec, "view")
            ids = query.get("articleNo", [])
            notice_id = ids[0] if len(ids) == 1 else ""
        if not re.fullmatch(r"[1-9][0-9]{0,11}", notice_id) or not title:
            raise ScrapeFailedError("공식 공지의 제목/링크 구조가 변경되었습니다.")
        detail_url = urljoin(url, href) if main else spec.source_url + "?mode=view&articleNo=" + notice_id
        notice = {"notice_id": notice_id, "title": title, "date_raw": _date(row.select_one(".date-area" if main else ".c-board-info-m")), "url": detail_url, "pinned": ("board-noti" if main else "c-board-top-wrap") in (row.get("class") or [])}
        if notice_id in seen:
            if any(seen[notice_id][field] != notice[field] for field in ("title", "date_raw", "url")):
                raise ScrapeFailedError("중복된 공식 공지의 제목/작성일/링크가 다릅니다.")
            seen[notice_id]["pinned"] = seen[notice_id]["pinned"] or notice["pinned"]
        else:
            notices.append(notice)
            seen[notice_id] = notice
    current = _text(box.select_one("._curPage"))
    last = _text(box.select_one("._totPage"))
    has_next = int(current) < int(last) if current.isdecimal() and last.isdecimal() else None
    if not main:
        paging_box = box.find_parent(class_="ys-board") or box
        current = _text(paging_box.select_one(".paging-wrap .active"))
        offsets = []
        for link in paging_box.select(".paging-wrap a[href]"):
            href = str(link["href"])
            if href == "#curPage":
                continue
            query = _graduate_query(href, spec, "list")
            values = query.get("article.offset", [])
            if len(values) != 1 or int(values[0]) % 10:
                raise ScrapeFailedError("공식 공지 페이지 이동 값을 확인하지 못했습니다.")
            offsets.append(int(values[0]))
        has_next = True if current and any(offset > (page - 1) * 10 for offset in offsets) else None
    if (page > 1 and not current) or (current and (not re.fullmatch(r"[1-9][0-9]*", current) or int(current) != page)):
        raise ScrapeFailedError("요청한 공지 페이지와 표시된 페이지가 다릅니다.")
    if main and current.isdecimal() and last.isdecimal() and int(last) < int(current):
        raise ScrapeFailedError("공식 공지의 전체 페이지 수가 현재 페이지보다 작습니다.")
    total_match = re.fullmatch(r"총 ([0-9,]+) 개의 게시물", _text(box.select_one(".srch_counts")))
    pagination = {"page": page, "limit": limit, "has_next": has_next, "next_request": {"source": source, "page": page + 1, "limit": limit} if has_next and page < 1000 else None, "complete_history": False, "page_limit_reached": page == 1000 and has_next is True}
    if total_match:
        pagination["total"] = int(total_match[1].replace(",", ""))
    pagination.update({
        "available_count": len(notices), "truncated": len(notices) > limit,
        "same_page_request": {"source": source, "page": page, "limit": min(len(notices), 100)} if len(notices) > limit and limit < 100 else None,
        "note": "상단 고정 공지는 페이지마다 반복될 수 있으며 현재 페이지 안에서만 중복을 제거합니다. limit은 해당 페이지의 출력 상한입니다. truncated이면 same_page_request로 같은 페이지를 먼저 확장하세요. 전체 이력 수집을 보장하지 않습니다. has_next=null은 다음 페이지 여부를 확인하지 못했다는 뜻입니다.",
    })
    if not notices and not verified_empty and pagination.get("total") != 0:
        raise ScrapeFailedError("공식 공지 목록이 비어 있으나 빈 목록 여부를 확인하지 못했습니다.")
    notices = notices[:limit]
    return {"source": asdict(spec), "source_url": url + "?" + urlencode(params), "fetched_at": datetime.now(timezone.utc).isoformat(), "count": len(notices), "notices": notices, "pagination": pagination}


async def fetch_notice(source: str, notice_id: str) -> dict:
    """Read only the selected public notice body and attachment link metadata."""
    validate_detail(source, notice_id)
    spec = _source(source)
    main = source == "university"
    url = ("https://www.yonsei.ac.kr/bbs/sc/58/" + notice_id + "/artclView.do") if main else spec.source_url + "?mode=view&articleNo=" + notice_id
    soup = BeautifulSoup(await _get_html(url), "html.parser")
    box = soup.select_one(".board-view" if main else ".ys-board.view")
    if box is None:
        raise ScrapeFailedError("공식 공지 본문 구조를 확인하지 못했습니다.")
    if main:
        identity = box.select_one("input#clip_tmp")
        value = str(identity.get("value", "")) if identity else ""
        if value.split("?", 1)[0] != url:
            raise ScrapeFailedError("요청한 공지와 본문 식별자가 다릅니다.")
        title = _text(box.select_one(".viewCont > .title > strong"))
        date_node = next((li for li in box.select(".title .detail li") if _text(li.find("span")) == "작성일"), None)
        body_node = box.select_one(".viewCont > .txt")
    else:
        identity = box.select_one("input[name='articleNo']")
        if identity is None or identity.get("value") != notice_id:
            raise ScrapeFailedError("요청한 공지와 본문 식별자가 다릅니다.")
        fields = {_text(dl.find("dt")): dl.find("dd") for dl in box.select(".board-write-wrap > dl.board-write-box")}
        title = _text(fields.get("제목"))
        date_node = fields.get("작성일")
        body_node = box.select_one(".board-write-wrap .fr-view")
    if not title or body_node is None:
        raise ScrapeFailedError("공식 공지의 제목/본문 구조가 변경되었습니다.")
    _clean(body_node)
    attachments = []
    for a in box.select(".attachment a[href]" if main else "a.file-down-btn[href]"):
        href = str(a["href"])
        if not href or href != href.strip() or re.search(r"[\x00-\x20\\%]", href):
            continue
        try:
            target = urljoin(url, href)
            parts, base = urlsplit(target), urlsplit(url)
        except ValueError:
            continue
        if parts.scheme != "https" or parts.netloc != base.netloc or parts.fragment:
            continue
        query = parse_qs(parts.query, keep_blank_values=True)
        if main:
            valid = re.fullmatch(r"/bbs/sc/58/[1-9][0-9]{0,11}/download.do", parts.path) and not parts.query
        else:
            valid = parts.path == base.path and query.get("mode") == ["download"] and query.get("articleNo") == [notice_id] and len(query.get("attachNo", [])) == 1 and re.fullmatch(r"[1-9][0-9]{0,11}", query["attachNo"][0]) and set(query) == {"mode", "articleNo", "attachNo"}
        if valid and _text(a) and not any(item["url"] == target for item in attachments):
            attachments.append({"name": _text(a), "url": target})
    return {"source": asdict(spec), "source_url": url, "fetched_at": datetime.now(timezone.utc).isoformat(), "notice_id": notice_id, "title": title, "date_raw": _date(date_node), "body": _text(body_node), "has_images": body_node.find("img") is not None, "attachments": attachments, "content_note": "선택한 공지의 공개 텍스트만 제공합니다. 이미지 OCR과 첨부파일 다운로드는 수행하지 않으므로 이미지/첨부 내용은 원문에서 확인하세요."}

"""Yonsei Library public HTTP and authenticated Playwright scrapers.

Catalog and notices use public HTML. Loans and room seats use authenticated
pages. Personal loan data is returned to the caller, never logged (DESIGN §6).
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup
from playwright.async_api import Page

from .. import httpclient
from ..errors import ScrapeFailedError, UpstreamTimeoutError

MYLOAN_URL = "https://library.yonsei.ac.kr/myloan/list"
MYRESERVE_URL = "https://library.yonsei.ac.kr/myreserve/integratedList"
SEAT_ROOMS_URL = "https://library.yonsei.ac.kr/relation/seat"
LIBRARY_BASE = "https://library.yonsei.ac.kr"


def _library_detail_url(href: str, prefix: str) -> str:
    parsed = urlsplit(urljoin(LIBRARY_BASE, href))
    if (
        parsed.scheme != "https" or parsed.hostname != "library.yonsei.ac.kr"
        or parsed.username or parsed.password or parsed.port not in (None, 443)
        or not parsed.path.startswith(prefix)
    ):
        raise ScrapeFailedError("도서관 상세 링크 주소를 확인하지 못했습니다.")
    return LIBRARY_BASE + parsed.path


def parse_book_search(html: str) -> list[dict]:
    """Parse public catalog results, excluding basket and reservation actions."""
    soup = BeautifulSoup(html, "html.parser")
    books = []
    seen = set()
    for item in soup.select("li.items"):
        link = item.select_one("dd.title a[href]")
        if link is None:
            raise ScrapeFailedError("도서 검색 결과의 제목을 확인하지 못했습니다.")
        url = _library_detail_url(str(link["href"]), "/search/detail/")
        if url in seen:
            continue
        seen.add(url)
        fields = {}
        for label in item.select("dt"):
            value = label.find_next_sibling("dd")
            if value is not None:
                fields[label.get_text(strip=True)] = value.get_text(" ", strip=True)
        holdings = []
        for location in item.select(".holdingInfo .location"):
            badge = location.select_one(".availableBtn")
            status = badge.get_text(" ", strip=True) if badge else ""
            text = location.get_text(" ", strip=True)
            holdings.append({"location": text.removesuffix(status).strip() if status else text, "status": status or None})
        books.append({
            "title": link.get_text(" ", strip=True),
            "author": fields.get("저자"),
            "publisher": fields.get("출판사"),
            "published_year": fields.get("출판년"),
            "material_type": fields.get("자료유형"),
            "url": url,
            "holdings": holdings,
        })
    if not books:
        count = soup.select_one(".searchCnt strong")
        if count is None or count.get_text(strip=True) != "0":
            raise ScrapeFailedError("도서 검색 결과 구조를 확인하지 못했습니다.")
    return books


def parse_library_notices(html: str) -> list[dict]:
    """Read public notice titles and dates without returning author identities."""
    soup = BeautifulSoup(html, "html.parser")
    notices = []
    seen = set()
    for row in soup.select("table.mobileTable tr"):
        link = row.select_one("td.title a[href]")
        if link is None:
            title = row.select_one("td.title")
            if title is not None and title.get_text(strip=True) == "관리자에 의해 삭제된 게시물입니다.":
                continue
            if row.find("td") is not None:
                raise ScrapeFailedError("도서관 공지 제목 링크를 확인하지 못했습니다.")
            continue
        date = row.select_one("td.reportDate")
        if date is None:
            raise ScrapeFailedError("도서관 공지 작성일을 확인하지 못했습니다.")
        url = _library_detail_url(str(link["href"]), "/bbs/content/")
        if url not in seen:
            seen.add(url)
            notices.append({"title": link.get_text(" ", strip=True), "date": date.get_text(strip=True), "url": url})
    if not notices:
        raise ScrapeFailedError("도서관 공지 목록 구조를 확인하지 못했습니다.")
    return notices


async def fetch_book_search(query: str, page: int = 1, limit: int = 10) -> dict:
    """Search the public catalog without login, cookies, or a browser."""
    query = query.strip()
    if not query or len(query) > 200:
        raise ValueError("query는 1~200자의 검색어여야 합니다.")
    if not 1 <= page <= 100 or not 1 <= limit <= 10:
        raise ValueError("page는 1~100, limit은 1~10이어야 합니다.")
    try:
        html = await httpclient.get_html(
            LIBRARY_BASE + "/search/tot/result",
            params={"st": "KWRD", "si": "TOTAL", "q": query, "pn": page},
        )
    except httpx.TimeoutException:
        raise UpstreamTimeoutError("도서 검색 응답 시간이 초과되었습니다.") from None
    except httpx.HTTPError:
        raise ScrapeFailedError("도서 검색 페이지를 불러오지 못했습니다.") from None
    books = parse_book_search(html)[:limit]
    return {"query": query, "page": page, "count": len(books), "results": books}


def parse_book_copies(html: str, catalog_id: str) -> dict:
    fields = {"등록번호": "reg_no", "청구기호": "call_number", "소장처": "location", "도서상태": "status_raw", "반납예정일": "due_date_raw"}
    copies, seen = [], set()
    for table in BeautifulSoup(html, "html.parser").select("table.searchTable"):
        headers = [re.sub(r"\s+", "", cell.get_text()) for cell in table.select("thead th,thead td")]
        if not fields.keys() <= set(headers) or any(headers.count(header) != 1 for header in fields):
            raise ScrapeFailedError("도서 복본 표의 필수 열을 확인하지 못했습니다.")
        rows = table.select("tbody tr")
        if not rows:
            raise ScrapeFailedError("도서 복본 표의 데이터가 준비되지 않았습니다.")
        for row in rows:
            cells = row.find_all("td", recursive=False)
            if len(cells) != len(headers):
                raise ScrapeFailedError("도서 복본 행의 열 구성이 변경되었습니다.")
            item = {field: " ".join(cells[headers.index(header)].get_text(" ", strip=True).split()) for header, field in fields.items()}
            if not item["reg_no"] or not item["location"] or not item["status_raw"] or item["reg_no"] in seen:
                raise ScrapeFailedError("도서 복본 식별자/상태가 없거나 중복되었습니다.")
            seen.add(item["reg_no"])
            copies.append(item)
    if not copies:
        raise ScrapeFailedError("도서 복본 소장 표를 확인하지 못했습니다. 미소장을 의미하지 않습니다.")
    return {
        "catalog_id": catalog_id, "count": len(copies), "copies": copies,
        "note": "소장자료 상세 화면의 복본 정보입니다. 빈 반납예정일의 의미를 추정하지 않습니다. 대출/예약 가능 여부는 방문 시 원문에서 재확인하세요.",
    }


async def fetch_book_detail(catalog_id: str) -> dict:
    if not re.fullmatch(r"CATTOT[0-9]{1,20}", catalog_id):
        raise ValueError("catalog_id는 검색 결과 상세 URL의 CATTOT와 숫자로 된 식별자여야 합니다.")
    url = LIBRARY_BASE + "/search/detail/" + catalog_id
    try:
        html = await httpclient.get_html(url)
    except httpx.TimeoutException:
        raise UpstreamTimeoutError("도서 상세 응답 시간이 초과되었습니다.") from None
    except httpx.HTTPError:
        raise ScrapeFailedError("도서 상세 페이지를 불러오지 못했습니다.") from None
    result = parse_book_copies(html, catalog_id)
    result.update(source_url=url, fetched_at=datetime.now(timezone.utc).isoformat())
    return result


async def fetch_library_notices(limit: int = 10) -> dict:
    """Return the public library notice board's first page, including pinned notices."""
    if not 1 <= limit <= 20:
        raise ValueError("limit은 1~20이어야 합니다.")
    try:
        html = await httpclient.get_html(LIBRARY_BASE + "/bbs/list/1")
    except httpx.TimeoutException:
        raise UpstreamTimeoutError("도서관 공지 응답 시간이 초과되었습니다.") from None
    except httpx.HTTPError:
        raise ScrapeFailedError("도서관 공지 페이지를 불러오지 못했습니다.") from None
    notices = parse_library_notices(html)[:limit]
    return {"count": len(notices), "notices": notices}


async def fetch_library_notice(url: str) -> dict:
    """Read a public general notice's text; image contents are not transcribed."""
    if not re.fullmatch(r"/bbs/content/1_[0-9]+", urlsplit(url).path):
        raise ValueError("도서관 일반공지 목록의 게시글 URL을 사용하세요.")
    url = _library_detail_url(url, "/bbs/content/")
    try:
        html = await httpclient.get_html(url)
    except httpx.TimeoutException:
        raise UpstreamTimeoutError("도서관 공지 본문 응답 시간이 초과되었습니다.") from None
    except httpx.HTTPError:
        raise ScrapeFailedError("도서관 공지 본문을 불러오지 못했습니다.") from None
    soup = BeautifulSoup(html, "html.parser")
    title = soup.select_one(".boardInfoTitle")
    content = soup.select_one(".boardContent")
    metadata = soup.select_one(".boardInfo")
    if title is None or content is None:
        raise ScrapeFailedError("도서관 공지 본문 구조를 확인하지 못했습니다.")
    date = re.search(r"[0-9]{4}[-.][0-9]{2}[-.][0-9]{2}", metadata.get_text(" ", strip=True) if metadata else "")
    image_count = len(content.select("img"))
    return {
        "url": url,
        "title": title.get_text(" ", strip=True),
        "date": date.group().replace(".", "-") if date else None,
        "author": None,
        "body": content.get_text("\n", strip=True),
        "image_count": image_count,
        "note": "이미지 내용은 텍스트로 추출하지 않았습니다. 원문을 확인하세요." if image_count else None,
    }

# --------------------------------------------------------------------------- #
# JavaScript snippets (run inside the page DOM)
# --------------------------------------------------------------------------- #

_MYLOAN_JS = r"""
() => {
  const t = document.querySelector('table.mobileTable') || document.querySelector('table');
  if (!t) return { headers: [], rows: [] };
  const headers = Array.from(t.querySelectorAll('thead th, thead td'))
    .map(c => (c.innerText || '').replace(/\s+/g, ' ').trim());
  const rows = [];
  t.querySelectorAll('tbody tr').forEach(tr => {
    const cells = Array.from(tr.querySelectorAll('td'))
      .map(c => (c.innerText || '').replace(/\s+/g, ' ').trim());
    // The "no results" placeholder renders as a single spanned cell.
    if (cells.filter(c => c).length <= 1) return;
    rows.push(cells);
  });
  return { headers, rows };
}
"""

# Map the live table headers to stable English keys for the JSON payload.
_LOAN_FIELD_MAP = {
    "서명/저자": "title_author",
    "소장처": "location",
    "등록번호": "reg_no",
    "대출일": "loan_date",
    "반납예정일": "due_date",
    "연체료": "overdue_fee",
    "연장횟수": "renew_count",
}

_RESERVATION_FIELD_MAP = {
    "서명/저자": "title_author", "소장처": "location", "예약순위": "queue_position",
    "예약일": "reservation_date", "도착통보일": "notification_date", "예약상태": "status",
}

_LOAN_HISTORY_FIELD_MAP = {
    "서명/저자": "title_author", "소장처": "location", "등록번호": "reg_no",
    "대출일": "loan_date", "반납일": "return_date", "반납유형": "return_type",
}


def _parse_account_table(html: str, fields: dict[str, str], *, history: bool = False) -> list[dict]:
    for table in BeautifulSoup(html, "html.parser").select("table.mobileTable"):
        headers = [re.sub(r"\s+", "", cell.get_text()) for cell in table.select("thead th,thead td")]
        if not fields.keys() <= set(headers):
            continue
        if history and any(headers.count(header) != 1 for header in fields):
            raise ScrapeFailedError("History table has ambiguous required columns.")
        records = []
        seen = set()
        rows = table.select("tbody tr")
        if not rows:
            raise ScrapeFailedError("도서관 개인 조회 표의 결과 상태를 확인하지 못했습니다.")
        for row in rows:
            cells = row.find_all("td", recursive=False)
            if len(cells) == 1 and cells[0].get("colspan") == str(len(headers)) and cells[0].get_text(strip=True) in {"결과가 없습니다.", "등록된 자료가 없습니다."}:
                if len(rows) != 1:
                    raise ScrapeFailedError("도서관 조회 표에 빈 상태와 데이터가 섞여 있습니다.")
                return []
            if len(cells) != len(headers):
                raise ScrapeFailedError("도서관 개인 조회 행의 열 구성이 변경되었습니다.")
            record = {key: cells[headers.index(header)].get_text(" ", strip=True) for header, key in fields.items()}
            if history:
                required = ("title_author", "reg_no", "loan_date", "return_date") if fields is _LOAN_HISTORY_FIELD_MAP else ("title_author", "reservation_date", "status")
                if any(not record[key] for key in required):
                    raise ScrapeFailedError("History row is missing required data.")
                signature = tuple(cell.get_text(" ", strip=True) for cell in cells)
                if signature in seen:
                    continue
                seen.add(signature)
            records.append(record)
        return records
    raise ScrapeFailedError("도서관 개인 조회 표를 확인하지 못했습니다. 0건을 의미하지 않습니다.")


def parse_my_loans(html: str) -> dict:
    loans = _parse_account_table(html, _LOAN_FIELD_MAP)
    return {"count": len(loans), "loans": loans}


def parse_my_reservations(html: str) -> dict:
    reservations = _parse_account_table(html, _RESERVATION_FIELD_MAP)
    return {"count": len(reservations), "reservations": reservations}


def _history_url(url: str, path: str) -> str:
    try:
        parsed = urlsplit(urljoin(LIBRARY_BASE + path, url))
        valid = (
            parsed.scheme == "https" and parsed.hostname == "library.yonsei.ac.kr"
            and not parsed.username and not parsed.password and parsed.port in (None, 443)
            and parsed.path == path and not parsed.fragment
        )
    except ValueError:
        valid = False
    if not valid:
        raise ScrapeFailedError("History navigation is not a same-origin read-only history URL.")
    return parsed.geturl()


def _history_state(html: str, fields: dict[str, str], path: str, count: int) -> tuple[dict, dict[int, str]]:
    soup = BeautifulSoup(html, "html.parser")
    table = next((table for table in soup.select("table.mobileTable") if fields.keys() <= {
        re.sub(r"\s+", "", cell.get_text()) for cell in table.select("thead th,thead td")
    }), None)
    if table is None:
        raise ScrapeFailedError("History table is unavailable.")
    metadata, links, current_pages = {}, {}, set()
    count_element = table.find_previous(lambda element: element.name == "table" or "totalCnt" in element.get("class", []))
    if count_element is not None and "totalCnt" in count_element.get("class", []):
        total = re.fullmatch(r"총\s*([0-9]+(?:,[0-9]{3})*)\s*건", count_element.get_text(" ", strip=True))
        if total is None:
            raise ScrapeFailedError("History total count is malformed.")
        metadata["total"] = int(total.group(1).replace(",", ""))
        if metadata["total"] < count or (metadata["total"] > 0 and count == 0):
            raise ScrapeFailedError("History total count contradicts the displayed rows.")
    for pager in soup.select(".paging,.pagination,.pageNum"):
        if pager.find_previous("table", class_="mobileTable") is not table:
            continue
        for marker in pager.select("strong,.current,.active"):
            text = marker.get_text(strip=True)
            if not re.fullmatch(r"[0-9]+", text):
                raise ScrapeFailedError("History current page is malformed.")
            current_pages.add(int(text))
        for anchor in pager.select("a[href]"):
            label = anchor.get_text(strip=True)
            numeric_label = bool(re.fullmatch(r"[0-9]+", label))
            href = str(anchor["href"])
            if not numeric_label and "?" not in href:
                continue
            url = _history_url(href, path)
            query = parse_qs(urlsplit(url).query, keep_blank_values=True)
            candidates = [int(values[0]) for key, values in query.items() if key not in {"dtf", "dtt"}
                          and len(values) == 1 and re.fullmatch(r"[0-9]+", values[0])
                          and (not numeric_label or int(values[0]) == int(label))]
            if len(candidates) != 1 or candidates[0] < 1:
                raise ScrapeFailedError("History pagination link has no unambiguous page parameter.")
            number = candidates[0]
            if number in links and links[number] != url:
                raise ScrapeFailedError("History pagination contains conflicting links.")
            links[number] = url
    if fields is _LOAN_HISTORY_FIELD_MAP:
        controls = soup.select('form#form input[name="pn"]')
        if len(controls) > 1:
            raise ScrapeFailedError("History page control is ambiguous.")
        if controls:
            value = str(controls[0].get("value", ""))
            if not re.fullmatch(r"[0-9]+", value):
                raise ScrapeFailedError("History page control is malformed.")
            current_pages.add(int(value))
    if len(current_pages) > 1 or any(not 1 <= number <= 100 for number in current_pages):
        raise ScrapeFailedError("History source page indicators are inconsistent.")
    if current_pages:
        current = current_pages.pop()
        metadata["page"] = current
        if current == 1 and metadata.get("total") == count and any(number > 1 for number in links):
            raise ScrapeFailedError("History total contradicts the advertised later pages.")
        if current + 1 in links:
            metadata.update(has_next=True, next_page=current + 1)
        elif current == 1 and metadata.get("total") == count:
            metadata.update(has_next=False, next_page=None)
    metadata["has_pagination"] = bool(links)
    return metadata, links


def parse_loan_history(html: str) -> dict:
    loans = _parse_account_table(html, _LOAN_HISTORY_FIELD_MAP, history=True)
    soup = BeautifulSoup(html, "html.parser")
    forms = soup.select("form#form")
    if len(forms) != 1 or str(forms[0].get("method", "get")).lower() != "get":
        raise ScrapeFailedError("Loan history search form is unavailable or is not read-only.")
    _history_url(str(forms[0].get("action", "/myloan/history")), "/myloan/history")
    dates = {}
    for name, field in (("dtf", "from"), ("dtt", "to")):
        elements = forms[0].select(f'input[name="{name}"]')
        if len(elements) != 1 or elements[0].has_attr("disabled"):
            raise ScrapeFailedError("이전 대출 기록의 날짜 조회 조건을 확인하지 못했습니다.")
        value = str(elements[0].get("value", ""))
        if value:
            try:
                if not re.fullmatch(r"[0-9]{8}", value):
                    raise ValueError
                datetime.strptime(value, "%Y%m%d").date()
            except ValueError:
                raise ScrapeFailedError("Loan history source date is malformed.") from None
        dates[field] = value
    if dates["from"] and dates["to"] and dates["from"] > dates["to"]:
        raise ScrapeFailedError("Loan history source dates are reversed.")
    metadata, _ = _history_state(html, _LOAN_HISTORY_FIELD_MAP, "/myloan/history", len(loans))
    return {
        "count": len(loans), "loans": loans, "scope": "displayed_page",
        "date_filters_raw": dates, **metadata,
        "note": "이전 대출기록의 현재 표시 페이지입니다. 반납일은 실제 반납 기록이며 반납예정일이 아닙니다. 0건은 현재 화면/필터 기준이고 전체 이력 없음을 뜻하지 않습니다.",
    }


def parse_reservation_history(html: str) -> dict:
    reservations = _parse_account_table(html, _RESERVATION_FIELD_MAP, history=True)
    metadata, _ = _history_state(html, _RESERVATION_FIELD_MAP, "/myreserve/integratedhistory", len(reservations))
    return {
        "count": len(reservations), "reservations": reservations, "scope": "displayed_page",
        **metadata,
        "note": "이전 도서 예약기록의 표시 페이지입니다. 예약순위와 상태는 과거 기록이지 현재 예약이 아닙니다. 캠퍼스간 신청/시설 예약 표는 제외하고, 0건을 전체 이력 없음으로 단정하지 않습니다.",
    }


def validate_history_options(
    *, start_date: str | None = None, end_date: str | None = None, page_number: int = 1,
) -> None:
    if type(page_number) is not int or not 1 <= page_number <= 100:
        raise ValueError("page_number must be an integer from 1 to 100.")
    for value in (start_date, end_date):
        if value is not None:
            if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
                raise ValueError("History dates must use ISO YYYY-MM-DD.")
            try:
                date.fromisoformat(value)
            except ValueError:
                raise ValueError("History dates must be valid calendar dates.") from None
    if start_date is not None and end_date is not None and start_date > end_date:
        raise ValueError("start_date must not be after end_date.")


async def _fetch_history_page(
    page: Page, path: str, parser, *, start_date: str | None = None,
    end_date: str | None = None, page_number: int = 1,
) -> dict:
    validate_history_options(start_date=start_date, end_date=end_date, page_number=page_number)
    url = LIBRARY_BASE + path
    params = {key: value.replace("-", "") for key, value in (("dtf", start_date), ("dtt", end_date)) if value is not None}
    if params:
        url += "?" + urlencode(params)
    await page.goto(url, wait_until="domcontentloaded")
    await page.wait_for_selector("table.mobileTable tbody tr", timeout=15_000)
    actual = _history_url(page.url, path)
    if parse_qs(urlsplit(actual).query, keep_blank_values=True) != parse_qs(urlsplit(url).query, keep_blank_values=True):
        raise ScrapeFailedError("History navigation changed the requested first-page conditions.")
    html = await page.content()
    result = parser(html)
    if result.get("page", 1) != 1:
        raise ScrapeFailedError("History did not display the requested first page.")
    for key, field in (("dtf", "from"), ("dtt", "to")):
        if key in params and result.get("date_filters_raw", {}).get(field) != params[key]:
            raise ScrapeFailedError("Loan history source did not confirm the requested date filters; results cannot be treated as date-filtered.")
    fields = _LOAN_HISTORY_FIELD_MAP if path == "/myloan/history" else _RESERVATION_FIELD_MAP
    _, links = _history_state(html, fields, path, result["count"])
    if result.get("total") == result["count"] and any(number > 1 for number in links):
        raise ScrapeFailedError("History total contradicts the advertised later pages.")
    if 2 in links:
        result.update(has_next=True, next_page=2)
    if page_number != 1:
        target = links.get(page_number)
        if target is None:
            raise ScrapeFailedError("Requested history page has no verified source link.")
        await page.goto(target, wait_until="domcontentloaded")
        await page.wait_for_selector("table.mobileTable tbody tr", timeout=15_000)
        actual = _history_url(page.url, path)
        if parse_qs(urlsplit(actual).query, keep_blank_values=True) != parse_qs(urlsplit(target).query, keep_blank_values=True):
            raise ScrapeFailedError("History navigation changed the requested page conditions.")
        selected = parser(await page.content())
        if selected.get("page") != page_number or not selected["count"]:
            raise ScrapeFailedError("Requested history page was not confirmed by the source.")
        if selected.get("date_filters_raw") != result.get("date_filters_raw"):
            raise ScrapeFailedError("History pagination changed the source date conditions.")
        key = "loans" if path == "/myloan/history" else "reservations"
        if {tuple(record.items()) for record in selected[key]} == {tuple(record.items()) for record in result[key]}:
            raise ScrapeFailedError("History returned the first page again instead of the requested page.")
        result = selected
    result["page"] = page_number
    if page_number == 1 and result.get("total") == result["count"]:
        result.update(has_next=False, next_page=None)
    result.update(source_url=page.url, fetched_at=datetime.now(timezone.utc).isoformat())
    return result


async def fetch_loan_history(
    page: Page, *, start_date: str | None = None, end_date: str | None = None, page_number: int = 1,
) -> dict:
    return await _fetch_history_page(
        page, "/myloan/history", parse_loan_history,
        start_date=start_date, end_date=end_date, page_number=page_number,
    )


async def fetch_reservation_history(page: Page, *, page_number: int = 1) -> dict:
    return await _fetch_history_page(page, "/myreserve/integratedhistory", parse_reservation_history, page_number=page_number)


# --------------------------------------------------------------------------- #
# Scrapers
# --------------------------------------------------------------------------- #

async def fetch_my_loans(page: Page) -> dict:
    """Return the student's current library loans (대출 현황).

    Each loan carries: 서명/저자(title_author), 소장처(location), 등록번호(reg_no),
    대출일(loan_date), 반납예정일(due_date), 연체료(overdue_fee),
    연장횟수(renew_count). Personal data — never logged. An empty list means no
    books are currently on loan.
    """
    await page.goto(MYLOAN_URL, wait_until="domcontentloaded")
    await page.wait_for_selector("table.mobileTable tbody tr", timeout=15_000)
    return parse_my_loans(await page.content())


async def fetch_my_reservations(page: Page) -> dict:
    """Read existing book holds only; never submit cancellation or renewal actions."""
    await page.goto(MYRESERVE_URL, wait_until="domcontentloaded")
    await page.wait_for_selector("table.mobileTable tbody tr", timeout=15_000)
    return parse_my_reservations(await page.content())


# --------------------------------------------------------------------------- #
# Reading-room seats (login required; NOT personal data)
# --------------------------------------------------------------------------- #

_SEATROOM_JS = r"""
() => {
  const t = document.querySelector('table.seatTbl') || document.querySelector('table');
  if (!t) return { rows: [] };
  const rows = [];
  t.querySelectorAll('tbody tr').forEach(tr => {
    const cells = Array.from(tr.querySelectorAll('td'))
      .map(c => (c.innerText || '').replace(/\s+/g, ' ').trim());
    if (cells.filter(c => c).length <= 1) return;
    rows.push(cells);
  });
  return { rows };
}
"""

# Status badges appended to the room name cell.
_SEAT_STATUS = ("배정불가", "배정가능", "좌석배정", "FULL")


def _to_int(text: str | None) -> int | None:
    if not text:
        return None
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else None


def _parse_seat_room(cells: list[str]) -> dict:
    # Columns: 실명 / 전체좌석 / 사용중 / 이용가능석 / 운영시간 / 이용률 / 추가정보안내
    name = cells[0] if len(cells) > 0 else ""
    assignable: bool | None = None
    for status in _SEAT_STATUS:
        if name.endswith(status):
            assignable = status in {"배정가능", "좌석배정"}
            name = name[: -len(status)].strip()
            break

    # 전체좌석 cell looks like "134(136)" -> operating(capacity), or plain int.
    total_cell = cells[1] if len(cells) > 1 else ""
    operating = capacity = None
    if "(" in total_cell and ")" in total_cell:
        head, _, tail = total_cell.partition("(")
        operating = _to_int(head)
        capacity = _to_int(tail)
    else:
        operating = _to_int(total_cell)

    usage_raw = cells[5] if len(cells) > 5 else ""
    usage_pct: float | None = None
    digits = usage_raw.replace("%", "").strip()
    if digits:
        try:
            usage_pct = float(digits)
        except ValueError:
            usage_pct = None

    return {
        "name": name,
        "assignable": assignable,
        "total": operating,
        "capacity": capacity,
        "in_use": _to_int(cells[2]) if len(cells) > 2 else None,
        "available": _to_int(cells[3]) if len(cells) > 3 else None,
        "hours": cells[4].replace("~ ", "~") if len(cells) > 4 else None,
        "usage_pct": usage_pct,
        "note": cells[6] if len(cells) > 6 and cells[6] else None,
    }


def parse_seat_rooms(html: str) -> dict:
    """Validate the exact source table and keep allocation status separate."""
    table = BeautifulSoup(html, "html.parser").select_one("table.seatTbl")
    expected = ["실명", "전체좌석", "사용중", "이용가능석", "운영시간", "이용률", "추가정보안내"]
    if table is None:
        raise ScrapeFailedError("열람실 좌석 표를 확인하지 못했습니다. 0석을 의미하지 않습니다.")
    headers = [cell.get_text(strip=True) for cell in table.select("th")]
    if not set(expected) <= set(headers):
        raise ScrapeFailedError("열람실 좌석 표의 열 구성이 변경되었습니다.")
    rooms = []
    source_totals = None
    for row in table.select("tbody tr"):
        raw_cells = row.find_all("td", recursive=False)
        cells = [cell.get_text(" ", strip=True) for cell in raw_cells]
        if len(raw_cells) == 1 and raw_cells[0].get("colspan") == str(len(headers)) and not cells[0]:
            continue
        if len(cells) != len(headers):
            raise ScrapeFailedError("열람실 좌석 행 구성을 확인하지 못했습니다.")
        ordered = [cells[headers.index(header)] for header in expected]
        if not re.fullmatch(r"[0-9,]+(?:\([0-9,]+\))?", ordered[1]) or any(not re.fullmatch(r"[0-9,]+", ordered[index]) for index in (2, 3)):
            raise ScrapeFailedError("열람실 좌석 수가 아직 준비되지 않았습니다.")
        room = _parse_seat_room(ordered)
        if ordered[0] == "합계":
            if source_totals is not None:
                raise ScrapeFailedError("열람실 합계 행이 중복되었습니다.")
            source_totals = room
            continue
        if room["assignable"] is None or room["available"] + room["in_use"] > room["total"]:
            raise ScrapeFailedError("열람실 배정 상태 또는 좌석 합계를 확인하지 못했습니다.")
        rooms.append(room)
    if not rooms:
        raise ScrapeFailedError("열람실 좌석 행이 없습니다. 0석을 의미하지 않습니다.")
    total = sum(room["total"] for room in rooms)
    in_use = sum(room["in_use"] for room in rooms)
    available = sum(room["available"] for room in rooms)
    if source_totals is not None and any(source_totals[key] != value for key, value in {"total": total, "in_use": in_use, "available": available}.items()):
        raise ScrapeFailedError("개별 열람실 합산값과 원문 합계가 다릅니다.")
    return {
        "count": len(rooms), "rooms": rooms, "total": total, "in_use": in_use,
        "available": available,
        "source_totals_match": True if source_totals is not None else None,
        "assignable_available": sum(room["available"] for room in rooms if room["assignable"]),
        "unassignable_rooms": sum(not room["assignable"] for room in rooms),
        "usage_pct": round(in_use / total * 100, 1) if total else 0.0,
        "availability_note": "available은 원문 표시 잔여석입니다. 배정불가 열람실을 제외한 assignable_available과 구분하세요. 실제 착석 가능성을 보장하지 않습니다.",
    }


async def fetch_seat_rooms(page: Page) -> dict:
    """Return per-reading-room seat availability (열람실별 좌석현황, 로그인 필요).

    Each room carries: 실명(name), 배정가능 여부(assignable), 운영좌석(total),
    수용좌석(capacity), 사용중(in_use), 이용가능석(available), 운영시간(hours),
    이용률%(usage_pct), 추가정보(note). Not personal data, but login-gated, so it
    runs through the authenticated library session.
    """
    await page.goto(SEAT_ROOMS_URL, wait_until="domcontentloaded")
    await page.wait_for_selector("table.seatTbl tbody tr", timeout=15_000)
    result = parse_seat_rooms(await page.content())
    parsed_url = urlsplit(page.url)
    result["source_url"] = f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}"
    result["fetched_at"] = datetime.now(timezone.utc).isoformat()
    return result

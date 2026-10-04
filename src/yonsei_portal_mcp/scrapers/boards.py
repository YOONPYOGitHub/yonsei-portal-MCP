"""Read-only LearnUs course board listings, excluding author and restricted text."""
from datetime import datetime
import re
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

from bs4 import BeautifulSoup
from playwright.async_api import Page

from ..errors import ScrapeFailedError
from . import learnus


def validate_id(value: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,20}", value):
        raise ValueError("강좌/게시판 ID는 조회 목록의 숫자 ID여야 합니다.")


def validate_page(page_number: int) -> None:
    if type(page_number) is not int or not 1 <= page_number <= 100:
        raise ValueError("page는 1~100의 정수여야 합니다.")


def _page_value(query: dict) -> int:
    values = query.get("page", ["1"])
    if len(values) != 1 or not re.fullmatch(r"[1-9][0-9]{0,5}", values[0]):
        raise ScrapeFailedError("게시판 페이지 번호를 확인하지 못했습니다.")
    return int(values[0])


def _link(href: str, path: str, board_id: str | None = None) -> tuple[str, dict]:
    parsed = urlsplit(urljoin(learnus.LEARNUS_HOME, href))
    query = parse_qs(parsed.query, keep_blank_values=True)
    required = ("id", "bwid") if path.endswith("article.php") else ("id",)
    try:
        valid = (
            parsed.scheme == "https" and parsed.hostname == "ys.learnus.org"
            and parsed.port in (None, 443) and parsed.username is None and parsed.password is None
            and parsed.path == path and set(query) <= {*required, "lang", "page"}
            and all(len(query.get(key, [])) == 1 and re.fullmatch(r"[0-9]{1,20}", query[key][0]) for key in required)
        )
    except ValueError:
        valid = False
    if not valid or (board_id is not None and query["id"] != [board_id]):
        raise ScrapeFailedError("게시판 링크의 출처 또는 식별자를 확인하지 못했습니다.")
    _page_value(query)
    values = {key: query[key][0] for key in required}
    return learnus.LEARNUS_HOME.rstrip("/") + path + "?" + urlencode(values), values


def _hidden(element) -> bool:
    return any(
        parent.has_attr("hidden") or bool(set(parent.get("class", [])) & {"hidden", "d-none", "accesshide"})
        or bool(re.search(r"(?:^|;)\s*(?:display\s*:\s*none|visibility\s*:\s*(?:hidden|collapse))\s*(?:!important\s*)?(?:;|$)", parent.get("style", ""), re.I))
        for parent in [element, *element.parents]
    )


def _text(element) -> str:
    if _hidden(element):
        return ""
    clone = BeautifulSoup(str(element), "html.parser")
    for child in reversed(clone.find_all(True)):
        if child.name in {"script", "style"} or _hidden(child):
            child.decompose()
    return " ".join(clone.get_text(" ", strip=True).split())


def parse_boards(html: str, course_id: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.select("table.ubboard_table")
    if not tables:
        raise ScrapeFailedError("LearnUs 강좌 게시판 목록을 확인하지 못했습니다.")
    records, seen = [], set()
    for table in tables:
        headers = [_text(cell) for cell in table.select(":scope > thead th")]
        if headers not in (["게시판명", "게시물 수", "최근 업데이트일"], ["구분", "게시판명", "게시물 수", "최근 업데이트일"]):
            raise ScrapeFailedError("LearnUs 게시판 목록의 열 구성이 변경되었습니다.")
        rows = table.select(":scope > tbody > tr")
        if not rows:
            raise ScrapeFailedError("LearnUs 게시판 목록의 결과 상태가 없습니다.")
        for row in rows:
            cells = row.find_all("td", recursive=False)
            if len(rows) == 1 and len(cells) == 1 and cells[0].get("colspan") == str(len(headers)) and _text(cells[0]) == "생성된 게시판이 없습니다.":
                continue
            if len(cells) != len(headers):
                raise ScrapeFailedError("LearnUs 게시판 행 구성이 변경되었습니다.")
            title_cell = cells[headers.index("게시판명")]
            anchors = [anchor for anchor in title_cell.select("a[href]") if not _hidden(anchor)]
            count = _text(cells[headers.index("게시물 수")])
            if len(anchors) != 1 or not _text(anchors[0]) or not re.fullmatch(r"[0-9]+", count):
                raise ScrapeFailedError("게시판 이름·링크·게시물 수를 확인하지 못했습니다.")
            url, identifiers = _link(str(anchors[0]["href"]), "/mod/ubboard/view.php")
            if identifiers["id"] in seen:
                raise ScrapeFailedError("게시판 ID가 중복되었습니다.")
            seen.add(identifiers["id"])
            records.append({"board_id": identifiers["id"], "name": _text(anchors[0]), "post_count": int(count), "updated_raw": _text(cells[headers.index("최근 업데이트일")]), "url": url})
    return {"course_id": course_id, "count": len(records), "boards": records}


def _pagination(soup, board_id: str, page_number: int) -> dict:
    containers = [node for node in soup.select(".pagination,.paging") if not _hidden(node)]
    pages, active = set(), set()
    for container in containers:
        for node in container.select('.active,[aria-current="page"]'):
            if _hidden(node):
                continue
            label = _text(node)
            if not re.fullmatch(r"[1-9][0-9]{0,5}", label):
                raise ScrapeFailedError("게시판의 현재 페이지 표시를 확인하지 못했습니다.")
            active.add(int(label))
        for anchor in container.select("a[href]"):
            if _hidden(anchor):
                continue
            href = str(anchor["href"])
            if href in ("", "#"):
                continue
            _link(href, "/mod/ubboard/view.php", board_id)
            query = parse_qs(urlsplit(urljoin(learnus.LEARNUS_HOME, href)).query, keep_blank_values=True)
            pages.add(_page_value(query))
    if containers:
        if active != {page_number}:
            raise ScrapeFailedError("요청한 게시판 페이지와 현재 페이지 표시가 다릅니다.")
    elif page_number != 1:
        raise ScrapeFailedError("후속 게시판 페이지의 선택 상태를 확인하지 못했습니다.")
    higher = {number for number in pages if number > page_number}
    next_page = page_number + 1 if higher else None
    if next_page is not None and next_page not in pages:
        raise ScrapeFailedError("연속된 다음 게시판 페이지 링크를 확인하지 못했습니다.")
    capped = next_page is not None and next_page > 100
    return {
        "page": page_number, "page_verified": True, "has_pagination": bool(containers),
        "has_next": next_page is not None, "next_page": next_page,
        "next_request": {"board_id": board_id, "page": next_page} if next_page and not capped else None,
        "page_limit_reached": capped,
    }


def parse_posts(html: str, board_id: str, page_number: int = 1) -> dict:
    validate_id(board_id)
    validate_page(page_number)
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.select("table.ubboard_table")
    if len(tables) != 1:
        raise ScrapeFailedError("LearnUs 게시글 목록을 확인하지 못했습니다.")
    table = tables[0]
    headers = [_text(cell) for cell in table.select(":scope > thead th")]
    if headers != ["번호", "제목", "작성자", "작성일", "조회수"]:
        raise ScrapeFailedError("LearnUs 강좌 게시글 목록의 열 구성이 변경되었습니다.")
    rows = table.select(":scope > tbody > tr")
    if not rows:
        raise ScrapeFailedError("LearnUs 게시글 결과 상태를 확인하지 못했습니다.")
    posts, unlinked, seen = [], 0, set()
    for row in rows:
        cells = row.find_all("td", recursive=False)
        if len(rows) == 1 and len(cells) == 1 and cells[0].get("colspan") == "5" and _text(cells[0]) == "등록된 게시글이 없습니다.":
            continue
        if len(cells) != 5:
            raise ScrapeFailedError("LearnUs 게시글 행 구성이 변경되었습니다.")
        anchors = [anchor for anchor in cells[1].select("a[href]") if not _hidden(anchor)]
        if not anchors:
            unlinked += 1
            continue
        if len(anchors) != 1 or not _text(anchors[0]):
            raise ScrapeFailedError("LearnUs 게시글 제목·링크를 확인하지 못했습니다.")
        url, identifiers = _link(str(anchors[0]["href"]), "/mod/ubboard/article.php", board_id)
        if identifiers["bwid"] in seen:
            continue
        seen.add(identifiers["bwid"])
        posts.append({"post_id": identifiers["bwid"], "title": _text(anchors[0]), "date_raw": _text(cells[3]), "url": url})
    return {"board_id": board_id, "count": len(posts), "posts": posts, "unlinked_count": unlinked,
            "scope": "displayed_page", **_pagination(soup, board_id, page_number),
            "note": "선택한 강좌 게시판 페이지입니다. 작성자와 링크 없는 글의 제목·본문은 제외합니다. count는 전체 글 수가 아니며 마지막 페이지라도 앞 페이지까지 수집했다는 뜻은 아닙니다."}


async def fetch_boards(page: Page, course_id: str) -> dict:
    validate_id(course_id)
    url = learnus.LEARNUS_HOME + "mod/ubboard/index.php?" + urlencode({"id": course_id})
    await learnus._goto_korean(page, url)
    await page.wait_for_selector("table.ubboard_table tbody tr", timeout=15_000)
    html = await page.content()
    learnus._require_page_url(page.url, url)
    result = parse_boards(html, course_id)
    result.update(source_url=page.url, fetched_at=datetime.now(learnus.KST).isoformat())
    return result


async def fetch_posts(page: Page, board_id: str, page_number: int = 1) -> dict:
    validate_id(board_id)
    validate_page(page_number)
    query = {"id": board_id}
    if page_number != 1:
        query["page"] = str(page_number)
    url = learnus.LEARNUS_HOME + "mod/ubboard/view.php?" + urlencode(query)
    await learnus._goto_korean(page, url)
    await page.wait_for_selector("table.ubboard_table tbody tr", timeout=15_000)
    html = await page.content()
    learnus._require_page_url(page.url, url)
    result = parse_posts(html, board_id, page_number)
    result.update(source_url=page.url, fetched_at=datetime.now(learnus.KST).isoformat())
    return result


def validate_search(board_id: str, query: str, max_pages: int, limit: int) -> None:
    validate_id(board_id)
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= 200:
        raise ValueError("query는 1~200자의 검색어여야 합니다.")
    if type(max_pages) is not int or not 1 <= max_pages <= 10:
        raise ValueError("max_pages는 1~10의 정수여야 합니다.")
    if type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError("limit는 1~50의 정수여야 합니다.")


async def search_posts(page: Page, board_id: str, query: str, max_pages: int = 3, limit: int = 20) -> dict:
    """Search linked titles only, following verified pages without reading bodies."""
    validate_search(board_id, query, max_pages, limit)
    unique, scanned, sources = {}, [], []
    duplicates = unlinked = 0
    number = 1
    for _ in range(max_pages):
        result = await fetch_posts(page, board_id, number)
        scanned.append(number)
        if result.get("source_url"):
            sources.append(result["source_url"])
        unlinked += result["unlinked_count"]
        for post in result["posts"]:
            identifier = post["post_id"]
            if identifier in unique:
                if unique[identifier] != post:
                    raise ScrapeFailedError("페이지 수집 중 같은 게시글의 정보가 달라졌습니다.")
                duplicates += 1
            else:
                unique[identifier] = post
        if not result["has_next"] or result["next_request"] is None:
            break
        following = result["next_page"]
        if following != number + 1:
            raise ScrapeFailedError("게시판 페이지가 순서대로 진행되지 않았습니다.")
        number = following
    terms = query.casefold().split()
    matches = [post for post in unique.values() if all(term in post["title"].casefold() for term in terms)]
    selected = matches[:limit]
    return {
        "board_id": board_id, "query": query.strip(), "count": len(selected), "posts": selected,
        "matching_count": len(matches), "scanned_pages": scanned, "scanned_posts": len(unique),
        "duplicates_removed": duplicates, "unlinked_count": unlinked,
        "has_more_pages": result["has_next"], "result_truncated": len(matches) > limit,
        "next_request": {"tool": "get_lms_board_posts", "arguments": result["next_request"]} if result["next_request"] else None,
        "scope": "linked_titles_in_scanned_pages", "source_urls": sources,
        "fetched_at": datetime.now(learnus.KST).isoformat(),
        "note": "선택 게시판의 첫 페이지부터 제한된 페이지까지 제목만 검색합니다. 공백으로 구분한 모든 검색어가 포함된 제목을 반환하며 중복 고정글은 한 번만 셉니다. 본문·작성자·링크 없는 글은 검색하지 않습니다. has_more_pages이면 후속 페이지는 미검색이며 0건도 게시판 전체에 없다는 뜻이 아닙니다. 선택한 본문은 get_notice로 별도 조회하세요.",
    }
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


def _link(href: str, path: str, board_id: str | None = None) -> tuple[str, dict]:
    parsed = urlsplit(urljoin(learnus.LEARNUS_HOME, href))
    query = parse_qs(parsed.query, keep_blank_values=True)
    required = ("id", "bwid") if path.endswith("article.php") else ("id",)
    try:
        valid = (
            parsed.scheme == "https" and parsed.hostname == "ys.learnus.org"
            and parsed.port in (None, 443) and not parsed.username and not parsed.password
            and parsed.path == path and set(query) <= {*required, "lang"}
            and all(len(query.get(key, [])) == 1 and re.fullmatch(r"[0-9]{1,20}", query[key][0]) for key in required)
        )
    except ValueError:
        valid = False
    if not valid or (board_id is not None and query["id"] != [board_id]):
        raise ScrapeFailedError("게시판 링크의 출처 또는 식별자를 확인하지 못했습니다.")
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


def parse_posts(html: str, board_id: str) -> dict:
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
    return {"board_id": board_id, "count": len(posts), "posts": posts, "unlinked_count": unlinked, "scope": "displayed_page", "has_pagination": bool(soup.select(".pagination a,.paging a")), "note": "강좌 게시판의 첫 표시 페이지입니다. 작성자와 링크 없는 글의 제목·본문은 제외합니다. count는 전체 글 수가 아닙니다."}


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


async def fetch_posts(page: Page, board_id: str) -> dict:
    validate_id(board_id)
    url = learnus.LEARNUS_HOME + "mod/ubboard/view.php?" + urlencode({"id": board_id})
    await learnus._goto_korean(page, url)
    await page.wait_for_selector("table.ubboard_table tbody tr", timeout=15_000)
    html = await page.content()
    learnus._require_page_url(page.url, url)
    result = parse_posts(html, board_id)
    result.update(source_url=page.url, fetched_at=datetime.now(learnus.KST).isoformat())
    return result
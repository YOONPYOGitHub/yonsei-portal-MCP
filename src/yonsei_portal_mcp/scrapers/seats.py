"""Read the actual public homepage seat table in an anonymous browser.

Displayed columns can disagree with API keys and even with their own totals.
Preserve the displayed values and flag inconsistencies instead of repairing them.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urlsplit

from playwright.async_api import Error as PlaywrightError, Page, TimeoutError as PlaywrightTimeoutError, async_playwright

from ..errors import ScrapeFailedError, UpstreamTimeoutError

HOMEPAGE_URL = "https://library.yonsei.ac.kr/"
_DISPLAY_TABLES_JS = """() => [...document.querySelectorAll('table')]
    .filter(table => table.querySelector('tr.central,tr.academic') && !table.closest('.slick-cloned'))
    .map(table => ({
        headers: [...table.querySelectorAll('th')].map(cell => cell.innerText.trim()),
        rows: [...table.querySelectorAll('tbody tr')].map(row => ({
            building: row.querySelector('.type')?.textContent.trim(),
            kind: row.querySelector('.name')?.textContent.trim(),
            cells: [...row.querySelectorAll('td')].slice(1).map(cell => cell.textContent.trim())
        }))
    }))"""

# JSON key prefixes -> human label. Building mapping is the library's own
# wording (확인 2026-05-31; exact building identity is the site's, not ours).
_BUILDINGS = {
    "center": "중앙도서관",
    "yonsei": "학술정보원",
}
# Homepage seat-type labels; occupancy semantics remain unverified.
_SEAT_TYPES = {
    "general": "일반열람석",
    "pc": "PC석",
    "study": "스터디룸",
    "notebook": "노트북석",
}


def _summarize_displayed(rows: list[dict]) -> dict:
    return {
        "rows": rows,
        **{field: sum(row[field] for row in rows) for field in ("total", "in_use", "remaining")},
        "usage_pct": None,
        "scope": "homepage_display",
        "totals_scope": "sum_of_displayed_rows",
        "display_verified": True,
        "semantics_verified": False,
        "source_totals_match": all(row["source_totals_match"] for row in rows),
    }


def parse_displayed_seats(tables: list[dict]) -> dict:
    buildings = {"중앙": "center", "학술": "yonsei"}
    kinds = {"일반좌석": "general", "노트북좌석": "notebook", "PC좌석": "pc", "그룹스터디룸": "study"}
    rows, seen = [], set()
    if not isinstance(tables, list):
        raise ScrapeFailedError("공개 좌석 화면의 표를 확인하지 못했습니다.")
    for table in tables:
        if not isinstance(table, dict) or table.get("headers") != ["열람실", "전체", "사용", "잔여석"] or not isinstance(table.get("rows"), list):
            raise ScrapeFailedError("공개 좌석 화면의 열 구성이 변경되었습니다.")
        for original in table["rows"]:
            if not isinstance(original, dict) or original.get("building") not in buildings or original.get("kind") not in kinds:
                raise ScrapeFailedError("공개 좌석 화면의 건물 또는 유형을 확인하지 못했습니다.")
            cells = original.get("cells")
            if not isinstance(cells, list) or len(cells) != 3 or any(not isinstance(value, str) or not re.fullmatch(r"(?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)", value) for value in cells):
                raise ScrapeFailedError("공개 좌석 화면의 수치가 준비되지 않았습니다.")
            building, kind = buildings[original["building"]], kinds[original["kind"]]
            identity = (building, kind)
            if identity in seen:
                raise ScrapeFailedError("공개 좌석 화면에 같은 건물·유형 행이 중복됩니다.")
            seen.add(identity)
            total, in_use, remaining = (int(value.replace(",", "")) for value in cells)
            rows.append({
                "building": _BUILDINGS[building], "building_code": building,
                "seat_type": _SEAT_TYPES[kind], "seat_type_code": kind,
                "building_label_raw": original["building"], "seat_type_label_raw": original["kind"],
                "total": total, "in_use": in_use, "remaining": remaining, "usage_pct": None,
                "source_totals_match": total == in_use + remaining,
            })
    if seen != {(building, kind) for building in buildings.values() for kind in kinds.values()}:
        raise ScrapeFailedError("공개 좌석 화면의 일부 행이 누락되었습니다.")
    return _summarize_displayed(rows)


def _summarize(rows: list[dict]) -> dict:
    total = sum(row["total"] for row in rows)
    raw_use = sum(row["raw_use"] for row in rows)
    return {
        "rows": rows, "total": total, "raw_use": raw_use,
        "raw_total_minus_use": total - raw_use,
        "in_use": None, "remaining": None, "usage_pct": None,
        "semantics_verified": False, "scope": "public_widget_api",
    }


def _parse(data: dict) -> dict:
    required = {f"{building}_{kind}_{field}" for building in _BUILDINGS for kind in _SEAT_TYPES for field in ("total", "use")}
    if not isinstance(data, dict) or not required <= data.keys():
        raise ScrapeFailedError("공개 좌석 응답 필드가 누락되었습니다. 0석을 의미하지 않습니다.")
    if any(type(data[key]) is not int or data[key] < 0 for key in required):
        raise ScrapeFailedError("공개 좌석 응답에 유효하지 않은 숫자가 있습니다.")
    rows: list[dict] = []
    for bkey, bname in _BUILDINGS.items():
        for tkey, tname in _SEAT_TYPES.items():
            total = data[f"{bkey}_{tkey}_total"]
            use = data[f"{bkey}_{tkey}_use"]
            if use > total:
                raise ScrapeFailedError("공개 좌석 원문 use 값이 total보다 큽니다.")
            if total == 0 and use == 0:
                continue  # category not offered in this building
            rows.append(
                {
                    "building": bname,
                    "building_code": bkey,
                    "seat_type": tname,
                    "seat_type_code": tkey,
                    "total": total,
                    "raw_use": use,
                    "raw_total_minus_use": total - use,
                    "in_use": None,
                    "remaining": None,
                    "usage_pct": None,
                }
            )

    return _summarize(rows)


async def read_displayed_tables(page: Page) -> list[dict]:
    await page.goto(HOMEPAGE_URL, wait_until="domcontentloaded", timeout=30_000)
    if (urlsplit(page.url).scheme, urlsplit(page.url).hostname) != ("https", "library.yonsei.ac.kr"):
        raise ScrapeFailedError("공개 좌석 홈페이지의 출처가 요청과 다릅니다.")
    await page.wait_for_function("typeof seatInfo === 'function'", timeout=15_000)
    async with page.expect_response(lambda response: urlsplit(response.url).hostname == "library.yonsei.ac.kr" and urlsplit(response.url).path == "/seat/info" and response.request.method == "POST", timeout=15_000) as pending:
        await page.evaluate("seatInfo()")
    response = await pending.value
    if not response.ok:
        raise ScrapeFailedError("홈페이지 좌석 갱신 요청이 실패했습니다.")
    _parse(await response.json())
    await page.wait_for_function("window.jQuery && jQuery.active === 0", timeout=15_000)
    return await page.evaluate(_DISPLAY_TABLES_JS)


async def _fetch_displayed_tables() -> list[dict]:
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            try:
                page = await browser.new_page(viewport={"width": 1280, "height": 900})
                return await read_displayed_tables(page)
            finally:
                await browser.close()
    except PlaywrightTimeoutError:
        raise UpstreamTimeoutError("공개 좌석 화면의 갱신을 제시간 내 확인하지 못했습니다.") from None
    except PlaywrightError:
        raise ScrapeFailedError("공개 좌석 화면을 읽지 못했습니다. Chromium 설치와 사이트 연결을 확인하세요.") from None


async def fetch_seats(seat_type: str | None = None) -> dict:
    """Return displayed seat values without account credentials; Chromium required."""
    code = None
    if seat_type is not None and seat_type != "":
        if not isinstance(seat_type, str):
            raise ValueError("seat_type은 지원 좌석 유형 문자열이어야 합니다.")
        wanted = seat_type.strip().lower()
        for tkey, tname in _SEAT_TYPES.items():
            if wanted in (tkey, tname.lower()):
                code = tkey
                break
        if code is None:
            raise ValueError("seat_type은 general/pc/study/notebook 또는 해당 한글 유형명이어야 합니다.")
    result = parse_displayed_seats(await _fetch_displayed_tables())
    if code is not None:
        result = _summarize_displayed([row for row in result["rows"] if row["seat_type_code"] == code])
    result.update(
        source_url=HOMEPAGE_URL,
        fetched_at=datetime.now(timezone.utc).isoformat(),
        availability_note="홈페이지의 전체/사용/잔여석 표에 표시된 값입니다. API 키 이름으로 재해석하지 않았습니다. source_totals_match=false는 화면 자체의 합계 모순이며 값을 보정하지 않습니다. 최상위 합계는 표시 행의 합산일 뿐 전체 도서관 수용력이나 실제 착석·예약 가능성을 보장하지 않습니다. usage_pct는 화면에 없어 null입니다. 세미나룸 시간대별 예약 조회와는 별개입니다.",
    )
    return result

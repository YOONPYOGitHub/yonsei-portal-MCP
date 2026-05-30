"""학사행정(ERP, underwood1.yonsei.ac.kr) scrapers.

The ERP is a WebSquare MDI app whose grids stay stuck on "LOADING..." when run
headless, so we do **not** scrape the DOM. Instead each scraper navigates the
left-menu to the relevant screen and captures the JSON the screen fetches from
its ``*.do`` endpoints via a ``page.on("response")`` listener (DESIGN §10.2 —
the "hybrid" philosophy: drive the UI just enough, read the data API).

Endpoints (validated live):
- ``findMyGLIOList.do``        → ``dmGlio``           : student profile (name/dept/no)
- ``findAccpsStdSchdlList.do`` → ``dsSyySmtDivCd``    : enrolled terms + credit totals
- ``findAccpcsStdList.do``     → ``dsSles450``        : registered courses (= timetable)
- ``findAllGradeDtlAsSyySmtList.do`` → ``dsSgra100/120`` : grade history (empty pre-1st term)

All of this is **personal** data; it is never logged, only returned to the
calling LLM.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, List, Optional

from playwright.async_api import Page

from ..config import ERP_URL
from ..errors import ScrapeFailedError

# --------------------------------------------------------------------------- #
# Menu navigation + JSON capture helper
# --------------------------------------------------------------------------- #

_DAY_MAP = {
    "월": "Mon", "화": "Tue", "수": "Wed", "목": "Thu",
    "금": "Fri", "토": "Sat", "일": "Sun",
}
_TIME_RE = re.compile(r"([월화수목금토일])?\s*(\d+)")


async def _open_menu_and_capture(
    page: Page,
    category: str,
    leaf: str,
    want: Dict[str, str],
    *,
    settle_ms: int = 12_000,
) -> Dict[str, Any]:
    """Click ``category`` → ``leaf`` in the ERP left menu and collect JSON.

    ``want`` maps a result key to a URL fragment to match. Returns a dict of the
    captured (parsed) JSON keyed by ``want``'s keys. Endpoints that fire more
    than once keep their latest payload.
    """
    captured: Dict[str, Any] = {}

    async def on_response(resp) -> None:
        try:
            url = resp.url
            if "underwood1.yonsei.ac.kr" not in url:
                return
            for key, frag in want.items():
                if frag in url:
                    ct = resp.headers.get("content-type", "")
                    if "json" not in ct:
                        return
                    body = await resp.text()
                    captured[key] = json.loads(body)
        except Exception:
            # Never let a listener error bubble up into Playwright.
            pass

    page.on("response", on_response)
    try:
        # ensure_authenticated() already left us on the ERP shell; make sure.
        if "underwood1.yonsei.ac.kr" not in page.url:
            await page.goto(ERP_URL, wait_until="domcontentloaded")
            await page.wait_for_timeout(1_500)

        mf = page.main_frame
        try:
            await mf.get_by_text(category, exact=True).first.click(timeout=15_000)
        except Exception as exc:  # noqa: BLE001
            raise ScrapeFailedError(
                f"ERP 좌측 메뉴에서 '{category}' 카테고리를 열지 못했습니다."
            ) from exc
        await page.wait_for_timeout(1_200)
        try:
            await mf.get_by_text(leaf, exact=True).first.click(timeout=15_000)
        except Exception as exc:  # noqa: BLE001
            raise ScrapeFailedError(
                f"ERP 메뉴에서 '{leaf}' 화면을 열지 못했습니다."
            ) from exc

        # Poll until every wanted endpoint responded or we hit the settle budget.
        deadline = time.monotonic() + settle_ms / 1000
        while time.monotonic() < deadline:
            await page.wait_for_timeout(400)
            if all(k in captured for k in want):
                break
    finally:
        page.remove_listener("response", on_response)

    return captured


# --------------------------------------------------------------------------- #
# Parsers
# --------------------------------------------------------------------------- #


def _parse_time(raw: Optional[str]) -> List[Dict[str, Any]]:
    """Parse a lecture-time string like ``화2`` / ``화2,3`` / ``월2화3``."""
    slots: List[Dict[str, Any]] = []
    if not raw:
        return slots
    cur_day: Optional[str] = None
    for m in _TIME_RE.finditer(raw):
        day_ch, period = m.group(1), m.group(2)
        if day_ch:
            cur_day = day_ch
        if cur_day is None:
            continue
        slots.append(
            {
                "day": cur_day,
                "day_en": _DAY_MAP.get(cur_day),
                "period": int(period),
            }
        )
    return slots


def _parse_profile(glio: Dict[str, Any], terms: Dict[str, Any]) -> Dict[str, Any]:
    dm = (glio or {}).get("dmGlio") or {}
    term_rows = (terms or {}).get("dsSyySmtDivCd") or []
    # Latest term is the highest code (e.g. 202610).
    current = None
    if term_rows:
        current = max(term_rows, key=lambda r: str(r.get("code", "")))
    return {
        "name": dm.get("userNm"),
        "student_no": dm.get("persNo"),
        "department": dm.get("deptNm"),
        "department_full": dm.get("deptTtNm"),
        "department_code": dm.get("deptCd"),
        "current_term": (current or {}).get("fullNm"),
        "current_term_credits": (current or {}).get("cdtTot"),
        "terms": [
            {
                "term": r.get("fullNm"),
                "year": r.get("syy"),
                "code": r.get("code"),
                "credits": r.get("cdtTot"),
            }
            for r in term_rows
        ],
    }


def _parse_timetable(enroll: Dict[str, Any]) -> Dict[str, Any]:
    rows = (enroll or {}).get("dsSles450") or []
    courses: List[Dict[str, Any]] = []
    total_credits = 0
    for r in rows:
        credits = r.get("cdt")
        try:
            total_credits += int(credits) if credits is not None else 0
        except (TypeError, ValueError):
            pass
        courses.append(
            {
                "course_code": r.get("subjtnb"),
                "section": r.get("corseDvclsNo"),
                "course_name": r.get("subjtNm"),
                "course_name_en": r.get("subjtEngNm"),
                "professor": r.get("cgprfNm"),
                "professor_en": r.get("cgprfEngNm"),
                "credits": credits,
                "category": r.get("subsrtDivNm"),
                "room": r.get("lecrmNm"),
                "time_raw": r.get("lctreTimeNm"),
                "time_en": r.get("lctreTimeEngNm"),
                "slots": _parse_time(r.get("lctreTimeNm")),
            }
        )
    term = None
    if rows:
        syy = rows[0].get("syy")
        smt = rows[0].get("smtDivNm")
        if syy and smt:
            term = f"{syy}-{smt}"
    return {
        "term": term,
        "count": len(courses),
        "total_credits": total_credits,
        "courses": courses,
    }


def _parse_grades(data: Dict[str, Any]) -> Dict[str, Any]:
    """Parse the grade datasets. Empty before the first completed term."""
    data = data or {}
    course_rows = data.get("dsSgra120") or []
    term_rows = data.get("dsSgra100") or []
    info_rows = data.get("dsStdntInfo") or []

    courses = [
        {
            "term": r.get("fullNm") or _term_label(r),
            "course_code": r.get("subjtnb"),
            "course_name": r.get("subjtNm"),
            "credits": r.get("cdt"),
            "grade": r.get("gradeGrdDivNm") or r.get("gradeGrdDivCd"),
            "category": r.get("subsrtDivNm"),
            "professor": r.get("cgprfNm"),
        }
        for r in course_rows
    ]
    summary = info_rows[0] if info_rows else {}
    result = {
        "count": len(courses),
        "courses": courses,
        "terms": term_rows,
        "summary": {
            "total_earned_credits": summary.get("totEarnCdt") or summary.get("erngCdt"),
            "gpa": summary.get("tgpa") or summary.get("avgGrd"),
        },
    }
    if not courses:
        result["note"] = (
            "조회된 성적이 없습니다. 첫 학기 성적이 확정되기 전이거나 "
            "성적 이력이 없는 계정일 수 있습니다."
        )
    return result


def _term_label(row: Dict[str, Any]) -> Optional[str]:
    syy = row.get("syy")
    smt = row.get("smtDivNm") or row.get("smtDivCd")
    if syy and smt:
        return f"{syy}-{smt}"
    return syy


# --------------------------------------------------------------------------- #
# Public scrapers
# --------------------------------------------------------------------------- #


async def fetch_student_profile(page: Page) -> Dict[str, Any]:
    """Return the student's profile + current term/credit summary."""
    cap = await _open_menu_and_capture(
        page,
        "수업",
        "수강신청내역",
        {"glio": "findMyGLIOList.do", "terms": "findAccpsStdSchdlList.do"},
    )
    if "glio" not in cap:
        raise ScrapeFailedError("ERP 학생 프로필 데이터를 받아오지 못했습니다.")
    return _parse_profile(cap.get("glio", {}), cap.get("terms", {}))


async def fetch_timetable(page: Page) -> Dict[str, Any]:
    """Return the current-term registered courses (= personal timetable)."""
    cap = await _open_menu_and_capture(
        page,
        "수업",
        "수강신청내역",
        {"enroll": "findAccpcsStdList.do"},
    )
    if "enroll" not in cap:
        raise ScrapeFailedError("ERP 수강신청내역(시간표) 데이터를 받아오지 못했습니다.")
    return _parse_timetable(cap.get("enroll", {}))


async def fetch_grades(page: Page) -> Dict[str, Any]:
    """Return the full grade history (may be empty before the first term)."""
    cap = await _open_menu_and_capture(
        page,
        "성적",
        "전체성적조회",
        {"grades": "findAllGradeDtlAsSyySmtList.do"},
    )
    if "grades" not in cap:
        raise ScrapeFailedError("ERP 성적 데이터를 받아오지 못했습니다.")
    return _parse_grades(cap.get("grades", {}))

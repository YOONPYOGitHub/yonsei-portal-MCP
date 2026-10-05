"""학사행정(ERP, underwood1.yonsei.ac.kr) scrapers.

The ERP uses cpr/eXBuilder. Each scraper navigates the left menu to the relevant
screen and captures the JSON fetched from its ``*.do`` endpoints via a
``page.on("response")`` listener, without depending on rendered grid cells.

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
from datetime import datetime
from decimal import Decimal, DecimalException, Inexact, localcontext
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

from playwright.async_api import Page

from ..config import ERP_URL, ERP_PROFILE_URL, ERP_GRADES_URL, ERP_TIMETABLE_TERMS_URL, ERP_ENROLLMENT_URL
from ..errors import ScrapeFailedError

# --------------------------------------------------------------------------- #
# Menu navigation + JSON capture helper
# --------------------------------------------------------------------------- #

_DAY_MAP = {
    "월": "Mon", "화": "Tue", "수": "Wed", "목": "Thu",
    "금": "Fri", "토": "Sat", "일": "Sun",
}
_TIME_RE = re.compile(r"([월화수목금토일])?\s*(\d+)")
_TIME_GROUP = r"[월화수목금토일]\s*[1-9][0-9]?(?:\s*,\s*[1-9][0-9]?)*"
_TIME_GRAMMAR = re.compile(rf"\s*{_TIME_GROUP}(?:\s*,?\s*{_TIME_GROUP})*\s*")


_ENDPOINT_PATHS = {
    urlsplit(url).path.rsplit("/", 1)[-1]: urlsplit(url).path
    for url in (ERP_PROFILE_URL, ERP_GRADES_URL, ERP_TIMETABLE_TERMS_URL, ERP_ENROLLMENT_URL)
}
_ENDPOINT_PATHS.update({
    "findSchSlesHandbList.do": "/sch/sles/SlescsCtr/findSchSlesHandbList.do",
    "findExamTimtbList.do": "/sch/sles/SlesapCtr/findExamTimtbList.do",
    "findAtnlcHandbList.do": "/sch/sles/SlessyCtr/findAtnlcHandbList.do",
})


def _matches_erp_url(url: str, endpoint: Optional[str] = None) -> bool:
    """Match an HTTPS origin and exact path (or known endpoint basename)."""
    try:
        parts = urlsplit(url)
        if (parts.scheme != "https" or parts.hostname != "underwood1.yonsei.ac.kr"
                or parts.port not in (None, 443) or parts.username or parts.password):
            return False
        if endpoint is None:
            return True
        path = _ENDPOINT_PATHS.get(endpoint, endpoint)
        return parts.path == path if path.startswith("/") else parts.path.rsplit("/", 1)[-1] == path
    except ValueError:
        return False


async def _open_menu_and_capture(
    page: Page,
    category: str,
    leaf: str,
    want: Dict[str, str],
    *,
    settle_ms: int = 12_000,
) -> Dict[str, Any]:
    """Click ``category`` → ``leaf`` in the ERP left menu and collect JSON.

    ``want`` maps a result key to an exact endpoint path or basename to match. Returns a dict of the
    captured (parsed) JSON keyed by ``want``'s keys. Endpoints that fire more
    than once keep their latest payload.
    """
    captured: Dict[str, Any] = {}

    async def on_response(resp) -> None:
        try:
            url = resp.url
            if not _matches_erp_url(url):
                return
            for key, frag in want.items():
                if _matches_erp_url(url, frag):
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
        if not _matches_erp_url(page.url):
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
    """Parse day/period groups (1-99); ranges and annotations are unsupported."""
    slots: List[Dict[str, Any]] = []
    if not isinstance(raw, str) or not _TIME_GRAMMAR.fullmatch(raw):
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
    dm = glio.get("dmGlio") if isinstance(glio, dict) else None
    term_rows = terms.get("dsSyySmtDivCd") if isinstance(terms, dict) else None
    if not isinstance(dm, dict) or not {"deptNm", "deptTtNm", "deptCd"} <= dm.keys():
        raise ScrapeFailedError("ERP 프로필 데이터셋의 필수 필드를 확인하지 못했습니다.")
    if not isinstance(term_rows, list) or any(not isinstance(row, dict) or not {"code", "fullNm", "syy", "cdtTot"} <= row.keys() for row in term_rows):
        raise ScrapeFailedError("ERP 프로필의 학기 데이터셋을 확인하지 못했습니다. 빈 이력을 의미하지 않습니다.")
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
    """Require explicit rows and finite nonnegative credits with a lossless JSON total."""
    rows = enroll.get("dsSles450") if isinstance(enroll, dict) else None
    if not isinstance(rows, list):
        raise ScrapeFailedError("ERP 시간표 데이터셋을 확인하지 못했습니다.")
    required = {"subjtnb", "corseDvclsNo", "subjtNm"}
    if any(
        not isinstance(row, dict) or any(
            not isinstance(row.get(field), str) or not row[field].strip()
            for field in required
        )
        for row in rows
    ):
        raise ScrapeFailedError("ERP 시간표 과목 식별 필드 구성이 변경되었습니다.")
    courses: List[Dict[str, Any]] = []
    total_credits = Decimal(0)
    for r in rows:
        credits = r.get("cdt")
        try:
            if type(credits) not in (str, int, float):
                raise ValueError
            amount = Decimal(str(credits))
            if not amount.is_finite() or amount < 0:
                raise ValueError
            with localcontext() as context:
                context.traps[Inexact] = True
                total_credits += amount
        except (DecimalException, ValueError):
            raise ScrapeFailedError("ERP 시간표 학점 값을 확인하지 못했습니다.") from None
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
    json_total_credits = int(total_credits) if total_credits == total_credits.to_integral_value() else float(total_credits)
    if Decimal(str(json_total_credits)) != total_credits:
        raise ScrapeFailedError("ERP 시간표 학점 합계를 JSON 숫자로 정확히 표현할 수 없습니다.")
    term = None
    if rows:
        syy = rows[0].get("syy")
        smt = rows[0].get("smtDivNm")
        if syy and smt:
            term = f"{syy}-{smt}"
    return {
        "term": term,
        "count": len(courses),
        "total_credits": json_total_credits,
        "courses": courses,
    }


def _parse_grades(data: Dict[str, Any], year: Optional[int] = None, term_code: Optional[str] = None) -> Dict[str, Any]:
    """Parse the grade datasets. Empty before the first completed term."""
    data = data or {}
    course_rows = data.get("dsSgra100")
    term_rows = data.get("dsSgra120")
    if not isinstance(course_rows, list) or not isinstance(term_rows, list):
        raise ScrapeFailedError("ERP 성적 데이터셋을 확인하지 못했습니다.")
    if any(not isinstance(row, dict) or not {"syy", "smtDivCd", "subjtnb", "subjtNm", "cmpsjCdt"} <= row.keys() for row in course_rows):
        raise ScrapeFailedError("ERP 과목별 성적 필드 구성이 변경되었습니다.")
    if any(not isinstance(row, dict) or not {"syy", "smtDivCd"} <= row.keys() for row in term_rows):
        raise ScrapeFailedError("ERP 학기별 성적 필드 구성이 변경되었습니다.")

    def matches(row):
        return (year is None or str(row["syy"]) == str(year)) and (term_code is None or str(row["smtDivCd"]) == term_code)

    course_rows = [row for row in course_rows if matches(row)]
    term_rows = [row for row in term_rows if matches(row)]
    info_rows = data.get("dsStdntInfo") or []

    courses = [
        {
            "term": r.get("fullNm") or _term_label(r),
            "year": str(r["syy"]),
            "term_code": str(r["smtDivCd"]),
            "course_code": r.get("subjtnb"),
            "course_name": r.get("subjtNm"),
            "credits": r.get("cmpsjCdt"),
            "grade": r.get("gradeDivCdView") or r.get("gradeGrdDivNm") or r.get("gradeGrdDivCd"),
            "category": r.get("subsrtDivNm"),
            "professor": r.get("cgprfNm"),
        }
        for r in course_rows
    ]
    summary = info_rows[0] if info_rows else {}
    result = {
        "count": len(courses),
        "courses": courses,
        "terms": [{key: row[key] for key in ("syy", "smtDivCd", "smtDivNm", "fullNm", "acqsCdt", "bwa") if key in row} for row in term_rows],
        "summary": {
            "total_earned_credits": summary.get("acqsCdt"),
            "gpa": summary.get("bwa"),
        },
        "summary_scope": "all_terms",
        "filters": {"year": year, "term_code": term_code},
    }
    if not courses:
        result["note"] = (
            "선택한 연도/학기에 조회된 성적이 없습니다. 전체 성적 이력이 없다는 의미는 아닙니다."
            if year is not None or term_code is not None else
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
    if not {"glio", "terms"} <= cap.keys():
        raise ScrapeFailedError("ERP 학생 프로필·학기 응답을 모두 받아오지 못했습니다.")
    return _parse_profile(cap["glio"], cap["terms"])


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


async def fetch_grades(page: Page, year: Optional[int] = None, term_code: Optional[str] = None) -> Dict[str, Any]:
    """Return the full grade history (may be empty before the first term)."""
    cap = await _open_menu_and_capture(
        page,
        "성적",
        "전체성적조회",
        {"grades": "findAllGradeDtlAsSyySmtList.do"},
    )
    if "grades" not in cap:
        raise ScrapeFailedError("ERP 성적 데이터를 받아오지 못했습니다.")
    return _parse_grades(cap.get("grades", {}), year, term_code)


def parse_scholarship_history(data: dict) -> dict:
    """Normalize scholarship awards, excluding student and internal identifiers."""
    rows = data.get("dsSscl121")
    required = {"syy", "smtDivCd", "scalNm", "scalApplcAmt", "sclarPymntDt"}
    if not isinstance(rows, list) or any(not isinstance(row, dict) or not required <= row.keys() for row in rows):
        raise ScrapeFailedError("ERP 장학수혜내역 응답 구조를 확인하지 못했습니다.")
    scholarships = [{
        "year": row["syy"], "term_code": row["smtDivCd"], "name": row["scalNm"],
        "amount": row["scalApplcAmt"], "payment_date_raw": row["sclarPymntDt"],
    } for row in rows]
    return {"count": len(scholarships), "scholarships": scholarships}


async def fetch_scholarship_history(page: Page) -> dict:
    """Read scholarship disbursement history without printing or applying."""
    captured = await _open_menu_and_capture(
        page, "장학", "장학수혜내역조회",
        {"scholarships": "findStdntRecfvDtlsList.do"},
    )
    return parse_scholarship_history(captured.get("scholarships", {}))


def parse_exam_schedule(data: dict, term: dict, period: Optional[dict], exam_type: str) -> dict:
    """Distinguish an unavailable viewing period from an empty exam schedule."""
    rows = data.get("dsSles450")
    fields = {
        "subjtnb": "course_code", "corseDvclsNo": "section", "subjtNm": "course_name",
        "examDt": "exam_date_raw", "lessnLestmDivNm": "time_raw", "lecrmNm": "room",
        "examDivNm": "exam_type", "cgprfNm": "professor",
    }
    if not isinstance(rows, list) or any(not isinstance(row, dict) or not fields.keys() <= row.keys() for row in rows):
        raise ScrapeFailedError("ERP 시험시간표 응답 구조를 확인하지 못했습니다.")
    configured = bool(period and period.get("beginDttm"))
    return {
        "term": _term_label(term), "exam_type": exam_type,
        "count": len(rows), "exams": [{key: row[source] for source, key in fields.items()} for row in rows],
        "period_configured": configured,
        "note": None if configured else "등록된 시험시간표 조회 기간이 없습니다. 시험이 없다는 의미는 아닙니다.",
    }


async def fetch_exam_schedule(page: Page, exam_type: str = "default") -> dict:
    """Select an exam type and use the screen's read-only inquiry button."""
    if exam_type not in {"default", "midterm", "final"}:
        raise ValueError("exam_type은 default/midterm/final입니다.")
    captured = await _open_menu_and_capture(
        page, "수업", "시험시간표조회",
        {"period": "findUnvfcYytmScheList.do", "term": "findSlesYytmScheList.do"},
    )
    if "period" not in captured or "term" not in captured:
        raise ScrapeFailedError("ERP 시험시간표 조회 조건이 준비되지 않았습니다.")
    term = captured["term"].get("dmSyySmt")
    if not isinstance(term, dict) or "dmUnvfcSyySmt" not in captured["period"]:
        raise ScrapeFailedError("ERP 시험시간표 학기/조회기간 구조를 확인하지 못했습니다.")
    combo = page.locator('input[role="combobox"]:visible').last
    if exam_type != "default":
        wanted = "중간" if exam_type == "midterm" else "기말"
        if wanted not in await combo.input_value():
            await combo.focus()
            await combo.press("ArrowUp" if exam_type == "midterm" else "ArrowDown")
            await combo.press("Enter")
    selected_exam = await combo.input_value()
    if exam_type != "default" and ("중간" if exam_type == "midterm" else "기말") not in selected_exam:
        raise ScrapeFailedError("요청한 시험구분이 화면에 반영되지 않았습니다.")
    async with page.expect_response(
        lambda response: _matches_erp_url(response.url, "findExamTimtbList.do"),
        timeout=20_000,
    ) as pending:
        await page.get_by_text("조회", exact=True).last.click()
    response = await pending.value
    if not response.ok:
        raise ScrapeFailedError("ERP 시험시간표 조회 요청에 실패했습니다.")
    return parse_exam_schedule(await response.json(), term, captured["period"]["dmUnvfcSyySmt"], selected_exam)


_CATALOG_TERMS = {"10": "1학기", "11": "여름학기", "20": "2학기", "21": "겨울학기"}
_CATALOG_CAMPUSES = {"s1": "학부(신촌)", "s3": "대학원(신촌)", "s7": "의료원(신촌)", "s2": "학부(미래)", "s4": "대학원(미래)", "s8": "의료원(미래)"}


def validate_catalog_filters(year: Optional[int], term_code: Optional[str], campus_code: Optional[str]) -> None:
    if year is not None and (type(year) is not int or not 2003 <= year <= datetime.now().year + 1):
        raise ValueError("year는 2003년부터 다음 연도까지입니다.")
    if term_code is not None and term_code not in _CATALOG_TERMS:
        raise ValueError("term_code는 10/11/20/21입니다.")
    if campus_code is not None and campus_code not in _CATALOG_CAMPUSES:
        raise ValueError("campus_code는 s1/s3/s7(신촌 학부/대학원/의료원), s2/s4/s8(미래)입니다.")


async def select_catalog_option(combo, options: list[str], wanted: str) -> None:
    current = await combo.input_value()
    if current not in options or wanted not in options:
        raise ScrapeFailedError("수강편람 선택지 구성이 변경되었습니다.")
    distance = options.index(wanted) - options.index(current)
    if distance:
        await combo.focus()
        for step in range(abs(distance)):
            await combo.press("ArrowDown" if distance > 0 else "ArrowUp")
        await combo.press("Enter")
    if await combo.input_value() != wanted:
        raise ScrapeFailedError("수강편람 필터 선택이 화면에 반영되지 않았습니다.")


def parse_course_catalog(data: dict, keyword: str, limit: int, filters: dict, *, requested_filters: Optional[dict] = None) -> dict:
    """Return a fetched page, preserving source conditions separately from row scope.

    ``filters`` describes the source request, not guaranteed result scope.
    ``observed_scope`` and ``filter_consistency`` inspect all fetched rows before
    explicit post-filtering and the local limit. Default disagreements retain
    source rows; explicitly requested filters still apply before the limit.
    Observations retain distinct raw values for present fields only. Validation
    compares nonblank string/integer values without rewriting source codes;
    ``missing_count`` includes absent, blank and unsupported row values.
    """
    rows = data.get("dsSles251")
    if not isinstance(rows, list) or any(not isinstance(row, dict) or not {"subjtnb", "subjtNm", "corseDvclsNo"} <= row.keys() for row in rows):
        raise ScrapeFailedError("ERP 수강편람 응답 구조를 확인하지 못했습니다.")
    fetched_count = len(rows)
    requested = {key: value for key, value in (requested_filters or {}).items() if value is not None}
    source_keys = {"year": "syy", "term_code": "smtDivCd", "campus_code": "campsBusnsCd"}
    observed_scope = {}
    consistency = {}
    warnings = []
    for key, source in source_keys.items():
        values = []
        for row in rows:
            value = row.get(source)
            if source in row and not any(type(value) is type(seen) and value == seen for seen in values):
                values.append(value)
        observed_scope[key] = values
        expected = requested.get(key, filters.get(key))
        present = [row[source] for row in rows if type(row.get(source)) in (str, int) and str(row[source]).strip()]
        missing_count = fetched_count - len(present)
        has_expected = type(expected) in (str, int) and bool(str(expected).strip())
        mismatch_count = sum(str(value) != str(expected) for value in present) if has_expected else 0
        status = "mismatch" if mismatch_count else "unverified" if missing_count or not has_expected or not rows else "matched"
        consistency[key] = {
            "expected": expected,
            "origin": "requested" if key in requested else "source" if key in filters else "unspecified",
            "status": status, "mismatch_count": mismatch_count, "missing_count": missing_count,
        }
        if status == "mismatch":
            warnings.append(f"{key}: 조회 조건과 원본 행의 범위가 다릅니다. filters는 반환 행의 범위를 보장하지 않습니다.")
        elif status == "unverified":
            warnings.append(f"{key}: 조회 조건 또는 원본 행의 검증 가능한 값이 없어 범위를 검증하지 못했습니다.")
    for key in requested:
        if any(type(row.get(source_keys[key])) not in (str, int) or not str(row[source_keys[key]]).strip() for row in rows):
            raise ScrapeFailedError("검색 결과에 필터 검증용 필드가 없거나 유효하지 않습니다.")
    rows = [row for row in rows if all(str(row[source_keys[key]]) == str(value) for key, value in requested.items())]
    if fetched_count > len(rows):
        warnings.append(f"명시적으로 요청한 필터와 다른 원본 행 {fetched_count - len(rows)}개를 제외했습니다. 원본 데이터가 없다는 의미는 아닙니다.")
    fields = {
        "syy": "year", "smtDivCd": "term_code", "subjtnb": "course_code",
        "corseDvclsNo": "section", "subjtNm": "course_name", "cgprfNm": "professor",
        "cdt": "credits", "lctreTimeNm": "time_raw", "lecrmNm": "room",
        "estblDeprtNm": "department", "subsrtDivNm": "category",
        "campsBusnsCd": "campus_code",
    }
    courses = [{key: row.get(source) for source, key in fields.items()} for row in rows[:limit]]
    return {
        "keyword": keyword, "filters": filters, "count": len(courses),
        "fetched_count": fetched_count, "matching_count": len(rows),
        "filters_scope": "source_request", "observed_scope": observed_scope,
        "filter_consistency": {"scope": "fetched_rows", "fields": consistency},
        "warnings": warnings, "excluded_count": fetched_count - len(rows),
        "result_status": "source_empty" if not fetched_count else "ok" if rows else "no_matching_rows",
        "requested_filters": requested, "truncated": len(rows) > limit or fetched_count >= 200,
        "courses": courses,
    }


async def fetch_course_catalog(page: Page, keyword: str, limit: int = 20, *, year: Optional[int] = None, term_code: Optional[str] = None, campus_code: Optional[str] = None) -> dict:
    """Search through the catalog UI, preserving its queue and default filters."""
    keyword = keyword.strip()
    if not 2 <= len(keyword) <= 100 or not 1 <= limit <= 50:
        raise ValueError("keyword는 2~100자, limit은 1~50이어야 합니다.")
    validate_catalog_filters(year, term_code, campus_code)
    await _open_menu_and_capture(
        page, "수업", "수강편람", {"ready": "findSchSlesHandbList.do", "term": "findSlesYySmtScheList.do"},
    )
    if year is not None:
        year_input = page.locator('.div_search input[role="spinbutton"]:visible')
        if await year_input.input_value() != str(year):
            async with page.expect_response(lambda response: _matches_erp_url(response.url, "findSchSlesHandbList.do") and str((response.request.post_data_json or {}).get("@d1#syy")) == str(year), timeout=20_000) as updated:
                await year_input.click()
                await year_input.press("ControlOrMeta+A")
                await year_input.press_sequentially(str(year))
                await year_input.press("Tab")
                if await year_input.input_value() != str(year):
                    raise ScrapeFailedError("수강편람 요청 연도가 화면에 반영되지 않았습니다.")
            await (await updated.value).finished()
    combos = page.locator('.div_search input[role="combobox"]:visible')
    for index, code, choices in ((0, term_code, _CATALOG_TERMS), (1, campus_code, _CATALOG_CAMPUSES)):
        if code is not None and await combos.nth(index).input_value() != choices[code]:
            async with page.expect_response(lambda response: _matches_erp_url(response.url, "findSchSlesHandbList.do"), timeout=20_000) as updated:
                await select_catalog_option(combos.nth(index), list(choices.values()), choices[code])
            await (await updated.value).finished()
    keyword_type = page.locator('.div_search input[role="combobox"]:visible').last
    await keyword_type.focus()
    await keyword_type.press("Home")
    await keyword_type.press("ArrowDown")
    await keyword_type.press("Enter")
    if await keyword_type.input_value() != "교과목명":
        raise ScrapeFailedError("ERP 수강편람 교과목명 검색 종류를 선택하지 못했습니다.")
    await page.locator('.div_search input:not([role]):visible').nth(1).fill(keyword)
    async with page.expect_response(
        lambda response: _matches_erp_url(response.url, "findAtnlcHandbList.do"),
        timeout=45_000,
    ) as pending:
        await page.get_by_text("조회", exact=True).last.click()
    response = await pending.value
    if not response.ok:
        raise ScrapeFailedError("ERP 수강편람 조회 요청에 실패했습니다.")
    conditions = response.request.post_data_json or {}
    if conditions.get("@d1#kwd") != keyword or str(conditions.get("@d1#searchGbn")) != "2" or str(conditions.get("@d1#kwdDivCd")) != "2":
        raise ScrapeFailedError("ERP 수강편람 검색어가 조회 조건에 반영되지 않았습니다.")
    filters = {
        key: conditions.get("@d1#" + source)
        for source, key in {"syy": "year", "smtDivCd": "term_code", "campsBusnsCd": "campus_code", "univCd": "college_code", "faclyCd": "department_code", "kwdDivCd": "keyword_type"}.items()
    }
    requested = {"year": year, "term_code": term_code, "campus_code": campus_code}
    if any(value is not None and str(filters.get(key)) != str(value) for key, value in requested.items()):
        raise ScrapeFailedError("수강편람 요청 필터와 서버 조회 조건이 다릅니다.")
    return parse_course_catalog(await response.json(), keyword, limit, filters, requested_filters=requested)

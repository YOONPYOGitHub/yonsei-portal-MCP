"""Yonsei Portal MCP server.

Exposes the student's LearnUs (LMS) data as MCP tools over stdio so an LLM
client (Claude Desktop, VS Code Copilot, MCP Inspector, ...) can answer
questions like "이번 주 과제 마감일 알려줘" or "내 강의 출석 현황 정리해줘".

Authentication uses the credentials in ``.env`` and is handled transparently by
:mod:`yonsei_portal_mcp.session`.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
import re
from typing import Optional
from urllib.parse import urlsplit

import anyio
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import ValidationError

from . import cache, ics
from .config import load_settings
from .scrapers import academic, boards, erp, learnus, library, seats
from .session import close_sessions, get_erp_session, get_library_session, get_session, validate_session_settings


@asynccontextmanager
async def server_lifespan(app: FastMCP):
    try:
        yield
    finally:
        with anyio.CancelScope(shield=True):
            await close_sessions()
        cache.clear()


_STRICT_HISTORY_TOOLS = {"get_my_loan_history", "get_my_reservation_history", "get_lms_course_history"}


class PortalMCP(FastMCP):
    async def list_tools(self):
        tools = await super().list_tools()
        for tool in tools:
            if tool.name in _STRICT_HISTORY_TOOLS:
                tool.inputSchema["additionalProperties"] = False
        return tools

    async def call_tool(self, name: str, arguments: dict):
        if name in _STRICT_HISTORY_TOOLS:
            schema = next(tool.inputSchema for tool in await self.list_tools() if tool.name == name)
            if set(arguments) - set(schema.get("properties", {})):
                raise ToolError("지원하지 않는 이력 조회 인자입니다. 현재 도구 입력 스키마를 확인하세요.")
        try:
            return await super().call_tool(name, arguments)
        except ToolError as exc:
            if name in _STRICT_HISTORY_TOOLS and isinstance(exc.__cause__, ValidationError):
                raise ToolError("이력 조회 입력 형식이 올바르지 않습니다. 현재 도구 입력 스키마를 확인하세요.") from None
            raise


mcp = PortalMCP("yonsei-portal", lifespan=server_lifespan)


def _account() -> str:
    """Cache-key component so different logins never share cached data."""
    settings = load_settings()
    validate_session_settings(settings)
    return settings.yonsei_id or "anon"


@mcp.tool()
async def get_lms_courses() -> list[dict]:
    """수강 중인 LearnUs(LMS) 강좌 목록을 반환합니다.

    각 강좌에는 id, 강좌명(name), 학수번호(code), 담당교수(professor),
    구분(category), 학습 진도율(progress_percent), 강좌 URL, 출석현황 URL이
    포함됩니다.
    """
    key = ("get_lms_courses", _account())
    return await cache.cached(
        key,
        cache.COURSES_TTL,
        lambda: get_session().run(learnus.fetch_courses),
    )


@mcp.tool()
async def get_lms_deadlines(course_id: Optional[str] = None) -> list[dict]:
    """다가오는 과제/활동 마감일(LearnUs 달력의 '예정된 할 일')을 반환합니다.

    course_id 를 주면 해당 강좌의 마감일만 돌려줍니다. 각 항목: 제목(title),
    마감 ISO 시각(due), 원문 마감 문구(due_text), 종류(kind), 강좌 id/이름
    (course_id/course), 출처(source), 상세 URL(url). 결과는 마감 임박 순으로
    정렬됩니다.

    kind 값에 주의하세요. LearnUs '예정된 할 일' 달력에는 실제 제출 과제뿐 아니라
    온라인 강의 진도/수료 마커가 섞여 있습니다.
    - "assignment": 실제 제출해야 하는 과제/활동 마감.
    - "progress": 온라인 강의 수강기간(동영상 진도) 종료 시점. 제출 과제가 아님.
    - "completion": 온라인 과정 수료 권장일(예: 연구윤리). 제출 과제가 아님.
    사용자에게 안내할 때 progress/completion 항목을 '과제 마감'이라고 부르지 말고
    '강의 진도/수료 마감'으로 구분해 설명하세요.
    """
    key = ("get_lms_deadlines", _account(), course_id)
    return await cache.cached(
        key,
        cache.DEADLINES_TTL,
        lambda: get_session().run(
            lambda page: learnus.fetch_deadlines(page, course_id=course_id)
        ),
    )


@mcp.tool()
async def get_lms_notices(scope: str = "all") -> list[dict]:
    """LearnUs 공지사항을 반환합니다.

    scope: "all"(전체), "course"(강좌 공지만), "platform"(플랫폼 공지만).
    각 항목: 유형(type), 강좌명(course), 날짜(date, YYYY-MM-DD), 제목(title), URL.
    """
    if scope not in {"all", "course", "platform"}:
        scope = "all"
    key = ("get_lms_notices", _account(), scope)
    return await cache.cached(
        key,
        cache.NOTICES_TTL,
        lambda: get_session().run(
            lambda page: learnus.fetch_notices(page, scope=scope)
        ),
    )


@mcp.tool()
async def search_notices(
    query: str, scope: str = "all", limit: int = 20
) -> dict:
    """LearnUs 공지사항을 키워드로 통합 검색합니다.

    query 단어가 제목(title) 또는 강좌명(course)에 포함된 공지만 추려서
    반환합니다(대소문자 무시, 공백으로 구분된 모든 단어를 AND 매칭). scope 는
    get_lms_notices 와 동일("all"/"course"/"platform"), limit 으로 최대 건수를
    제한합니다. 반환값: 검색어(query), scope, 전체 일치 수(count), 결과(results).
    각 결과 항목은 get_lms_notices 의 공지 딕셔너리와 동일한 키를 가집니다.
    """
    if scope not in {"all", "course", "platform"}:
        scope = "all"
    terms = [t for t in query.lower().split() if t]
    notices_key = ("get_lms_notices", _account(), scope)
    notices = await cache.cached(
        notices_key,
        cache.NOTICES_TTL,
        lambda: get_session().run(
            lambda page: learnus.fetch_notices(page, scope=scope)
        ),
    )

    def _matches(item: dict) -> bool:
        if not terms:
            return True
        haystack = " ".join(
            str(item.get(k) or "") for k in ("title", "course", "type")
        ).lower()
        return all(t in haystack for t in terms)

    matched = [n for n in notices if _matches(n)]
    try:
        limit = max(1, int(limit))
    except (TypeError, ValueError):
        limit = 20
    return {
        "query": query,
        "scope": scope,
        "count": len(matched),
        "results": matched[:limit],
    }


@mcp.tool()
async def get_notice(url: str) -> dict:
    """LearnUs 또는 도서관 일반공지의 본문 텍스트를 반환합니다.

    url은 get_lms_notices 또는 get_library_notices가 돌려준 HTTPS 게시글 URL입니다.
    LearnUs는 로그인 필요, 도서관 일반공지는 무로그인 HTTP입니다. 반환값은 제목(title),
    작성일(date), 작성자(author), 본문(body), url 을 포함하며, 요약은 호출하는
    LLM이 수행합니다. 도서관 작성자는 제외하며 image_count와 note를 제공합니다.
    이미지 속 안내는 읽지 못하므로 내용을 추측하지 말고 원문 확인을 안내하세요.
    """
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError("허용된 HTTPS 공지 URL을 사용하세요.")
    if parsed.hostname == "library.yonsei.ac.kr":
        return await cache.cached(
            ("get_notice", "library", url),
            cache.NOTICE_BODY_TTL,
            lambda: library.fetch_library_notice(url),
        )
    if parsed.hostname != "ys.learnus.org" or parsed.path != "/mod/ubboard/article.php":
        raise ValueError("LearnUs 또는 도서관 공지 목록의 URL을 사용하세요.")
    key = ("get_notice", _account(), url)
    return await cache.cached(
        key,
        cache.NOTICE_BODY_TTL,
        lambda: get_session().run(
            lambda page: learnus.fetch_notice_body(page, url)
        ),
    )


@mcp.tool()
async def get_lms_attendance(course_id: str) -> dict:
    """특정 강좌의 주차별 출석/학습 현황 표를 반환합니다.

    course_id 는 get_lms_courses 가 돌려준 강좌 id 입니다. 반환값은
    header(열 제목)와 weeks(주차별 행 딕셔너리 목록)를 포함합니다.
    """
    key = ("get_lms_attendance", _account(), course_id)
    return await cache.cached(
        key,
        cache.ATTENDANCE_TTL,
        lambda: get_session().run(
            lambda page: learnus.fetch_attendance(page, course_id)
        ),
    )

@mcp.tool()
async def get_lms_course_materials(course_id: str) -> dict:
    """특정 강좌의 주차별 학습활동/자료(강의 콘텐츠) 목록을 반환합니다.

    course_id 는 get_lms_courses 가 돌려준 강좌 id 입니다. LearnUs 강좌 페이지의
    '강의 개요'와 주차별 섹션을 읽어, 각 섹션의 활동(동영상/강의자료 파일/과제/
    게시판 등)을 그대로 돌려줍니다. 시험 범위에 맞춰 실제 강의자료를 근거로
    학습 체크리스트를 만드는 등, 모델이 추측하지 않고 실제 콘텐츠에 기반해
    답하도록 돕습니다.

    반환값: course_id, section_count, activity_count, sections. 각 section 은
    id, week(주차 번호, 강의 개요는 null), name, activities 를 가지며 각 activity
    는 type(Moodle 모듈 유형: vod/ubfile/assign/ubboard 등), title, url 을
    포함합니다. sections 는 주차 순으로 정렬되고 강의 개요(week=null)가 맨 앞에
    옵니다.
    """
    key = ("get_lms_course_materials", _account(), course_id)
    return await cache.cached(
        key,
        cache.COURSE_MATERIALS_TTL,
        lambda: get_session().run(
            lambda page: learnus.fetch_course_materials(page, course_id)
        ),
    )

@mcp.tool()
async def get_lms_assignments(course_id: str) -> dict:
    """특정 LearnUs 강좌의 제출 과제 목록을 반환합니다(조회 전용).

    get_lms_courses의 숫자 course_id를 사용합니다. 강의자료 캐시에서 실제
    assign 활동만 추려 course_id, count, assignments를 반환합니다.
    각 과제는 title, url, week, section을 포함합니다. 동영상·퀴즈는 제외하며
    제출 상태나 마감시각은 이 목록에서 확인하지 않습니다. 과제 제출은 하지 않습니다.
    """
    if not course_id.isascii() or not course_id.isdigit():
        raise ValueError("course_id는 get_lms_courses의 숫자 강좌 ID여야 합니다.")
    materials = await get_lms_course_materials(course_id)
    return learnus.assignments_from_materials(materials)


@mcp.tool()
async def get_lms_overview() -> dict:
    """강좌 목록 + 다가오는 마감일 + 최근 강좌 공지를 한 번에 묶어 반환합니다.

    "이번 주 학습 상황 정리해줘" 같은 요청에 적합한 종합 요약 도구입니다.
    """
    key = ("get_lms_overview", _account())

    async def _build(page) -> dict:
        courses = await learnus.fetch_courses(page)
        course_map = {c["id"]: c["name"] for c in courses if c.get("id")}
        deadlines = await learnus.fetch_deadlines(page, course_map=course_map)
        notices = await learnus.fetch_notices(page, scope="course")
        return {
            "courses": courses,
            "upcoming_deadlines": deadlines,
            "recent_course_notices": notices[:10],
        }

    return await cache.cached(
        key,
        cache.OVERVIEW_TTL,
        lambda: get_session().run(_build),
    )


@mcp.tool()
async def get_my_loans() -> dict:
    """연세대학교 도서관에서 현재 대출 중인 도서 목록을 반환합니다.

    로그인(연세포털 ID)이 필요하며, 반환값은 대출 권수(count)와 목록(loans)을
    포함합니다. 각 항목: 서명/저자(title_author), 소장처(location),
    등록번호(reg_no), 대출일(loan_date), 반납예정일(due_date),
    연체료(overdue_fee), 연장횟수(renew_count). 대출 도서가 없으면 count=0.
    """
    key = ("get_my_loans", _account())
    return await cache.cached(
        key,
        cache.MY_LOANS_TTL,
        lambda: get_library_session().run(library.fetch_my_loans),
    )


@mcp.tool()
async def export_calendar_ics(
    include_loans: bool = True, course_id: Optional[str] = None
) -> str:
    """다가오는 과제 마감일(과 도서 반납예정일)을 iCalendar(.ics) 텍스트로 반환합니다.

    반환된 문자열을 ``.ics`` 파일로 저장하면 Google/Apple/Outlook 캘린더에서
    바로 구독·가져오기할 수 있습니다. LearnUs 마감일은 시각 이벤트로,
    도서 반납예정일은 종일 이벤트로 들어갑니다.

    course_id 를 주면 해당 강좌의 마감일만 포함합니다. include_loans=False 면
    도서관 로그인을 건너뛰고 LMS 마감일만 내보냅니다.
    """
    deadlines = await cache.cached(
        ("get_lms_deadlines", _account(), course_id),
        cache.DEADLINES_TTL,
        lambda: get_session().run(
            lambda page: learnus.fetch_deadlines(page, course_id=course_id)
        ),
    )
    loans: list[dict] = []
    if include_loans:
        result = await cache.cached(
            ("get_my_loans", _account()),
            cache.MY_LOANS_TTL,
            lambda: get_library_session().run(library.fetch_my_loans),
        )
        loans = result.get("loans", [])
    return ics.build_ics(deadlines, loans)


@mcp.tool()
async def get_library_seats(seat_type: Optional[str] = None) -> dict:
    """연세대학교 도서관의 실시간 좌석 현황(로그인 불필요)을 반환합니다.

    건물군(중앙도서관/학술정보원) × 좌석유형(일반열람석/PC석/스터디룸/노트북석)
    단위 집계입니다. 각 항목: 건물(building), 좌석유형(seat_type), 총좌석(total),
    사용중(in_use), 남은좌석(remaining), 이용률%(usage_pct). 최상위에 전체 합계와
    이용률도 포함됩니다. seat_type 을 주면 해당 유형만 필터합니다(예: "pc",
    "general", "study", "notebook"). 개별 열람실 단위는 로그인이 필요합니다.
    source_url, fetched_at을 제공하며 60초 캐시입니다. remaining은 공개 집계일 뿐
    배정 가능 좌석이 아닙니다. 별도 열람실 시스템과 범위/갱신 상태가 달라 합치면 안 됩니다.
    """
    key = ("get_library_seats", seat_type)
    return await cache.cached(
        key,
        cache.LIBRARY_SEATS_TTL,
        lambda: seats.fetch_seats(seat_type),
    )


@mcp.tool()
async def search_library_books(query: str, page: int = 1, limit: int = 10) -> dict:
    """연세 도서관 소장자료를 검색합니다(로그인·브라우저 불필요).

    query는 1~200자 검색어, page는 1~100, limit은 1~10입니다.
    query, page, count, results를 반환하며 count는 반환한 현재 페이지 건수입니다.
    각 결과: title, author, publisher, published_year, material_type, url,
    holdings(소장처 location과 표시된 대출 상태 status). 대출·예약은 수행하지
    않습니다. 소장 상태는 5분 캐시이므로 실제 이용 전 원문에서 재확인하세요.
    """
    query = query.strip()
    return await cache.cached(
        ("search_library_books", query, page, limit),
        cache.LIBRARY_SEARCH_TTL,
        lambda: library.fetch_book_search(query, page=page, limit=limit),
    )


@mcp.tool()
async def get_library_notices(limit: int = 10) -> dict:
    """도서관 일반공지 첫 페이지를 반환합니다(로그인·브라우저 불필요).

    limit은 1~20이며 count와 notices를 반환합니다. 각 공지: title, date, url.
    상단 고정 공지를 포함한 원문 순서이며 작성자 정보는 제외합니다.
    휴관·이용시간 변경 등 도서관 운영 공지를 확인할 때 사용하세요.
    """
    return await cache.cached(
        ("get_library_notices", limit),
        cache.LIBRARY_NOTICES_TTL,
        lambda: library.fetch_library_notices(limit=limit),
    )


@mcp.tool()
async def get_library_seat_rooms() -> dict:
    """연세대학교 중앙도서관 **열람실별** 실시간 좌석 현황을 반환합니다(로그인 필요).

    무로그인 집계(`get_library_seats`)보다 세부적으로, 24시 열람실·자료실·
    대학원열람실 등 개별 열람실 단위로 반환합니다. 반환값은 열람실 수(count)와
    목록(rooms), 전체 합계를 포함합니다. 각 열람실: 실명(name), 배정가능
    여부(assignable), 운영좌석(total), 수용좌석(capacity), 사용중(in_use),
    이용가능석(available), 운영시간(hours), 이용률%(usage_pct).
    available은 원문 표시 잔여석이며 배정불가 방을 포함합니다. 실제 배정 가능한
    잔여 합계는 assignable_available입니다. unassignable_rooms, fetched_at,
    source_totals_match를 함께 확인하세요. 60초 캐시이며 실제 착석을 보장하지 않습니다.
    """
    key = ("get_library_seat_rooms", _account())
    return await cache.cached(
        key,
        cache.LIBRARY_SEAT_ROOMS_TTL,
        lambda: get_library_session().run(library.fetch_seat_rooms),
    )


@mcp.tool()
async def get_student_profile(include_pii: bool = False) -> dict:
    """학사행정(ERP)에서 학생 본인의 프로필·학기 정보를 반환합니다(로그인 필요).

    기본 응답은 이름·학번을 제외합니다. 사용자가 명시적으로 요청한 경우에만
    include_pii=True로 이름(name)·학번(student_no)을 포함하세요.
    반환값: 학과(department)·전체학과명
    (department_full)·학과코드(department_code), 현재학기(current_term)와
    현재학기 신청학점(current_term_credits), 그리고 등록된 전체 학기 목록
    (terms: 각 학기명/연도/코드/학점). 대학원 신입생 등 이력이 적은 계정은
    학기 목록이 짧을 수 있습니다.
    """
    key = ("get_student_profile", _account())
    result = await cache.cached(
        key,
        cache.ERP_PROFILE_TTL,
        lambda: get_erp_session().run(erp.fetch_student_profile),
    )
    visible = {key: value for key, value in result.items() if include_pii or key not in {"name", "student_no"}}
    visible["pii_included"] = include_pii
    return visible


@mcp.tool()
async def get_my_timetable() -> dict:
    """학사행정(ERP) 수강신청내역 기반의 본인 시간표를 반환합니다(로그인 필요).

    반환값: 학기(term), 과목 수(count), 총 학점(total_credits), 과목 목록
    (courses). 각 과목: 과목코드(course_code), 분반(section), 과목명
    (course_name)·영문명(course_name_en), 담당교수(professor), 학점(credits),
    이수구분(category), 강의실(room), 강의시간 원문(time_raw)과 파싱된 교시
    슬롯(slots: 요일 day/day_en + 교시 period). 요일은 월~일을 Mon~Sun으로
    매핑합니다. 범위·격주 등 미지원 표현은 원문을 보존하고 slots=[]로 반환하므로
    수업 없음으로 해석하지 마세요. 학점 값 누락이나 손상은 0으로 합산하지 않습니다.
    """
    key = ("get_my_timetable", _account())
    return await cache.cached(
        key,
        cache.ERP_TIMETABLE_TTL,
        lambda: get_erp_session().run(erp.fetch_timetable),
    )


@mcp.tool()
async def get_grades(year: Optional[int] = None, term_code: Optional[str] = None) -> dict:
    """학사행정(ERP)에서 본인의 전체 성적 이력을 반환합니다(로그인 필요).

    반환값: 과목 수(count), 과목별 성적 목록(courses: 학기/과목코드/과목명/
    학점/성적/이수구분/교수), 학기 목록(terms), 요약(summary: 취득학점/평점).
    첫 학기 성적 확정 전이거나 성적 이력이 없는 신입생 계정은 courses 가 비어
    있고 note 안내가 포함됩니다(정상 동작).
    year와 term_code(10/11/20/21)로 과목·학기 목록을 필터합니다.
    summary는 항상 전체 학기 누적이며 필터된 학기의 GPA가 아닙니다.
    """
    if year is not None and not 1900 <= year <= datetime.now(ics.KST).year:
        raise ValueError("year는 1900년부터 현재 연도까지입니다.")
    if term_code is not None and term_code not in {"10", "11", "20", "21"}:
        raise ValueError("term_code는 10/11/20/21입니다.")
    key = ("get_grades", _account(), year, term_code)
    return await cache.cached(
        key,
        cache.ERP_GRADES_TTL,
        lambda: get_erp_session().run(lambda page: erp.fetch_grades(page, year, term_code)),
    )


@mcp.tool()
async def get_my_reservations() -> dict:
    """도서관 본인의 도서 예약 내역을 조회합니다. 예약 생성·취소는 하지 않습니다.

    count, reservations를 반환합니다. 각 항목: title_author, location,
    queue_position(원문 예약순위), reservation_date, notification_date, status.
    좌석/스터디룸 예약은 포함하지 않습니다. 개인정보이며 5분 캐시를 사용합니다.
    """
    return await cache.cached(
        ("get_my_reservations", _account()), cache.MY_LOANS_TTL,
        lambda: get_library_session().run(library.fetch_my_reservations),
    )


@mcp.tool()
async def get_scholarship_history() -> dict:
    """ERP 본인의 장학수혜내역을 읽습니다. 신청 가능한 장학금 공고가 아닙니다.

    count와 scholarships를 반환합니다. 각 항목: year, term_code, name,
    amount(원문 금액), payment_date_raw(원문 지급일). 학번·내부 식별자는 제외합니다.
    현재 표의 조회 결과이며 5분 캐시를 사용합니다. 신청·증명서 발급은 하지 않습니다.
    """
    return await cache.cached(
        ("get_scholarship_history", _account()), cache.NOTICES_TTL,
        lambda: get_erp_session().run(erp.fetch_scholarship_history),
    )


@mcp.tool()
async def get_exam_schedule(exam_type: str = "default") -> dict:
    """ERP 현재 학기 시험시간표를 시험구분별로 조회합니다(신청 없음).

    term, exam_type, period_configured, note, count, exams를 반환합니다.
    exam_type은 default(화면 기본)/midterm(중간)/final(기말)입니다.
    선택된 시험구분을 반환합니다. period_configured=false이면 조회기간 미등록 상태이며
    '시험 없음'으로 해석하면 안 됩니다. 각 시험은 과목·분반·날짜·교시·강의실·
    교수 원문을 포함합니다. 5분 캐시입니다.
    """
    if exam_type not in {"default", "midterm", "final"}:
        raise ValueError("exam_type은 default/midterm/final입니다.")
    return await cache.cached(
        ("get_exam_schedule", _account(), exam_type), cache.DEADLINES_TTL,
        lambda: get_erp_session().run(lambda page: erp.fetch_exam_schedule(page, exam_type)),
    )


@mcp.tool()
async def search_courses(keyword: str, limit: int = 20, year: Optional[int] = None, term_code: Optional[str] = None, campus_code: Optional[str] = None) -> dict:
    """ERP 수강편람에서 교과목명으로 검색합니다. 수강신청은 수행하지 않습니다.

    keyword는 2~100자, limit은 1~50입니다. year, term_code(10/11/20/21),
    campus_code로 선택합니다. campus_code는 s1/s3/s7(신촌 학부/대학원/의료원),
    s2/s4/s8(미래 학부/대학원/의료원)입니다. 생략한 조건은 화면 기본값을 사용하고
    실제 적용된 값을 filters로 반환합니다. courses의 각 항목은 과목코드·과목명·분반·교수·학점·
    강의시간·강의실·학과·이수구분입니다. count는 반환 건수, fetched_count는
    학교 응답 건수이며 학교는 최대 200건으로 제한합니다. matching_count는 응답 안에서
    요청 필터에 일치한 건수입니다. truncated=true이면 0건이라도 해당 조건에
    과목이 없다고 단정할 수 없습니다. 키워드를 좁히세요. 정원·수강인원·강의계획서는 제외합니다.
    """
    keyword = keyword.strip()
    if not 2 <= len(keyword) <= 100 or not 1 <= limit <= 50:
        raise ValueError("keyword는 2~100자, limit은 1~50이어야 합니다.")
    erp.validate_catalog_filters(year, term_code, campus_code)
    options = {key: value for key, value in {"year": year, "term_code": term_code, "campus_code": campus_code}.items() if value is not None}
    return await cache.cached(
        ("search_courses", _account(), keyword, limit, year, term_code, campus_code), cache.COURSES_TTL,
        lambda: get_erp_session().run(lambda page: erp.fetch_course_catalog(page, keyword, limit, **options)),
    )


@mcp.tool()
async def get_lms_course_history(year: Optional[int] = None, semester: str = "all") -> dict:
    """LearnUs 본인 과거강좌조회 표를 연도·학기로 조회합니다.

    year 생략 시 전체 연도, semester는 all/10(1학기)/11(여름)/20(2학기)/21(겨울).
    count, courses, year, semester, has_pagination을 반환합니다. 각 강좌는
    id, name, year, semester, url을 포함합니다. 현재 필터의 표시 페이지이며
    선택한 연도/학기의 표시 결과이며 페이지 번호를 받지 않습니다. 원문 선택 조건과
    행의 연도/학기를 검증합니다. scope=displayed_result, filters_verified=true이며
    전체 학적 이력의 완전성을 보장하지 않습니다. 출처·수집시각과 30분 캐시를 제공합니다.
    """
    if year is not None and (type(year) is not int or not 2003 <= year <= datetime.now(ics.KST).year):
        raise ValueError("year는 2003년부터 현재 연도까지입니다.")
    if semester not in {"all", "10", "11", "20", "21"}:
        raise ValueError("semester는 all/10/11/20/21입니다.")
    return await cache.cached(
        ("get_lms_course_history", _account(), year, semester), cache.COURSES_TTL,
        lambda: get_session().run(lambda browser_page: learnus.fetch_course_history(browser_page, year, semester)),
    )


@mcp.tool()
async def get_lms_assignment_status(assignment_id: str) -> dict:
    """LearnUs 과제 한 건의 본인 제출상태·채점상태·마감을 조회합니다(제출 없음).

    assignment_id는 get_lms_assignments가 반환한 /mod/assign/view.php?id=...의
    숫자 id입니다(강좌 ID 아님). submission_status는 submitted/not_submitted/
    draft/unknown이며 원문도 함께 반환합니다. 채점됨과 제출됨은 별개입니다.
    due는 확인 가능한 KST 시각, due_raw는 원문입니다. overdue_marker는 화면의
    마감경과 표시일 뿐 지각 제출 판정이 아닙니다. 제출물 내용은 읽지 않습니다.
    fetched_at과 url을 제공하며 5분 캐시입니다.
    """
    if not re.fullmatch(r"[0-9]{1,20}", assignment_id):
        raise ValueError("assignment_id는 과제 URL의 숫자 id여야 합니다.")
    return await cache.cached(
        ("get_lms_assignment_status", _account(), assignment_id), cache.DEADLINES_TTL,
        lambda: get_session().run(lambda page: learnus.fetch_assignment_status(page, assignment_id)),
    )


@mcp.tool()
async def get_my_schedule(days: int = 7, include_loans: bool = True, include_exams: bool = False) -> dict:
    """오늘(KST)부터 days일 동안의 LMS 마감·도서 반납일과 주간 시간표를 묶습니다.

    days는 1~90. events는 날짜 범위 내 마감/반납일이며 kind의 progress/completion을
    제출 과제로 부르지 마세요. 날짜를 못 읽은 항목은 undated_items에 보존합니다.
    weekly_timetable은 현재 학기의 주간 패턴일 뿐 그 기간에 실제 수업이 열린다는
    보장이 아닙니다(휴강·학기 기간 미반영). include_exams=True면 중간/기말 조회를
    함께 반환하며 exams는 days로 필터하지 않은 원문 조회 범위입니다.
    개별 도구 캐시를 재사용합니다. generated_at은 묶음 생성시각이지 원천 갱신시각이 아닙니다.
    """
    if not 1 <= days <= 90:
        raise ValueError("days는 1~90이어야 합니다.")
    deadlines = await get_lms_deadlines()
    loans = (await get_my_loans())["loans"] if include_loans else []
    result = ics.build_agenda(deadlines, loans, days=days)
    result["weekly_timetable"] = await get_my_timetable()
    result["exams"] = {
        "midterm": await get_exam_schedule("midterm"),
        "final": await get_exam_schedule("final"),
    } if include_exams else None
    result["generated_at"] = datetime.now(ics.KST).isoformat()
    result["coverage_note"] = "개별 조회 캐시를 재사용합니다. 시간표는 주간 패턴이며 실제 수업 날짜/교시 시각은 추정하지 않습니다. exams는 기간 필터 미적용입니다."
    return result


@mcp.tool()
async def get_academic_calendar() -> dict:
    """연세 공식 홈페이지(신촌·국제)의 현재 표시 학기 학사일정을 조회합니다(무로그인).

    academic_year, semester(first/second), months, count, source_url, fetched_at 반환.
    각 월은 display_year, month, events[{date_raw,title}]입니다. date_raw는 원문이며
    월을 넘는 기간은 인접 월에 중복 표시될 수 있습니다. display_year/month를
    모든 이벤트의 시작 연월로 해석하지 마세요. 개인 시험/학과 일정을 대체하지 않습니다.
    공개 HTTP 조회이며 30분 캐시입니다.
    """
    return await cache.cached(("get_academic_calendar",), cache.COURSES_TTL, academic.fetch_calendar)


@mcp.tool()
async def export_timetable_ics(
    start_date: str, end_date: str, period_times: dict[str, dict[str, str]],
    exclude_dates: Optional[list[str]] = None,
) -> str:
    """본인 ERP 시간표를 사용자 확인 기간/교시 시각으로 반복 iCalendar 텍스트로 만듭니다.

    start_date/end_date: YYYY-MM-DD (양끝 포함, 최대 366일). period_times는 모든
    교시별 {"2":{"start":"10:00","end":"10:50"}} 형태의 KST 시각입니다.
    위 시간은 형식 예시일 뿐 학교 전체에 보장된 시각이 아닙니다. 반드시 사용자가
    확인한 기간/시각을 받아 호출하세요. 모르면 질문하고 임의 값을 넣지 마세요.
    exclude_dates는 휴강/휴일 YYYY-MM-DD 목록입니다. 공휴일을 자동 제외하지 않습니다.
    교시마다 주간 반복 이벤트를 생성하며 해석 불가능/누락 시간표는 부분 내보내기 대신
    오류를 반환합니다. 학사일정은 get_academic_calendar, 시간표는 get_my_timetable로 확인하세요.
    """
    timetable = await get_my_timetable()
    return ics.build_timetable_ics(timetable, start_date, end_date, period_times, exclude_dates=exclude_dates)


@mcp.tool()
async def get_lms_gradebook(course_id: str, include_feedback: bool = False) -> dict:
    """LearnUs 강좌의 본인 성적부를 조회합니다. ERP 확정 성적/GPA와는 별개입니다.

    course_id는 get_lms_courses/get_lms_course_history의 숫자 강좌 ID입니다.
    items는 kind(category=분류/item=항목/total=소계·총계), name, grade_raw,
    grade_available과 화면에 있는 weight_raw/range_raw/percentage_raw/contribution_raw를
    포함합니다. '-'·숨김·빈 값은 0점이 아닙니다. total을 다른 항목과 중복 합산하지 마세요.
    피드백은 기본 제외하며 사용자가 요청한 경우만 include_feedback=True로 포함하세요.
    계정/강좌/옵션별 5분 캐시이며 source_url, fetched_at을 반환합니다.
    """
    if not re.fullmatch(r"[0-9]{1,20}", course_id):
        raise ValueError("course_id는 본인 강좌 목록의 숫자 ID여야 합니다.")
    return await cache.cached(
        ("get_lms_gradebook", _account(), course_id, include_feedback), cache.ATTENDANCE_TTL,
        lambda: get_session().run(lambda page: learnus.fetch_gradebook(page, course_id, include_feedback)),
    )


@mcp.tool()
async def get_library_book_detail(catalog_id: str) -> dict:
    """도서관 소장자료의 복본별 상세 상태를 조회합니다(로그인·브라우저 불필요).

    catalog_id는 search_library_books가 반환한 URL의 /search/detail/CATTOT숫자 부분입니다.
    count와 copies(reg_no, call_number, location, status_raw, due_date_raw)를 반환합니다.
    현재는 CATTOT 소장자료만 지원합니다. 반납예정일 빈 값이나 상태 문구만으로
    예약 가능 여부를 추정하지 마세요. 예약 버튼·차용자 정보는 읽지 않습니다.
    5분 캐시이며 source_url/fetched_at 포함. 실제 이용 전 원문에서 재확인하세요.
    """
    if not re.fullmatch(r"CATTOT[0-9]{1,20}", catalog_id):
        raise ValueError("catalog_id는 검색 결과의 CATTOT와 숫자로 된 식별자여야 합니다.")
    return await cache.cached(
        ("get_library_book_detail", catalog_id), cache.LIBRARY_SEARCH_TTL,
        lambda: library.fetch_book_detail(catalog_id),
    )


@mcp.tool()
async def get_my_loan_history() -> dict:
    """도서관 본인의 이전 대출기록 표시 페이지를 조회합니다(현재 대출은 get_my_loans).

    loans: title_author, location, reg_no, loan_date, return_date(실제 반납일),
    return_type. count는 반환 건수이며 전체 이력 건수가 아닙니다. date_filters_raw로
    화면 조회기간을 확인하세요. scope=displayed_page, has_pagination 포함.
    날짜 필터와 후속 페이지는 실데이터 검증이 완료되지 않아 입력으로 지원하지 않습니다.
    기본 화면의 표시 결과만 반환합니다. date_filters_raw의 빈 값은 전체 기간을 뜻하지 않습니다.
    count는 표시 페이지 건수이며 total/has_next/next_page는 확인 가능한 경우만 제공합니다.
    5분 계정 캐시이며 source_url/fetched_at을 제공합니다. 연장은 하지 않습니다.
    """
    return await cache.cached(
        ("get_my_loan_history", _account()), cache.MY_LOANS_TTL,
        lambda: get_library_session().run(library.fetch_loan_history),
    )


@mcp.tool()
async def get_my_reservation_history() -> dict:
    """도서관 본인의 이전 도서 예약기록 표시 페이지를 조회합니다(예약 생성/취소 없음).

    현재 예약은 get_my_reservations를 사용하세요. reservations는 title_author,
    location, queue_position, reservation_date, notification_date, status입니다.
    순위와 상태는 과거 기록이며 현재 예약 상태로 안내하지 마세요. count는 반환 건수,
    scope=displayed_page, has_pagination 포함. 캠퍼스간 신청·좌석/시설 예약은 제외합니다.
    후속 페이지는 실데이터 검증이 완료되지 않아 입력으로 지원하지 않습니다.
    total/has_next/next_page는 확인 가능한 경우만 반환하며 전체 수집 완료를 뜻하지 않습니다.
    날짜 필터는 지원하지 않습니다. 5분 계정 캐시, source_url/fetched_at 포함.
    """
    return await cache.cached(
        ("get_my_reservation_history", _account()), cache.MY_LOANS_TTL,
        lambda: get_library_session().run(library.fetch_reservation_history),
    )


@mcp.tool()
async def get_lms_boards(course_id: str) -> dict:
    """LearnUs 강좌 게시판 목록을 읽습니다. 글 작성·수정·삭제는 하지 않습니다.

    course_id는 현재/과거 강좌 목록의 숫자 ID입니다. count, boards를 반환하며
    각 게시판은 board_id, name, post_count(원문 표시), updated_raw, url을 포함합니다.
    공통 메뉴가 아니라 강좌 게시판 표만 수집합니다. 5분 계정·강좌별 캐시입니다.
    """
    boards.validate_id(course_id)
    return await cache.cached(
        ("get_lms_boards", _account(), course_id), cache.NOTICES_TTL,
        lambda: get_session().run(lambda page: boards.fetch_boards(page, course_id)),
    )


@mcp.tool()
async def get_lms_board_posts(board_id: str) -> dict:
    """get_lms_boards가 반환한 board_id로 강좌 게시글 목록 첫 페이지를 읽습니다.

    posts는 post_id, title, date_raw, url입니다. 작성자·본문·링크 없는 글의 제목은
    수집하지 않으며 unlinked_count로 제외 수만 제공합니다. count는 공개 링크가 있는
    반환 건수이고 전체 글 수가 아닙니다. has_pagination이면 후속 페이지는 미수집입니다.
    글 작성·수정·삭제는 하지 않습니다. 출처·수집시각과 5분 계정 캐시를 제공합니다.
    """
    boards.validate_id(board_id)
    return await cache.cached(
        ("get_lms_board_posts", _account(), board_id), cache.NOTICES_TTL,
        lambda: get_session().run(lambda page: boards.fetch_posts(page, board_id)),
    )
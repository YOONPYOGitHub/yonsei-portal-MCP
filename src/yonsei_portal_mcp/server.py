"""Yonsei Portal MCP server.

Exposes the student's LearnUs (LMS) data as MCP tools over stdio so an LLM
client (Claude Desktop, VS Code Copilot, MCP Inspector, ...) can answer
questions like "이번 주 과제 마감일 알려줘" or "내 강의 출석 현황 정리해줘".

Authentication uses the credentials in ``.env`` and is handled transparently by
:mod:`yonsei_portal_mcp.session`.
"""
from __future__ import annotations

from typing import Optional

from mcp.server.fastmcp import FastMCP

from . import cache, ics
from .config import load_settings
from .scrapers import erp, learnus, library, seats
from .session import get_erp_session, get_library_session, get_session

mcp = FastMCP("yonsei-portal")


def _account() -> str:
    """Cache-key component so different logins never share cached data."""
    return load_settings().yonsei_id or "anon"


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
    """단일 LearnUs 공지/게시글의 본문 전체를 반환합니다.

    url 은 get_lms_notices 가 돌려준 게시글 URL 입니다. 반환값은 제목(title),
    작성일(date), 작성자(author), 본문(body), url 을 포함하며, 요약은 호출하는
    LLM 이 수행합니다(서버는 원문만 제공).
    """
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
    """
    key = ("get_library_seats", seat_type)
    return await cache.cached(
        key,
        cache.LIBRARY_SEATS_TTL,
        lambda: seats.fetch_seats(seat_type),
    )


@mcp.tool()
async def get_library_seat_rooms() -> dict:
    """연세대학교 중앙도서관 **열람실별** 실시간 좌석 현황을 반환합니다(로그인 필요).

    무로그인 집계(`get_library_seats`)보다 세부적으로, 24시 열람실·자료실·
    대학원열람실 등 개별 열람실 단위로 반환합니다. 반환값은 열람실 수(count)와
    목록(rooms), 전체 합계를 포함합니다. 각 열람실: 실명(name), 배정가능
    여부(assignable), 운영좌석(total), 수용좌석(capacity), 사용중(in_use),
    이용가능석(available), 운영시간(hours), 이용률%(usage_pct).
    """
    key = ("get_library_seat_rooms", _account())
    return await cache.cached(
        key,
        cache.LIBRARY_SEAT_ROOMS_TTL,
        lambda: get_library_session().run(library.fetch_seat_rooms),
    )


@mcp.tool()
async def get_student_profile() -> dict:
    """학사행정(ERP)에서 학생 본인의 프로필·학기 정보를 반환합니다(로그인 필요).

    반환값: 이름(name), 학번(student_no), 학과(department)·전체학과명
    (department_full)·학과코드(department_code), 현재학기(current_term)와
    현재학기 신청학점(current_term_credits), 그리고 등록된 전체 학기 목록
    (terms: 각 학기명/연도/코드/학점). 대학원 신입생 등 이력이 적은 계정은
    학기 목록이 짧을 수 있습니다.
    """
    key = ("get_student_profile", _account())
    return await cache.cached(
        key,
        cache.ERP_PROFILE_TTL,
        lambda: get_erp_session().run(erp.fetch_student_profile),
    )


@mcp.tool()
async def get_my_timetable() -> dict:
    """학사행정(ERP) 수강신청내역 기반의 본인 시간표를 반환합니다(로그인 필요).

    반환값: 학기(term), 과목 수(count), 총 학점(total_credits), 과목 목록
    (courses). 각 과목: 과목코드(course_code), 분반(section), 과목명
    (course_name)·영문명(course_name_en), 담당교수(professor), 학점(credits),
    이수구분(category), 강의실(room), 강의시간 원문(time_raw)과 파싱된 교시
    슬롯(slots: 요일 day/day_en + 교시 period). 요일은 월~일을 Mon~Sun으로
    매핑합니다.
    """
    key = ("get_my_timetable", _account())
    return await cache.cached(
        key,
        cache.ERP_TIMETABLE_TTL,
        lambda: get_erp_session().run(erp.fetch_timetable),
    )


@mcp.tool()
async def get_grades() -> dict:
    """학사행정(ERP)에서 본인의 전체 성적 이력을 반환합니다(로그인 필요).

    반환값: 과목 수(count), 과목별 성적 목록(courses: 학기/과목코드/과목명/
    학점/성적/이수구분/교수), 학기 목록(terms), 요약(summary: 취득학점/평점).
    첫 학기 성적 확정 전이거나 성적 이력이 없는 신입생 계정은 courses 가 비어
    있고 note 안내가 포함됩니다(정상 동작).
    """
    key = ("get_grades", _account())
    return await cache.cached(
        key,
        cache.ERP_GRADES_TTL,
        lambda: get_erp_session().run(erp.fetch_grades),
    )
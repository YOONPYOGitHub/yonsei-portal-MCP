"""Canned Korean tool outputs mirroring the 14 production tool shapes.

These fixtures stand in for the live scrapers so the L1/L2 LLM tests never log
in to the real portal and never send real student PII to an external model.
The data is fictional but structurally identical to what the scrapers return
(see ``src/yonsei_portal_mcp/server.py``).
"""
from __future__ import annotations

# --- LearnUs ---------------------------------------------------------------

COURSES = [
    {
        "id": "101",
        "name": "운영체제",
        "code": "CSI3108",
        "professor": "김교수",
        "category": "전공",
        "progress_percent": 62,
        "url": "https://learnus.example/course/view.php?id=101",
        "attendance_url": "https://learnus.example/course/attendance.php?id=101",
    },
    {
        "id": "202",
        "name": "데이터베이스",
        "code": "CSI3110",
        "professor": "이교수",
        "category": "전공",
        "progress_percent": 45,
        "url": "https://learnus.example/course/view.php?id=202",
        "attendance_url": "https://learnus.example/course/attendance.php?id=202",
    },
]

DEADLINES = [
    {
        "title": "운영체제 과제 3",
        "due": "2026-05-20T23:59:00+09:00",
        "due_text": "2026-05-20 23:59",
        "course_id": "101",
        "course": "운영체제",
        "source": "assignment",
        "url": "https://learnus.example/mod/assign/view.php?id=5551",
    },
    {
        "title": "데이터베이스 퀴즈 2",
        "due": "2026-05-23T18:00:00+09:00",
        "due_text": "2026-05-23 18:00",
        "course_id": "202",
        "course": "데이터베이스",
        "source": "quiz",
        "url": "https://learnus.example/mod/quiz/view.php?id=7782",
    },
]

_NOTICES = [
    {
        "type": "course",
        "course": "운영체제",
        "date": "2026-05-10",
        "title": "[운영체제] 중간고사 성적 공지",
        "url": "https://learnus.example/mod/forum/discuss.php?d=3001",
    },
    {
        "type": "platform",
        "course": None,
        "date": "2026-05-09",
        "title": "[LearnUs] 시스템 점검 안내 (5/12 02:00~04:00)",
        "url": "https://learnus.example/news/3002",
    },
]

NOTICE_BODY = {
    "title": "[운영체제] 중간고사 성적 공지",
    "date": "2026-05-10",
    "author": "김교수",
    "body": "중간고사 성적을 공지합니다. 이의 신청은 5/15까지 이메일로 받습니다.",
    "url": "https://learnus.example/mod/forum/discuss.php?d=3001",
}

ATTENDANCE = {
    "header": ["주차", "출석", "지각", "결석"],
    "weeks": [
        {"week": 1, "status": "출석"},
        {"week": 2, "status": "출석"},
        {"week": 3, "status": "지각"},
    ],
}


def notices(scope: str = "all") -> list[dict]:
    if scope == "course":
        return [n for n in _NOTICES if n["type"] == "course"]
    if scope == "platform":
        return [n for n in _NOTICES if n["type"] == "platform"]
    return list(_NOTICES)


# --- Library ---------------------------------------------------------------

LOANS = {
    "count": 2,
    "loans": [
        {
            "title_author": "운영체제 / Silberschatz",
            "location": "중앙도서관 3층",
            "reg_no": "CLD000111",
            "loan_date": "2026-05-01",
            "due_date": "2026-05-22",
            "overdue_fee": "0",
            "renew_count": 1,
        },
        {
            "title_author": "데이터베이스 시스템 / Elmasri",
            "location": "학술정보원 2층",
            "reg_no": "CLD000222",
            "loan_date": "2026-05-03",
            "due_date": "2026-05-24",
            "overdue_fee": "0",
            "renew_count": 0,
        },
    ],
}

SEAT_ROOMS = {
    "count": 2,
    "rooms": [
        {"name": "제1열람실", "total": 200, "in_use": 150, "remaining": 50},
        {"name": "제2열람실", "total": 180, "in_use": 90, "remaining": 90},
    ],
    "totals": {"total": 380, "in_use": 240, "remaining": 140},
}

_SEATS = {
    "building": "중앙도서관",
    "seat_type": "전체",
    "total": 380,
    "in_use": 240,
    "remaining": 140,
    "usage_pct": 63,
    "totals": {"total": 380, "in_use": 240, "remaining": 140},
}


def seats(seat_type: str | None = None) -> dict:
    data = dict(_SEATS)
    if seat_type:
        data["seat_type"] = seat_type
    return data


# --- ERP -------------------------------------------------------------------

PROFILE = {
    "name": "홍길동",
    "student_no": "2020123456",
    "department": "컴퓨터과학과",
    "department_full": "공과대학 컴퓨터과학과",
    "department_code": "CSI",
    "current_term": "2026-1",
    "current_term_credits": 18,
    "terms": ["2025-1", "2025-2", "2026-1"],
}

TIMETABLE = {
    "term": "2026-1",
    "count": 2,
    "total_credits": 6,
    "courses": [
        {
            "course_code": "CSI3108",
            "section": "01",
            "course_name": "운영체제",
            "course_name_en": "Operating Systems",
            "professor": "김교수",
            "credits": 3,
            "category": "전공",
            "room": "공학원 B101",
            "time_raw": "월3 수4",
            "slots": [
                {"day": "월", "day_en": "Mon", "period": 3},
                {"day": "수", "day_en": "Wed", "period": 4},
            ],
        },
        {
            "course_code": "CSI3110",
            "section": "02",
            "course_name": "데이터베이스",
            "course_name_en": "Databases",
            "professor": "이교수",
            "credits": 3,
            "category": "전공",
            "room": "공학원 C203",
            "time_raw": "화5 목6",
            "slots": [
                {"day": "화", "day_en": "Tue", "period": 5},
                {"day": "목", "day_en": "Thu", "period": 6},
            ],
        },
    ],
}

GRADES = {
    "count": 2,
    "courses": [
        {"term": "2025-2", "course_name": "자료구조", "credits": 3, "grade": "A+"},
        {"term": "2025-2", "course_name": "이산수학", "credits": 3, "grade": "A0"},
    ],
    "terms": ["2025-2"],
    "summary": {"취득학점": 6, "평점": 4.25},
}

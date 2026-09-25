"""Unit tests for the pure ICS generator (no browser / no network).

Run: ``uv run python tests/test_ics.py``
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from yonsei_portal_mcp import ics  # noqa: E402


def test_agenda_uses_kst_window_and_preserves_activity_kind() -> None:
    from datetime import datetime, timezone

    result = ics.build_agenda([
        {"title": "Lecture", "due": "2026-09-21T15:00:00Z", "kind": "progress", "course": "Test", "url": "https://example.test/1"},
        {"title": "Outside", "due": "2026-09-23T00:00:00+09:00", "kind": "assignment"},
        {"title": "Unknown", "due": None, "kind": "assignment"},
    ], [{"title_author": "Book", "due_date": "2026.09.22", "reg_no": "private-id"}],
        days=1, now=datetime(2026, 9, 21, 16, tzinfo=timezone.utc))
    assert result["window"]["start"] == "2026-09-22"
    assert result["window"]["end_exclusive"] == "2026-09-23"
    assert result["count"] == 2
    assert {event["kind"] for event in result["events"]} == {"progress", "loan_return"}
    assert len(result["undated_items"]) == 1
    assert "private-id" not in str(result)


def test_agenda_keeps_unparseable_dates_visible() -> None:
    from datetime import datetime, timezone

    result = ics.build_agenda(
        [{"title": "Unknown", "due": "tomorrow"}],
        [{"title_author": "Book", "due_date": "unknown"}],
        now=datetime(2026, 9, 22, tzinfo=timezone.utc),
    )
    assert result["count"] == 0
    assert len(result["undated_items"]) == 2


def test_agenda_rejects_unbounded_window() -> None:
    import pytest

    for days in (0, 91):
        with pytest.raises(ValueError):
            ics.build_agenda([], [], days=days)


def test_timetable_ics_uses_explicit_times_and_weekly_bounds() -> None:
    import re

    timetable = {"term": "2026-2", "courses": [{
        "course_code": "TEST101", "section": "01", "course_name": "Test; course",
        "room": "Room A", "time_raw": "월2,3", "slots": [
            {"day_en": "Mon", "period": 2}, {"day_en": "Mon", "period": 3},
        ],
    }]}
    result = ics.build_timetable_ics(timetable, "2026-09-01", "2026-12-21", {
        "2": {"start": "10:00", "end": "10:50"}, "3": {"start": "11:00", "end": "11:50"},
    }, exclude_dates=["2026-09-28"])
    assert result.count("BEGIN:VEVENT") == 2
    assert "DTSTART:20260907T010000Z" in result
    assert "DTEND:20260907T015000Z" in result
    assert "RRULE:FREQ=WEEKLY;UNTIL=20261221T145959Z" in result
    assert "EXDATE:20260928T010000Z" in result
    assert "SUMMARY:Test\\; course" in result
    assert "LOCATION:Room A" in result
    assert len(set(re.findall(r"UID:(.+)", result))) == 2


def test_timetable_ics_does_not_guess_periods_or_dates() -> None:
    import pytest

    timetable = {"courses": [{"course_code": "TEST", "section": "1", "course_name": "Course", "time_raw": "화2", "slots": [{"day_en": "Tue", "period": 2}]}]}
    for start, end, times in [
        ("2026-10-01", "2026-09-01", {"2": {"start": "10:00", "end": "10:50"}}),
        ("2026-09-01", "2026-12-21", {}),
        ("2026-09-01", "2026-12-21", {"2": {"start": "11:00", "end": "10:00"}}),
        ("2026-09-01", "2026-12-21", {"2": {"start": "25:00", "end": "26:00"}}),
    ]:
        with pytest.raises(ValueError):
            ics.build_timetable_ics(timetable, start, end, times)


def test_timetable_ics_rejects_unparsed_and_empty_schedules() -> None:
    import pytest

    for raw, slots in [("미정", []), ("월2-4", [{"day_en": "Mon", "period": 2}, {"day_en": "Mon", "period": 4}])]:
        with pytest.raises(ValueError):
            ics.build_timetable_ics({"courses": [{"course_code": "TEST", "section": "1", "course_name": "Course", "time_raw": raw, "slots": slots}]}, "2026-09-01", "2026-12-21", {"2": {"start": "10:00", "end": "10:50"}, "4": {"start": "12:00", "end": "12:50"}})


@pytest.mark.parametrize(("raw", "periods"), [
    ("월2-4", [2, 4]), ("월2(격주1회)", [2, 1]),
    ("월2 3", [23]), ("월2,", [2]), ("월02", [2]),
])
def test_timetable_ics_rejects_unsupported_complete_grammar(raw, periods) -> None:
    timetable = {"courses": [{
        "course_code": "TEST", "section": "01", "course_name": "Course",
        "time_raw": raw,
        "slots": [{"day_en": "Mon", "period": period} for period in periods],
    }]}
    times = {str(period): {"start": "10:00", "end": "10:50"} for period in periods}
    with pytest.raises(ValueError):
        ics.build_timetable_ics(timetable, "2026-09-01", "2026-09-30", times)


@pytest.mark.parametrize("raw", ["화2", "화2,3", "월2화3", "월2,화3", " 월 2, 3 화 4 ", "일99"])
def test_timetable_ics_accepts_supported_erp_time_formats(raw) -> None:
    from yonsei_portal_mcp.scrapers import erp

    slots = erp._parse_time(raw)
    timetable = {"courses": [{
        "course_code": "TEST", "section": "01", "course_name": "Course",
        "time_raw": raw, "slots": slots,
    }]}
    times = {str(slot["period"]): {"start": "10:00", "end": "10:50"} for slot in slots}
    result = ics.build_timetable_ics(timetable, "2026-09-01", "2026-09-30", times)
    assert len(_events(result)) == len(slots)


def _events(text: str) -> list[str]:
    return [b for b in text.split("BEGIN:VEVENT") if "END:VEVENT" in b]


def test_basic_structure() -> None:
    deadlines = [
        {
            "title": "과제 1 제출",
            "due": "2026-06-15T23:59:00+09:00",
            "due_text": "6월 15일 23:59",
            "course_id": "12345",
            "course": "자료구조",
            "url": "https://ys.learnus.org/mod/assign/view.php?id=1",
            "source": "calendar",
        },
        {  # no due -> must be skipped
            "title": "마감 미정",
            "due": None,
            "course": "알고리즘",
            "url": "https://ys.learnus.org/x",
        },
    ]
    loans = [
        {
            "title_author": "클린 코드 / 로버트 마틴",
            "location": "중앙도서관",
            "reg_no": "EM123456",
            "due_date": "2026.06.20",
        },
    ]
    out = ics.build_ics(deadlines, loans)

    # CRLF line endings (RFC 5545 §3.1).
    assert "\r\n" in out, "must use CRLF"
    assert out.startswith("BEGIN:VCALENDAR\r\n")
    assert out.rstrip().endswith("END:VCALENDAR")
    assert "VERSION:2.0" in out
    assert "PRODID:" in out

    evs = _events(out)
    assert len(evs) == 2, f"expected 2 events (1 deadline + 1 loan), got {len(evs)}"

    # Deadline event: UTC timestamp (23:59 KST -> 14:59 UTC).
    assert "DTSTART:20260615T145900Z" in out
    assert "SUMMARY:[자료구조] 과제 1 제출" in out
    assert "URL:https://ys.learnus.org/mod/assign/view.php?id=1" in out

    # Loan event: all-day, exclusive DTEND (+1 day).
    assert "DTSTART;VALUE=DATE:20260620" in out
    assert "DTEND;VALUE=DATE:20260621" in out
    assert "SUMMARY:[도서 반납] 클린 코드 / 로버트 마틴" in out
    assert "LOCATION:중앙도서관" in out


def test_escaping_and_no_loans() -> None:
    deadlines = [
        {
            "title": "보고서; 제출, 필독\\주의",
            "due": "2026-07-01T18:00:00+09:00",
            "course": None,
            "url": None,
        },
    ]
    out = ics.build_ics(deadlines, None)
    # ; , \ must be escaped per RFC 5545 §3.3.11.
    assert "SUMMARY:보고서\\; 제출\\, 필독\\\\주의" in out
    assert len(_events(out)) == 1


def test_naive_datetime_treated_as_kst() -> None:
    out = ics.build_ics([{"title": "T", "due": "2026-06-15T09:00:00"}], None)
    # 09:00 KST -> 00:00 UTC same day.
    assert "DTSTART:20260615T000000Z" in out


def test_timed_deadline_is_instantaneous_without_dtend_or_duration() -> None:
    event = _events(ics.build_ics([{"title": "T", "due": "2026-09-22T09:00:00+09:00"}]))[0]
    assert "DTSTART:20260922T000000Z" in event
    assert not any(line.startswith(("DTEND", "DURATION")) for line in event.split("\r\n"))


@pytest.mark.parametrize("due", ["2026-09-22", "20260922", "2026-W39-2", None, "2026-09-22T"])
def test_ics_does_not_invent_deadline_time(due) -> None:
    assert _events(ics.build_ics([{"title": "T", "due": due}])) == []


@pytest.mark.parametrize("due", ["2026-09-22", "20260922", "2026-W39-2", None, "2026-09-22T"])
def test_agenda_keeps_deadline_without_time_unresolved(due) -> None:
    from datetime import datetime

    result = ics.build_agenda(
        [{"title": "T", "due": due, "due_text": "Original deadline"}], [],
        now=datetime(2026, 9, 22, tzinfo=ics.KST),
    )
    assert result["events"] == []
    assert len(result["undated_items"]) == 1
    assert result["undated_items"][0]["due_raw"] == "Original deadline"


@pytest.mark.parametrize("stamp", [
    "2026-09-22T10:00:00+09:00", "2026-09-22T10:00:00", "2026-09-22T01:00:00+00:00",
])
def test_deadline_and_loan_dtstamp_is_utc(stamp) -> None:
    from datetime import datetime

    result = ics.build_ics(
        [{"title": "T", "due": "2026-09-22T09:00:00+09:00"}],
        [{"title_author": "Book", "due_date": "2026-09-22"}],
        now=datetime.fromisoformat(stamp),
    )
    assert result.count("DTSTAMP:20260922T010000Z\r\n") == 2


@pytest.mark.parametrize(("url", "expected"), [
    ("https://example.test/task;a,b?q=a,b;c", "https://example.test/task;a,b?q=a,b;c"),
    ("https://example.test/a b\\c\r\nSUMMARY:Injected", "https://example.test/a%20b%5Cc%0D%0ASUMMARY:Injected"),
])
def test_ics_url_uses_uri_encoding_not_text_escaping(url, expected) -> None:
    result = ics.build_ics([{"title": "T", "due": "2026-09-22T09:00:00+09:00", "url": url}])
    unfolded = result.replace("\r\n ", "")
    assert f"URL:{expected}\r\n" in unfolded
    assert "\r\nSUMMARY:Injected" not in result


def test_empty() -> None:
    out = ics.build_ics([], [])
    assert _events(out) == []
    assert "BEGIN:VCALENDAR" in out and "END:VCALENDAR" in out


def test_line_folding() -> None:
    long_title = "가" * 200  # 600 UTF-8 bytes -> must fold
    out = ics.build_ics(
        [{"title": long_title, "due": "2026-06-15T10:00:00+09:00"}], None
    )
    for line in out.split("\r\n"):
        assert len(line.encode("utf-8")) <= 75, f"unfolded line: {len(line)} bytes"


if __name__ == "__main__":
    test_basic_structure()
    test_escaping_and_no_loans()
    test_naive_datetime_treated_as_kst()
    test_empty()
    test_line_folding()
    print("ICS UNIT TESTS PASSED")

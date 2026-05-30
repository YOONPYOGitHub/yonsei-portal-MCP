"""Unit tests for the pure ICS generator (no browser / no network).

Run: ``uv run python tests/test_ics.py``
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from yonsei_portal_mcp import ics  # noqa: E402


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

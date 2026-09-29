"""Pure, dependency-free iCalendar (RFC 5545) export.

The portal scrapers already hand back KST ISO-8601 due times for LearnUs
deadlines and date strings for library loan due dates, so turning them into an
``.ics`` feed is a *local* transform with no extra portal dependency. We emit
the text by hand (no third-party library) to keep the package light enough for
``uvx`` distribution.
"""
from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable, Optional
from urllib.parse import quote

PRODID = "-//yonsei-portal-mcp//ICS//KO"
KST = timezone(timedelta(hours=9))
_TIME_GROUP = r"[월화수목금토일]\s*[1-9][0-9]?(?:\s*,\s*[1-9][0-9]?)*"
_TIME_GRAMMAR = re.compile(rf"\s*{_TIME_GROUP}(?:\s*,?\s*{_TIME_GROUP})*\s*")


def build_agenda(
    deadlines: Iterable[dict], loans: Iterable[dict], *,
    days: int = 7, now: Optional[datetime] = None,
) -> dict:
    """Combine dated events without inventing times for weekly classes or unknown dates."""
    if not 1 <= days <= 90:
        raise ValueError("days는 1~90이어야 합니다.")
    current = now or datetime.now(KST)
    if current.tzinfo is None:
        current = current.replace(tzinfo=KST)
    start = current.astimezone(KST).date()
    end = start + timedelta(days=days)
    events, undated = [], []
    for deadline in deadlines:
        event = {
            "title": deadline.get("title"), "kind": deadline.get("kind") or "unknown",
            "source": "learnus", "course": deadline.get("course"), "url": deadline.get("url"),
            "due_raw": deadline.get("due_text") or deadline.get("due"),
        }
        parsed = _parse_deadline(deadline.get("due"))
        if parsed is None:
            undated.append(event)
            continue
        parsed = parsed.astimezone(KST)
        if start <= parsed.date() < end:
            events.append({**event, "date": parsed.date().isoformat(), "due": parsed.isoformat(), "all_day": False})
    for loan in loans:
        event = {"title": loan.get("title_author"), "kind": "loan_return", "source": "library", "due_raw": loan.get("due_date")}
        due = _parse_date(loan.get("due_date") or "")
        if due is None:
            undated.append(event)
        elif start <= due < end:
            events.append({**event, "date": due.isoformat(), "due": None, "all_day": True})
    events.sort(key=lambda item: (item["date"], item.get("due") or "", item.get("title") or ""))
    return {
        "window": {"start": start.isoformat(), "end_exclusive": end.isoformat(), "timezone": "Asia/Seoul"},
        "count": len(events), "events": events, "undated_items": undated,
    }

# Library due-date cells come in a few shapes ("2026-06-15", "2026.06.15",
# "2026/06/15", possibly with a trailing time). Pull the first Y-M-D triple.
_DATE_RE = re.compile(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})")


def _escape(text: str) -> str:
    """Escape TEXT values per RFC 5545 §3.3.11."""
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def _fold(line: str) -> str:
    """Fold a content line to <=75 octets (RFC 5545 §3.1) on UTF-8 boundaries."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    chunks: list[bytes] = []
    buf = bytearray()
    limit = 75
    for ch in line:
        enc = ch.encode("utf-8")
        if len(buf) + len(enc) > limit:
            chunks.append(bytes(buf))
            buf = bytearray()
            limit = 74  # continuation lines start with a leading space
        buf += enc
    chunks.append(bytes(buf))
    return "\r\n ".join(c.decode("utf-8") for c in chunks)


def _parse_deadline(iso: Optional[str]) -> Optional[datetime]:
    """Require an explicit time; interpret naive timestamps as KST."""
    if not isinstance(iso, str) or not re.search(r"[Tt ][0-9]{2}:[0-9]{2}", iso):
        return None
    try:
        parsed = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=KST) if parsed.tzinfo is None else parsed


def _dt_utc(iso: str) -> Optional[str]:
    """Convert an ISO-8601 timestamp (with offset) to UTC ``...Z`` form."""
    parsed = _parse_deadline(iso)
    return parsed.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ") if parsed else None


def _parse_date(text: str) -> Optional[date]:
    """Best-effort parse of a library due-date cell into a ``date``."""
    m = _DATE_RE.search(text or "")
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _uid(seed: str) -> str:
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]
    return f"{digest}@yonsei-portal-mcp"


def _vevent(lines: list[str], *, uid: str, dtstamp: str, summary: str) -> None:
    lines.append("BEGIN:VEVENT")
    lines.append(_fold(f"UID:{uid}"))
    lines.append(f"DTSTAMP:{dtstamp}")
    lines.append(_fold(f"SUMMARY:{_escape(summary)}"))


def build_ics(
    deadlines: Iterable[dict],
    loans: Optional[Iterable[dict]] = None,
    *,
    calendar_name: str = "연세 포털 일정",
    now: Optional[datetime] = None,
) -> str:
    """Render LearnUs deadlines (and optional library loans) as an ICS string.

    ``deadlines`` items follow :func:`scrapers.learnus.fetch_deadlines` (need a
    timezone-aware ``due`` ISO string to be included). ``loans`` items follow
    :func:`scrapers.library.fetch_my_loans` (need a parseable ``due_date``);
    each becomes an all-day reminder for the return date.
    """
    stamp = now or datetime.now(timezone.utc)
    stamp = stamp.replace(tzinfo=KST) if stamp.tzinfo is None else stamp
    dtstamp = stamp.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out: list[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        _fold(f"X-WR-CALNAME:{_escape(calendar_name)}"),
    ]

    for d in deadlines:
        start = _dt_utc(d.get("due") or "")
        if not start:
            continue  # no concrete time -> not a calendar event
        title = d.get("title") or "(제목 없음)"
        course = d.get("course")
        summary = f"[{course}] {title}" if course else title
        uid = _uid(d.get("url") or f"{title}{d.get('due')}")
        _vevent(out, uid=uid, dtstamp=dtstamp, summary=summary)
        out.append(f"DTSTART:{start}")
        desc_parts = [p for p in (d.get("due_text"), d.get("course")) if p]
        if desc_parts:
            out.append(_fold(f"DESCRIPTION:{_escape(' / '.join(desc_parts))}"))
        if d.get("url"):
            url = quote(d["url"], safe=":/?#[]@!$&'()*+,;=%")
            out.append(_fold(f"URL:{url}"))
        out.append("END:VEVENT")

    for ln in loans or []:
        due = _parse_date(ln.get("due_date") or "")
        if not due:
            continue
        title = ln.get("title_author") or "(서명 미상)"
        summary = f"[도서 반납] {title}"
        uid = _uid(f"loan:{ln.get('reg_no') or title}:{due.isoformat()}")
        _vevent(out, uid=uid, dtstamp=dtstamp, summary=summary)
        # All-day event: DTSTART/DTEND are dates; DTEND is exclusive (+1 day).
        out.append(f"DTSTART;VALUE=DATE:{due.strftime('%Y%m%d')}")
        out.append(
            f"DTEND;VALUE=DATE:{(due + timedelta(days=1)).strftime('%Y%m%d')}"
        )
        loc = ln.get("location")
        if loc:
            out.append(_fold(f"LOCATION:{_escape(loc)}"))
        out.append("END:VEVENT")

    out.append("END:VCALENDAR")
    return "\r\n".join(out) + "\r\n"


def build_timetable_ics(
    timetable: dict, start_date: str, end_date: str,
    period_times: dict[str, dict[str, str]], *,
    exclude_dates: Optional[list[str]] = None, now: Optional[datetime] = None,
) -> str:
    """Export weekly periods with caller-confirmed dates/times, never inferred ones."""
    def checked_date(value: str) -> date:
        if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
            raise ValueError("날짜는 YYYY-MM-DD 형식이어야 합니다.")
        return date.fromisoformat(value)

    start, end = checked_date(start_date), checked_date(end_date)
    if end < start or (end - start).days > 366:
        raise ValueError("수업 기간은 시작일 이상, 최대 366일이어야 합니다.")
    excluded = {checked_date(value) for value in exclude_dates or []}
    if any(value < start or value > end for value in excluded):
        raise ValueError("제외일은 지정한 수업 기간 안에 있어야 합니다.")
    periods = {}
    for period, times in period_times.items():
        if not re.fullmatch(r"[1-9][0-9]?", period) or not isinstance(times, dict):
            raise ValueError("교시 키는 1~99, 값은 start/end 시각이어야 합니다.")
        parsed = []
        for key in ("start", "end"):
            value = times.get(key)
            if not isinstance(value, str) or not re.fullmatch(r"[0-9]{2}:[0-9]{2}", value):
                raise ValueError("교시 시각은 HH:MM 형식이어야 합니다.")
            parsed.append(time.fromisoformat(value))
        if parsed[1] <= parsed[0]:
            raise ValueError("교시 종료는 같은 날의 시작 시각보다 뒤여야 합니다.")
        periods[int(period)] = tuple(parsed)
    courses = timetable.get("courses")
    if not isinstance(courses, list) or not courses:
        raise ValueError("내보낼 시간표 과목이 없습니다.")
    weekdays = {"월": "Mon", "화": "Tue", "수": "Wed", "목": "Thu", "금": "Fri", "토": "Sat", "일": "Sun"}
    stamp = now or datetime.now(timezone.utc)
    stamp = stamp.replace(tzinfo=KST) if stamp.tzinfo is None else stamp
    dtstamp = stamp.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    until = datetime.combine(end, time(23, 59, 59), KST).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:{PRODID}", "CALSCALE:GREGORIAN", "METHOD:PUBLISH", _fold("X-WR-CALNAME:연세 주간 시간표")]
    seen = set()
    for course in courses:
        if not all(course.get(key) for key in ("course_code", "section", "course_name", "slots")):
            raise ValueError("시간표의 과목·분반·교시 정보를 확인하지 못했습니다.")
        raw = course.get("time_raw")
        if not isinstance(raw, str) or not _TIME_GRAMMAR.fullmatch(raw):
            raise ValueError("해석할 수 없는 강의시간이 있어 내보내지 않습니다.")
        raw = re.sub(r"\s+", "", raw)
        expected = set()
        for match in re.finditer(r"([월화수목금토일])([0-9]+(?:,[0-9]+)*)", raw):
            expected.update((weekdays[match[1]], int(value)) for value in match[2].split(","))
        supplied = {(slot.get("day_en"), slot.get("period")) for slot in course["slots"]}
        if supplied != expected:
            raise ValueError("원문 강의시간과 파싱된 교시가 다릅니다.")
        for day, period in sorted(expected):
            if period not in periods:
                raise ValueError("시간표에 사용된 모든 교시의 시작/종료 시각이 필요합니다.")
            weekday = list(weekdays.values()).index(day)
            first = start + timedelta(days=(weekday - start.weekday()) % 7)
            if first > end:
                continue
            begin_time, end_time = periods[period]
            begin = datetime.combine(first, begin_time, KST).astimezone(timezone.utc)
            finish = datetime.combine(first, end_time, KST).astimezone(timezone.utc)
            uid = _uid(f"timetable:{timetable.get('term')}:{course['course_code']}:{course['section']}:{day}:{period}:{start}:{end}")
            if uid in seen:
                raise ValueError("시간표 과목과 교시가 중복되었습니다.")
            seen.add(uid)
            _vevent(out, uid=uid, dtstamp=dtstamp, summary=course["course_name"])
            out.extend([f"DTSTART:{begin:%Y%m%dT%H%M%SZ}", f"DTEND:{finish:%Y%m%dT%H%M%SZ}", f"RRULE:FREQ=WEEKLY;UNTIL={until}"])
            for excluded_date in sorted(excluded):
                if excluded_date.weekday() == weekday:
                    exception = datetime.combine(excluded_date, begin_time, KST).astimezone(timezone.utc)
                    out.append(f"EXDATE:{exception:%Y%m%dT%H%M%SZ}")
            if course.get("room"):
                out.append(_fold(f"LOCATION:{_escape(course['room'])}"))
            out.append(_fold("DESCRIPTION:" + _escape("기간·교시 시각은 사용자 지정입니다. 휴강/공휴일은 제외일 지정 없이는 자동 반영되지 않습니다.")))
            out.append("END:VEVENT")
    if not seen:
        raise ValueError("지정한 기간에 반복할 수업 요일이 없습니다.")
    out.append("END:VCALENDAR")
    return "\r\n".join(out) + "\r\n"

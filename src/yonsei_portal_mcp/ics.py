"""Pure, dependency-free iCalendar (RFC 5545) export (DESIGN §10.7 P1).

The portal scrapers already hand back KST ISO-8601 due times for LearnUs
deadlines and date strings for library loan due dates, so turning them into an
``.ics`` feed is a *local* transform with no extra portal dependency. We emit
the text by hand (no third-party library) to keep the package light enough for
``uvx`` distribution.
"""
from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Optional

PRODID = "-//yonsei-portal-mcp//ICS//KO"

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


def _dt_utc(iso: str) -> Optional[str]:
    """Convert an ISO-8601 timestamp (with offset) to UTC ``...Z`` form."""
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if dt.tzinfo is None:
        # Treat naive as KST per the scraper contract.
        dt = dt.replace(tzinfo=timezone(timedelta(hours=9)))
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


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
    dtstamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
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
        out.append(f"DTEND:{start}")
        desc_parts = [p for p in (d.get("due_text"), d.get("course")) if p]
        if desc_parts:
            out.append(_fold(f"DESCRIPTION:{_escape(' / '.join(desc_parts))}"))
        if d.get("url"):
            out.append(_fold(f"URL:{_escape(d['url'])}"))
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

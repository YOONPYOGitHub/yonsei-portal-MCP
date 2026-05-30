"""Yonsei Library (library.yonsei.ac.kr) page scrapers.

Each scraper navigates an authenticated :class:`~playwright.async_api.Page` and
extracts structured data via ``page.evaluate``. Selectors below were validated
against the live site.

These pages expose **personal** data (loaned book titles, due dates). We never
log it; the MCP layer hands it straight to the calling LLM (DESIGN §6).
"""
from __future__ import annotations

from playwright.async_api import Page

MYLOAN_URL = "https://library.yonsei.ac.kr/myloan/list"
SEAT_ROOMS_URL = "https://library.yonsei.ac.kr/relation/seat"

# --------------------------------------------------------------------------- #
# JavaScript snippets (run inside the page DOM)
# --------------------------------------------------------------------------- #

_MYLOAN_JS = r"""
() => {
  const t = document.querySelector('table.mobileTable') || document.querySelector('table');
  if (!t) return { headers: [], rows: [] };
  const headers = Array.from(t.querySelectorAll('thead th, thead td'))
    .map(c => (c.innerText || '').replace(/\s+/g, ' ').trim());
  const rows = [];
  t.querySelectorAll('tbody tr').forEach(tr => {
    const cells = Array.from(tr.querySelectorAll('td'))
      .map(c => (c.innerText || '').replace(/\s+/g, ' ').trim());
    // The "no results" placeholder renders as a single spanned cell.
    if (cells.filter(c => c).length <= 1) return;
    rows.push(cells);
  });
  return { headers, rows };
}
"""

# Map the live table headers to stable English keys for the JSON payload.
_LOAN_FIELD_MAP = {
    "서명/저자": "title_author",
    "소장처": "location",
    "등록번호": "reg_no",
    "대출일": "loan_date",
    "반납예정일": "due_date",
    "연체료": "overdue_fee",
    "연장횟수": "renew_count",
}


# --------------------------------------------------------------------------- #
# Scrapers
# --------------------------------------------------------------------------- #

async def fetch_my_loans(page: Page) -> dict:
    """Return the student's current library loans (대출 현황).

    Each loan carries: 서명/저자(title_author), 소장처(location), 등록번호(reg_no),
    대출일(loan_date), 반납예정일(due_date), 연체료(overdue_fee),
    연장횟수(renew_count). Personal data — never logged. An empty list means no
    books are currently on loan.
    """
    await page.goto(MYLOAN_URL, wait_until="networkidle")
    await page.wait_for_timeout(800)
    data = await page.evaluate(_MYLOAN_JS)

    headers: list[str] = (data or {}).get("headers", [])
    raw_rows: list[list[str]] = (data or {}).get("rows", [])

    loans: list[dict] = []
    for row in raw_rows:
        by_header: dict[str, str] = {}
        for i, value in enumerate(row):
            header = headers[i] if i < len(headers) else ""
            if header:
                by_header[header] = value
        loan = {key: by_header.get(label) for label, key in _LOAN_FIELD_MAP.items()}
        loans.append(loan)

    return {"count": len(loans), "loans": loans}


# --------------------------------------------------------------------------- #
# Reading-room seats (login required; NOT personal data)
# --------------------------------------------------------------------------- #

_SEATROOM_JS = r"""
() => {
  const t = document.querySelector('table.seatTbl') || document.querySelector('table');
  if (!t) return { rows: [] };
  const rows = [];
  t.querySelectorAll('tbody tr').forEach(tr => {
    const cells = Array.from(tr.querySelectorAll('td'))
      .map(c => (c.innerText || '').replace(/\s+/g, ' ').trim());
    if (cells.filter(c => c).length <= 1) return;
    rows.push(cells);
  });
  return { rows };
}
"""

# Status badges appended to the room name cell.
_SEAT_STATUS = ("배정불가", "배정가능")


def _to_int(text: str | None) -> int | None:
    if not text:
        return None
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else None


def _parse_seat_room(cells: list[str]) -> dict:
    # Columns: 실명 / 전체좌석 / 사용중 / 이용가능석 / 운영시간 / 이용률 / 추가정보안내
    name = cells[0] if len(cells) > 0 else ""
    assignable: bool | None = None
    for status in _SEAT_STATUS:
        if name.endswith(status):
            assignable = status == "배정가능"
            name = name[: -len(status)].strip()
            break

    # 전체좌석 cell looks like "134(136)" -> operating(capacity), or plain int.
    total_cell = cells[1] if len(cells) > 1 else ""
    operating = capacity = None
    if "(" in total_cell and ")" in total_cell:
        head, _, tail = total_cell.partition("(")
        operating = _to_int(head)
        capacity = _to_int(tail)
    else:
        operating = _to_int(total_cell)

    usage_raw = cells[5] if len(cells) > 5 else ""
    usage_pct: float | None = None
    digits = usage_raw.replace("%", "").strip()
    if digits:
        try:
            usage_pct = float(digits)
        except ValueError:
            usage_pct = None

    return {
        "name": name,
        "assignable": assignable,
        "total": operating,
        "capacity": capacity,
        "in_use": _to_int(cells[2]) if len(cells) > 2 else None,
        "available": _to_int(cells[3]) if len(cells) > 3 else None,
        "hours": cells[4].replace("~ ", "~") if len(cells) > 4 else None,
        "usage_pct": usage_pct,
        "note": cells[6] if len(cells) > 6 and cells[6] else None,
    }


async def fetch_seat_rooms(page: Page) -> dict:
    """Return per-reading-room seat availability (열람실별 좌석현황, 로그인 필요).

    Each room carries: 실명(name), 배정가능 여부(assignable), 운영좌석(total),
    수용좌석(capacity), 사용중(in_use), 이용가능석(available), 운영시간(hours),
    이용률%(usage_pct), 추가정보(note). Not personal data, but login-gated, so it
    runs through the authenticated library session.
    """
    await page.goto(SEAT_ROOMS_URL, wait_until="networkidle")
    await page.wait_for_timeout(1200)
    data = await page.evaluate(_SEATROOM_JS)

    rooms = [_parse_seat_room(r) for r in (data or {}).get("rows", [])]
    total = sum(r["total"] or 0 for r in rooms)
    in_use = sum(r["in_use"] or 0 for r in rooms)
    available = sum(r["available"] or 0 for r in rooms)
    usage_pct = round(in_use / total * 100, 1) if total else 0.0
    return {
        "count": len(rooms),
        "rooms": rooms,
        "total": total,
        "in_use": in_use,
        "available": available,
        "usage_pct": usage_pct,
    }

"""Public (no-login) library seat availability (DESIGN §10.6, P1).

The library home page's seat widget calls ``GET /seat/info`` which returns a
campus-level aggregate as JSON **without authentication**. We expose that as a
zero-friction tool via the lightweight httpx path (no browser). Granularity is
limited to *building-group × seat-type* totals; per-reading-room drill-down
requires login (handled separately).

No PII is involved.
"""
from __future__ import annotations

from .. import httpclient
from ..config import LIBRARY_SEAT_INFO_URL

# JSON key prefixes -> human label. Building mapping is the library's own
# wording (확인 2026-05-31; exact building identity is the site's, not ours).
_BUILDINGS = {
    "center": "중앙도서관",
    "yonsei": "학술정보원",
}
# Seat-type suffixes -> label (추정; site exposes only the English keys).
_SEAT_TYPES = {
    "general": "일반열람석",
    "pc": "PC석",
    "study": "스터디룸",
    "notebook": "노트북석",
}


def _pct(use: int, total: int) -> float:
    return round(use / total * 100, 1) if total else 0.0


def _parse(data: dict) -> dict:
    rows: list[dict] = []
    for bkey, bname in _BUILDINGS.items():
        for tkey, tname in _SEAT_TYPES.items():
            total = int(data.get(f"{bkey}_{tkey}_total") or 0)
            use = int(data.get(f"{bkey}_{tkey}_use") or 0)
            if total == 0 and use == 0:
                continue  # category not offered in this building
            remaining = max(total - use, 0)
            rows.append(
                {
                    "building": bname,
                    "building_code": bkey,
                    "seat_type": tname,
                    "seat_type_code": tkey,
                    "total": total,
                    "in_use": use,
                    "remaining": remaining,
                    "usage_pct": _pct(use, total),
                }
            )

    t_total = sum(r["total"] for r in rows)
    t_use = sum(r["in_use"] for r in rows)
    return {
        "rows": rows,
        "total": t_total,
        "in_use": t_use,
        "remaining": max(t_total - t_use, 0),
        "usage_pct": _pct(t_use, t_total),
    }


async def fetch_seats(seat_type: str | None = None) -> dict:
    """Return aggregate seat availability (no login).

    Pass ``seat_type`` (one of the keys/labels in :data:`_SEAT_TYPES`) to filter
    the ``rows`` to a single category; aggregate totals are recomputed for the
    filtered view.
    """
    data = await httpclient.get_json(LIBRARY_SEAT_INFO_URL)
    result = _parse(data)

    if seat_type:
        wanted = seat_type.strip().lower()
        code = wanted
        for tkey, tname in _SEAT_TYPES.items():
            if wanted in (tkey, tname.lower()):
                code = tkey
                break
        rows = [r for r in result["rows"] if r["seat_type_code"] == code]
        t_total = sum(r["total"] for r in rows)
        t_use = sum(r["in_use"] for r in rows)
        result = {
            "rows": rows,
            "total": t_total,
            "in_use": t_use,
            "remaining": max(t_total - t_use, 0),
            "usage_pct": _pct(t_use, t_total),
        }
    return result

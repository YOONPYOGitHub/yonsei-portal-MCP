"""Public (no-login) library seat availability.

The library home page's seat widget calls ``GET /seat/info`` which returns a
campus-level aggregate as JSON **without authentication**. We expose that as a
zero-friction tool via the lightweight httpx path (no browser). Granularity is
limited to *building-group × seat-type* totals; per-reading-room drill-down
requires login (handled separately).

No PII is involved.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .. import httpclient
from ..config import LIBRARY_SEAT_INFO_URL
from ..errors import ScrapeFailedError

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
    required = {f"{building}_{kind}_{field}" for building in _BUILDINGS for kind in _SEAT_TYPES for field in ("total", "use")}
    if not isinstance(data, dict) or not required <= data.keys():
        raise ScrapeFailedError("공개 좌석 응답 필드가 누락되었습니다. 0석을 의미하지 않습니다.")
    if any(type(data[key]) is not int or data[key] < 0 for key in required):
        raise ScrapeFailedError("공개 좌석 응답에 유효하지 않은 숫자가 있습니다.")
    rows: list[dict] = []
    for bkey, bname in _BUILDINGS.items():
        for tkey, tname in _SEAT_TYPES.items():
            total = data[f"{bkey}_{tkey}_total"]
            use = data[f"{bkey}_{tkey}_use"]
            if use > total:
                raise ScrapeFailedError("공개 좌석 사용중 수가 전체좌석보다 큽니다.")
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
    result.update(
        source_url=LIBRARY_SEAT_INFO_URL,
        fetched_at=datetime.now(timezone.utc).isoformat(),
        availability_note="공개 건물군 집계입니다. 열람실별 배정 가능 여부나 현재 착석 가능성을 보장하지 않습니다. 별도 좌석 시스템과 수치가 다를 수 있습니다.",
    )
    return result

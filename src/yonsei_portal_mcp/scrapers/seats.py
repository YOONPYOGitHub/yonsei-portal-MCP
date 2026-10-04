"""Public (no-login) library seat availability.

The homepage widget calls ``POST /seat/info``; GET also returns public JSON.
Its displayed columns conflict with the API key names. Preserve raw values
without claiming that ``use`` means occupied or available seats. The separate
authenticated reading-room table provides verified displayed availability.

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
# Homepage seat-type labels; occupancy semantics remain unverified.
_SEAT_TYPES = {
    "general": "일반열람석",
    "pc": "PC석",
    "study": "스터디룸",
    "notebook": "노트북석",
}


def _summarize(rows: list[dict]) -> dict:
    total = sum(row["total"] for row in rows)
    raw_use = sum(row["raw_use"] for row in rows)
    return {
        "rows": rows, "total": total, "raw_use": raw_use,
        "raw_total_minus_use": total - raw_use,
        "in_use": None, "remaining": None, "usage_pct": None,
        "semantics_verified": False, "scope": "public_widget_api",
    }


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
                raise ScrapeFailedError("공개 좌석 원문 use 값이 total보다 큽니다.")
            if total == 0 and use == 0:
                continue  # category not offered in this building
            rows.append(
                {
                    "building": bname,
                    "building_code": bkey,
                    "seat_type": tname,
                    "seat_type_code": tkey,
                    "total": total,
                    "raw_use": use,
                    "raw_total_minus_use": total - use,
                    "in_use": None,
                    "remaining": None,
                    "usage_pct": None,
                }
            )

    return _summarize(rows)


async def fetch_seats(seat_type: str | None = None) -> dict:
    """Return aggregate seat availability (no login).

    Pass ``seat_type`` (one of the keys/labels in :data:`_SEAT_TYPES`) to filter
    the ``rows`` to a single category; aggregate totals are recomputed for the
    filtered view.
    """
    code = None
    if seat_type is not None and seat_type != "":
        if not isinstance(seat_type, str):
            raise ValueError("seat_type은 지원 좌석 유형 문자열이어야 합니다.")
        wanted = seat_type.strip().lower()
        for tkey, tname in _SEAT_TYPES.items():
            if wanted in (tkey, tname.lower()):
                code = tkey
                break
        if code is None:
            raise ValueError("seat_type은 general/pc/study/notebook 또는 해당 한글 유형명이어야 합니다.")
    data = await httpclient.get_json(LIBRARY_SEAT_INFO_URL)
    result = _parse(data)
    if code is not None:
        result = _summarize([row for row in result["rows"] if row["seat_type_code"] == code])
    result.update(
        source_url=LIBRARY_SEAT_INFO_URL,
        fetched_at=datetime.now(timezone.utc).isoformat(),
        availability_note="공개 API use와 홈페이지 사용/잔여 칸의 의미가 충돌해 검증되지 않았습니다. raw_use와 raw_total_minus_use를 사용중/잔여석으로 해석하지 마세요. in_use/remaining/usage_pct는 미확인 null입니다. 열람실별 표시 현황은 로그인 후 get_library_seat_rooms로 확인하세요. 두 원천의 범위가 같다는 보장은 없습니다.",
    )
    return result

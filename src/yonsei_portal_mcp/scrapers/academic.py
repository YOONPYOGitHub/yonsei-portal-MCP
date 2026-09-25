"""Read the official public academic calendar without guessing cross-month dates."""
from __future__ import annotations

import re
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup

from .. import httpclient
from ..errors import ScrapeFailedError, UpstreamTimeoutError

CALENDAR_URL = "https://www.yonsei.ac.kr/sc/373/subview.do"


def parse_calendar(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    year_input = soup.select_one("input#year")
    half_input = soup.select_one("input#half")
    boxes = soup.select("#timeTableList .box-sch")
    if year_input is None or half_input is None or not boxes:
        raise ScrapeFailedError("공식 학사일정의 학기/목록 구조를 확인하지 못했습니다.")
    year_raw = year_input.get("value", "")
    half = half_input.get("value")
    if not isinstance(year_raw, str) or not re.fullmatch(r"20[0-9]{2}", year_raw) or half not in {"first", "second"}:
        raise ScrapeFailedError("공식 학사일정의 연도/학기 값을 확인하지 못했습니다.")
    academic_year = int(year_raw)
    display_year, previous_month = academic_year, 0
    months, seen = [], set()
    for box in boxes:
        label = box.select_one(".num h3 span")
        match = re.fullmatch(r"([0-9]{1,2})월", label.get_text(strip=True)) if label else None
        if not match or not 1 <= int(match[1]) <= 12:
            raise ScrapeFailedError("공식 학사일정 월 표기를 확인하지 못했습니다.")
        month = int(match[1])
        if month < previous_month:
            display_year += 1
        if month in seen or display_year > academic_year + 1:
            raise ScrapeFailedError("공식 학사일정의 월 순서가 중복되거나 변경되었습니다.")
        seen.add(month)
        previous_month = month
        events = []
        for row in box.select(".desc dl"):
            date_label, title = row.find("dt"), row.find("dd")
            if date_label is None or title is None or not date_label.get_text(strip=True) or not title.get_text(strip=True):
                raise ScrapeFailedError("공식 학사일정 항목의 날짜/제목이 없습니다.")
            events.append({"date_raw": " ".join(date_label.get_text(" ", strip=True).split()), "title": " ".join(title.get_text(" ", strip=True).split())})
        if not events:
            raise ScrapeFailedError("공식 학사일정 목록이 비어 있어 확인이 필요합니다.")
        months.append({"display_year": display_year, "month": month, "events": events})
    return {
        "academic_year": academic_year, "semester": half,
        "count": sum(len(month["events"]) for month in months), "months": months,
        "source_url": CALENDAR_URL,
        "date_note": "날짜 구간은 원문 그대로입니다. 월 경계 항목은 여러 월에 반복 표시될 수 있으며 display_year/month는 표시 구간이지 모든 이벤트의 시작 월이 아닙니다. 개인별 수업/시험은 해당 학과 안내를 확인하세요.",
    }


async def fetch_calendar() -> dict:
    try:
        html = await httpclient.get_html(CALENDAR_URL)
    except httpx.TimeoutException:
        raise UpstreamTimeoutError("공식 학사일정 응답 시간이 초과되었습니다.") from None
    except httpx.HTTPError:
        raise ScrapeFailedError("공식 학사일정을 불러오지 못했습니다.") from None
    result = parse_calendar(html)
    result["fetched_at"] = datetime.now(timezone.utc).isoformat()
    return result
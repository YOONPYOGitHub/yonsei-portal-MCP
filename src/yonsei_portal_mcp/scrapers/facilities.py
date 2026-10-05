"""Read facility selectors and timetable marks without submitting reservations."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from playwright.async_api import Page

from ..errors import ScrapeFailedError

FACILITY_URL = "https://libadm.yonsei.ac.kr:444/fac"
_ENTRY_URL = "https://library.yonsei.ac.kr/relation/seat"
_COLUMNS = "table.facilityTbl.onlyPc tbody > tr > td"
_OPTION_KEYS = ("dates", "buildings", "groups", "facilities", "durations")


def validate_filters(date: str | None = None, building: str | None = None, group: str | None = None, facility: str | None = None, duration_minutes: int | None = None) -> None:
    if date is not None:
        if not isinstance(date, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", date):
            raise ValueError("date는 YYYY-MM-DD 형식이어야 합니다.")
        datetime.strptime(date, "%Y-%m-%d")
    if building is not None and building not in {"학술정보관", "중앙도서관"}:
        raise ValueError("building은 화면의 학술정보관/중앙도서관입니다.")
    for label in (group, facility):
        if label is not None and (not isinstance(label, str) or not 1 <= len(label.strip()) <= 200):
            raise ValueError("group/facility는 조회 목록의 1~200자 이름이어야 합니다.")
    if group is not None and building is None or facility is not None and group is None:
        raise ValueError("building, group, facility 순서로 앞 단계의 이름이 필요합니다.")
    if duration_minutes is not None and (facility is None or type(duration_minutes) is not int or not 1 <= duration_minutes <= 1440):
        raise ValueError("duration_minutes는 facility와 함께 1~1440 정수로 지정하세요.")


def parse_timeline(cells: list[dict], unit_minutes: int) -> list[dict]:
    if type(unit_minutes) is not int or not 1 <= unit_minutes <= 60 or 60 % unit_minutes or not isinstance(cells, list) or len(cells) < 2:
        raise ScrapeFailedError("시설 시간표의 구간 단위를 확인하지 못했습니다.")
    if any(not isinstance(cell, dict) or not isinstance(cell.get("label"), str) or not isinstance(cell.get("classes"), list) for cell in cells):
        raise ScrapeFailedError("시설 시간표의 셀 형식이 변경되었습니다.")
    if not re.fullmatch(r"[0-9]{1,2}", cells[0]["label"]) or not re.fullmatch(r"[0-9]{1,2}", cells[-1]["label"]):
        raise ScrapeFailedError("시설 시간표 시작·종료 시각을 확인하지 못했습니다.")
    start, end = int(cells[0]["label"]) * 60, int(cells[-1]["label"]) * 60
    if not 0 <= start < end <= 1440 or len(cells) != (end - start) // unit_minutes + 1:
        raise ScrapeFailedError("시설 시간표 시각과 구간 수가 일치하지 않습니다.")
    slots = []
    for index, cell in enumerate(cells):
        minute = start + index * unit_minutes
        expected_label = str(minute // 60) if minute % 60 == 0 else ""
        if cell["label"] != expected_label or any(value not in {"times", "use", "past"} for value in cell["classes"]):
            raise ScrapeFailedError("시설 시간표의 시간 또는 상태 표시가 변경되었습니다.")
        if index == len(cells) - 1:
            break
        used = "use" in cell["classes"]
        past = "past" in cell["classes"]
        # Report literal DOM marks, not inferred reservation availability.
        display_marks = (["사용 표시"] if used else []) + (["과거 표시"] if past else [])
        next_minute = minute + unit_minutes
        slots.append({
            "start": f"{minute // 60:02d}:{minute % 60:02d}",
            "end": f"{next_minute // 60:02d}:{next_minute % 60:02d}",
            "used_mark": used, "past_mark": past,
            "display_status": " · ".join(display_marks) or "표시 없음",
        })
    return slots


def parse_options_snapshot(source: dict) -> dict:
    if not isinstance(source, dict) or source.get("headers") != ["날짜", "도서관 선택", "그룹", "시설", "사용시간"]:
        raise ScrapeFailedError("시설 선택 표의 머리글 또는 열 순서가 변경되었습니다.")
    columns = source.get("columns")
    if not isinstance(columns, list) or len(columns) != len(_OPTION_KEYS):
        raise ScrapeFailedError("시설 선택 표의 필수 열이 누락되었습니다.")
    for column in columns:
        if not isinstance(column, list) or any(not isinstance(option, dict) or not isinstance(option.get("name"), str) or not option["name"] or type(option.get("selected")) is not bool or type(option.get("selectable")) is not bool for option in column):
            raise ScrapeFailedError("시설 선택 항목의 표시 상태를 확인하지 못했습니다.")
        if len({option["name"] for option in column}) != len(column) or sum(option["selected"] for option in column) > 1:
            raise ScrapeFailedError("시설 선택 항목의 이름 또는 선택 상태가 중복됩니다.")
    return dict(zip(_OPTION_KEYS, columns))


def verify_selection(options: dict, selected: dict) -> None:
    columns = {"date": ("dates", "date"), "building": ("buildings", "name"), "group": ("groups", "name"), "facility": ("facilities", "name"), "duration_minutes": ("durations", "minutes")}
    for key, expected in selected.items():
        if expected is None:
            continue
        column, field = columns[key]
        current = [option.get(field) for option in options[column] if option["selected"]]
        if current != [expected]:
            raise ScrapeFailedError("시설 화면의 최종 선택값이 요청과 다릅니다.")


async def _snapshot(page: Page) -> dict:
    source = await page.locator("table.facilityTbl.onlyPc").evaluate(r"""table => ({
        headers: Array.from(table.querySelectorAll('thead th'), cell => cell.textContent.trim()),
        columns: Array.from(table.querySelectorAll('tbody > tr > td'), cell => Array.from(cell.querySelectorAll('.selectFacility'), element => ({
            name: element.textContent.trim().replace(/\s+/g, ' '),
            selectable: !element.classList.contains('disable'), selected: element.classList.contains('active')
        })))
    })""")
    return parse_options_snapshot(source)


async def _options(page: Page, column: int) -> list[dict]:
    return (await _snapshot(page))[_OPTION_KEYS[column]]


async def _choose(page: Page, column: int, name: str) -> bool:
    choices = await _options(page, column)
    indexes = [index for index, choice in enumerate(choices) if choice["name"] == name]
    if len(indexes) != 1:
        raise ValueError("요청한 선택값이 현재 시설 화면 목록에 없습니다. options의 이름을 사용하세요.")
    index = indexes[0]
    if not choices[index]["selectable"]:
        return False
    await page.locator(_COLUMNS).nth(column).locator(".selectFacility").nth(index).click()
    await page.wait_for_function(r"""({selector, column, name}) => {
        const selected = document.querySelectorAll(selector)[column]?.querySelector('.selectFacility.active');
        return selected?.textContent.trim().replace(/\s+/g, ' ') === name;
    }""", arg={"selector": _COLUMNS, "column": column, "name": name}, timeout=15_000)
    return True


def _duration(label: str) -> int:
    match = re.fullmatch(r"(?:(\d+)시간)?(?:(\d+)분)?", re.sub(r"\s+", "", label))
    if not match or not any(match.groups()):
        raise ScrapeFailedError("시설 사용시간 선택지 형식이 변경되었습니다.")
    return int(match[1] or 0) * 60 + int(match[2] or 0)


async def fetch_facility_status(page: Page, date: str | None = None, building: str | None = None, group: str | None = None, facility: str | None = None, duration_minutes: int | None = None) -> dict:
    validate_filters(date, building, group, facility, duration_minutes)
    await page.goto(_ENTRY_URL, wait_until="domcontentloaded")
    await page.wait_for_selector('a[href="/fac"]', timeout=15_000)
    parsed = urlsplit(page.url)
    if (parsed.scheme, parsed.hostname, parsed.port) != ("https", "libadm.yonsei.ac.kr", 444):
        raise ScrapeFailedError("시설 시스템의 인증된 진입 출처가 변경되었습니다.")
    blocked = []

    async def readonly(route):
        if route.request.method in {"GET", "HEAD"}:
            await route.continue_()
        else:
            blocked.append(route.request.method)
            await route.abort()

    await page.route("https://libadm.yonsei.ac.kr:444/**", readonly)
    requested = {"date": date, "building": building, "group": group, "facility": facility, "duration_minutes": duration_minutes}
    selected = {key: None for key in requested}
    dates = []
    date_names = []

    async def finish(slots=None, unavailable=None):
        if blocked:
            raise ScrapeFailedError("시설 조회 중 변경 요청을 차단했습니다. 예약은 실행하지 않았습니다.")
        options = await _snapshot(page)
        if [option["name"] for option in options["dates"]] != date_names:
            raise ScrapeFailedError("시설 조회 중 날짜 목록이 변경되었습니다.")
        for original, value in zip(options["dates"], dates):
            original["date"] = value
        for option in options["durations"]:
            option["minutes"] = _duration(option["name"])
        verify_selection(options, selected)
        return {
            "requested_filters": requested, "selected": selected, "options": options,
            "selection_applied": unavailable is None, "unavailable_selection": unavailable,
            "time_slots": slots, "count": len(slots) if slots is not None else None,
            "scope": "facility_ui", "display_verified": True,
            "source_url": FACILITY_URL, "fetched_at": datetime.now(timezone.utc).isoformat(),
            "note": "선택된 조건의 웹 화면 표시입니다. time_slots=null은 시간표 미선택이지 예약 가능 시간 없음이 아닙니다. 사용 표시가 없는 구간도 이용 자격·인원·사용시간·정책을 모두 만족해 예약이 확정된다는 뜻은 아닙니다. 예약자·참여자 정보는 반환하지 않으며 예약/취소 요청과 시간대 클릭은 실행하지 않습니다.",
        }

    try:
        await page.locator('a[href="/fac"]').click()
        await page.wait_for_url(FACILITY_URL, timeout=15_000)
        await page.locator(_COLUMNS).nth(0).locator(".selectFacility").first.wait_for(timeout=15_000)
        date_options = await _options(page, 0)
        date_names = [option["name"] for option in date_options]
        today = datetime.now(ZoneInfo("Asia/Seoul")).date()
        for index, option in enumerate(date_options):
            candidate = today + timedelta(days=index)
            match = re.fullmatch(r"(\d+)월\s*(\d+)\s*일\s*/\s*[월화수목금토일]", option["name"])
            if not match or (int(match[1]), int(match[2])) != (candidate.month, candidate.day):
                raise ScrapeFailedError("시설 날짜 목록을 현재 한국 날짜와 대조하지 못했습니다.")
            dates.append(candidate.isoformat())
        date = date or today.isoformat()
        if date not in dates:
            raise ValueError("date가 현재 웹 화면의 조회 가능한 날짜 범위 밖입니다.")
        if not await _choose(page, 0, date_options[dates.index(date)]["name"]):
            return await finish(unavailable={"date": date})
        selected["date"] = date
        if building is None:
            return await finish()
        async with page.expect_response(lambda response: urlsplit(response.url).netloc == "libadm.yonsei.ac.kr:444" and urlsplit(response.url).path.startswith("/facilities/groups/libraries/"), timeout=15_000) as groups_response:
            if not await _choose(page, 1, building):
                raise ScrapeFailedError("시설 도서관 선택을 적용하지 못했습니다.")
        if not (await groups_response.value).ok:
            raise ScrapeFailedError("시설 그룹 목록 요청이 실패했습니다.")
        await page.locator(_COLUMNS).nth(2).locator(".selectFacility").first.wait_for(timeout=15_000)
        selected["building"] = building
        if group is None:
            return await finish()
        path = "/facilities/infos/groups/" + date.replace("-", "") + "/"
        async with page.expect_response(lambda response: urlsplit(response.url).netloc == "libadm.yonsei.ac.kr:444" and urlsplit(response.url).path.startswith(path), timeout=15_000) as infos_response:
            if not await _choose(page, 2, group):
                raise ScrapeFailedError("시설 그룹 선택을 적용하지 못했습니다.")
        response = await infos_response.value
        if not response.ok:
            raise ScrapeFailedError("시설 목록 요청이 실패했습니다.")
        info = await response.json()
        if not isinstance(info, dict) or not isinstance(info.get("data"), list):
            raise ScrapeFailedError("시설 목록 응답 형식이 변경되었습니다.")
        await page.locator(_COLUMNS).nth(3).locator(".selectFacility").first.wait_for(timeout=15_000)
        selected["group"] = group
        if facility is None:
            return await finish()
        if not await _choose(page, 3, facility):
            return await finish(unavailable={"facility": facility})
        selected["facility"] = facility
        await page.locator(_COLUMNS).nth(4).locator(".selectFacility").first.wait_for(timeout=15_000)
        if duration_minutes is None:
            return await finish()
        durations = await _options(page, 4)
        labels = [option["name"] for option in durations if _duration(option["name"]) == duration_minutes]
        if len(labels) != 1:
            raise ValueError("duration_minutes가 현재 시설의 사용시간 선택지에 없습니다.")
        if not await _choose(page, 4, labels[0]):
            return await finish(unavailable={"duration_minutes": duration_minutes})
        selected["duration_minutes"] = duration_minutes
        graph = page.locator(".graphWrapper.active .graphView")
        await graph.wait_for(timeout=15_000)
        cells = await graph.evaluate("""element => Array.from(element.children, cell => ({
            label: cell.textContent.trim(), classes: Array.from(cell.classList).filter(value => !value.startsWith('ng-'))
        }))""")
        sources = [item for item in info["data"] if isinstance(item, dict) and item.get("name") == facility]
        if len(sources) != 1:
            raise ScrapeFailedError("선택된 시설과 원문 시설 ID를 대조하지 못했습니다.")
        return await finish(parse_timeline(cells, sources[0].get("rsrvUnit")))
    finally:
        await page.unroute("https://libadm.yonsei.ac.kr:444/**", readonly)
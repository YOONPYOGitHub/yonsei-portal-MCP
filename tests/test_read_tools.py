from __future__ import annotations

import json
from datetime import date
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
import httpx
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from yonsei_portal_mcp import cache, httpclient, server
from yonsei_portal_mcp.errors import ScrapeFailedError
from yonsei_portal_mcp.scrapers import erp, learnus, library, seats


def _timetable_row(**changes):
    return {
        "subjtnb": "TEST101", "corseDvclsNo": "01", "subjtNm": "Test",
        "syy": "2026", "smtDivNm": "2학기", "cdt": 3,
        "lctreTimeNm": "월2,3", **changes,
    }


@pytest.mark.parametrize("payload", [
    None, {}, [], {"dsSles450": None}, {"dsSles450": {}},
    {"dsSles450": ""}, {"dsSles450": [None]}, {"dsSles450": [{}]},
])
def test_timetable_missing_schema_is_not_empty(payload) -> None:
    with pytest.raises(ScrapeFailedError):
        erp._parse_timetable(payload)


@pytest.mark.parametrize("field", ["subjtnb", "corseDvclsNo", "subjtNm"])
def test_timetable_requires_row_identity(field) -> None:
    row = _timetable_row()
    del row[field]
    with pytest.raises(ScrapeFailedError):
        erp._parse_timetable({"dsSles450": [row]})


@pytest.mark.parametrize("field", ["subjtnb", "corseDvclsNo", "subjtNm"])
@pytest.mark.parametrize("value", [None, "", " "])
def test_timetable_requires_nonempty_row_identity(field, value) -> None:
    with pytest.raises(ScrapeFailedError):
        erp._parse_timetable({"dsSles450": [_timetable_row(**{field: value})]})


def test_timetable_explicit_empty_dataset_is_valid() -> None:
    assert erp._parse_timetable({"dsSles450": []}) == {
        "term": None, "count": 0, "total_credits": 0, "courses": [],
    }


def test_timetable_valid_row_preserves_identity_and_term() -> None:
    result = erp._parse_timetable({"dsSles450": [_timetable_row()]})
    assert result["term"] == "2026-2학기"
    assert result["count"] == 1 and result["total_credits"] == 3
    assert result["courses"][0]["course_code"] == "TEST101"
    assert result["courses"][0]["section"] == "01"
    assert result["courses"][0]["course_name"] == "Test"


@pytest.mark.parametrize("raw", [
    "월2-4", "월2(격주1회)", "월2(비대면)", "월2/3", "월2abc", "2월3",
    "월2 3", "월2,", "월0", "월100", "월02", "월２", "월2;화3",
])
def test_timetable_unsupported_time_preserves_raw_without_inventing_slots(raw) -> None:
    result = erp._parse_timetable({"dsSles450": [_timetable_row(lctreTimeNm=raw)]})
    assert result["courses"][0]["time_raw"] == raw
    assert result["courses"][0]["slots"] == []


@pytest.mark.parametrize(("raw", "expected"), [
    ("화2", [("화", "Tue", 2)]),
    ("화2,3", [("화", "Tue", 2), ("화", "Tue", 3)]),
    ("월2화3", [("월", "Mon", 2), ("화", "Tue", 3)]),
    ("월2,화3", [("월", "Mon", 2), ("화", "Tue", 3)]),
    (" 월 2, 3 화 4 ", [("월", "Mon", 2), ("월", "Mon", 3), ("화", "Tue", 4)]),
    ("일99", [("일", "Sun", 99)]),
    (None, []), ("", []), ("미정", []),
])
def test_timetable_time_supported_formats(raw, expected) -> None:
    assert erp._parse_time(raw) == [
        {"day": day, "day_en": day_en, "period": period}
        for day, day_en, period in expected
    ]


@pytest.mark.parametrize(("amounts", "expected"), [
    (["1.5"], 1.5), ([1.5], 1.5), (["3.0"], 3),
    (["1.5", 1.5, "3.0"], 6), (["0.1", "0.2"], 0.3),
    ([0, "0.0", 3], 3), (["1.25", "0.25"], 1.5),
])
def test_timetable_credit_totals_preserve_fractional_amounts(amounts, expected) -> None:
    result = erp._parse_timetable({"dsSles450": [_timetable_row(cdt=amount) for amount in amounts]})
    assert result["total_credits"] == expected
    assert [course["credits"] for course in result["courses"]] == amounts
    assert json.loads(json.dumps(result, allow_nan=False)) == result


@pytest.mark.parametrize("amount", [
    None, "", "unknown", "NaN", "Infinity", "-Infinity",
    float("nan"), float("inf"), float("-inf"), -1, "-0.5", True, {}, [],
])
def test_timetable_rejects_invalid_credit_amounts(amount) -> None:
    with pytest.raises(ScrapeFailedError):
        erp._parse_timetable({"dsSles450": [_timetable_row(cdt=amount)]})


def test_timetable_rejects_missing_credit_amount() -> None:
    row = _timetable_row()
    del row["cdt"]
    with pytest.raises(ScrapeFailedError):
        erp._parse_timetable({"dsSles450": [row]})


@pytest.mark.parametrize("amounts", [
    ["1e-400"], ["1.0000000000000000001"], ["1e30", "1.5"],
])
def test_timetable_rejects_credit_totals_that_would_lose_precision(amounts) -> None:
    with pytest.raises(ScrapeFailedError):
        erp._parse_timetable({"dsSles450": [_timetable_row(cdt=amount) for amount in amounts]})


def test_assignments_include_only_assignment_activities() -> None:
    materials = {
        "course_id": "123",
        "sections": [{
            "name": "Week 1", "week": 1,
            "activities": [
                {"type": "assign", "title": "Report", "url": "https://ys.learnus.org/mod/assign/view.php?id=1"},
                {"type": "vod", "title": "Lecture", "url": "https://ys.learnus.org/mod/vod/view.php?id=2"},
                {"type": "quiz", "title": "Quiz", "url": "https://ys.learnus.org/mod/quiz/view.php?id=3"},
            ],
        }],
    }
    result = learnus.assignments_from_materials(materials)
    assert result == {
        "course_id": "123", "count": 1,
        "assignments": [{
            "title": "Report", "url": "https://ys.learnus.org/mod/assign/view.php?id=1",
            "week": 1, "section": "Week 1",
        }],
    }
    assert len(materials["sections"][0]["activities"]) == 3


def test_no_assignment_is_a_valid_empty_result() -> None:
    assert learnus.assignments_from_materials({"course_id": "123", "sections": []}) == {
        "course_id": "123", "count": 0, "assignments": [],
    }


def test_missing_materials_schema_is_not_no_assignments() -> None:
    with pytest.raises(ScrapeFailedError):
        learnus.assignments_from_materials({"course_id": "123"})


@pytest.mark.parametrize("activity", [{}, None, {"type": None}, {"type": ""}, {"type": " "}, {"type": "assign"}, {"type": "assign", "title": "", "url": "https://ys.learnus.org/mod/assign/view.php?id=1"}, {"type": "assign", "title": "Report", "url": None}])
def test_malformed_assignment_activity_is_not_silently_skipped(activity) -> None:
    with pytest.raises(ScrapeFailedError):
        learnus.assignments_from_materials({
            "course_id": "123", "sections": [{"activities": [activity]}],
        })


@pytest.mark.asyncio
async def test_assignment_tool_reuses_materials_cache(monkeypatch) -> None:
    fetch = AsyncMock(return_value={"course_id": "123", "sections": []})
    monkeypatch.setattr(server, "get_lms_course_materials", fetch)
    result = await server.get_lms_assignments("123")
    assert result["count"] == 0
    fetch.assert_awaited_once_with("123")


@pytest.mark.asyncio
@pytest.mark.parametrize("course_id", ["", "1&redirect=bad", "../1", "abc"])
async def test_assignment_tool_rejects_invalid_ids(monkeypatch, course_id) -> None:
    fetch = AsyncMock()
    monkeypatch.setattr(server, "get_lms_course_materials", fetch)
    with pytest.raises(ValueError):
        await server.get_lms_assignments(course_id)
    fetch.assert_not_awaited()


@pytest.mark.parametrize("options", [
    {"page_number": 0}, {"page_number": 101}, {"page_number": True},
    {"page_number": 1.0}, {"page_number": "2"}, {"page_number": None},
    {"start_date": "2026-9-01"}, {"end_date": "2026-09-31"},
    {"start_date": "2025-02-29"}, {"start_date": "20260901"},
    {"start_date": ""}, {"end_date": " 2026-09-01"},
    {"start_date": 20260901}, {"end_date": True},
    {"start_date": "2026-09-02", "end_date": "2026-09-01"},
])
def test_history_options_reject_invalid_values(options) -> None:
    with pytest.raises(ValueError):
        library.validate_history_options(**options)


@pytest.mark.parametrize("options", [
    {}, {"page_number": 100}, {"start_date": "2024-02-29"},
    {"end_date": "2026-09-25"},
    {"start_date": "2026-09-01", "end_date": "2026-09-01", "page_number": 2},
])
def test_history_options_accept_defaults_and_valid_bounds(options) -> None:
    assert library.validate_history_options(**options) is None


def _history_document(kind="loan", *, current=1, links=(), total=None, dates=("", ""), rows=None, page_key="pn"):
    path = "/myloan/history" if kind == "loan" else "/myreserve/integratedhistory"
    if kind == "loan":
        headers = ["No.", "서명/저자", "소장처", "등록번호", "대출일", "반납일", "반납유형"]
        default_row = ["1", "Example", "Central", "BOOK1", "2026-09-01", "2026-09-10", "Normal"]
        form = f'<form id="form" method="get" action="{path}"><input name="pn" value="{current}"><input name="dtf" value="{dates[0]}"><input name="dtt" value="{dates[1]}"></form>'
    else:
        headers = ["No.", "서명/저자", "소장처", "예약순위", "예약일", "도착통보일", "예약상태"]
        default_row = ["1", "Example", "Central", "1", "2026-09-01", "", "Cancelled"]
        form = '<form id="myreserve" method="post" action="/myreserve/integratedCancel"><input name="cancelType" value="private-action">'
    rows = [default_row] if rows is None else rows
    body = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
    if not rows:
        body = '<tr><td colspan="7">등록된 자료가 없습니다.</td></tr>'
    count = "" if total is None else f'<div class="listInfo"><div class="listInfo1"><p class="totalCnt">총 <span>{total}</span> 건</p></div></div>'
    anchors = []
    for number in links:
        params = {page_key: number}
        if kind == "loan":
            params.update(dtf=dates[0], dtt=dates[1])
        anchors.append(f'<a href="{path}?{urlencode(params)}">{number}</a>')
    pager = f'<div class="paging"><strong>{current}</strong>{"".join(anchors)}</div>'
    table = '<div class="listTable"><table class="mobileTable"><thead><tr>' + "".join(f"<th>{header}</th>" for header in headers) + f'</tr></thead><tbody>{body}</tbody></table></div>'
    return count + form + table + pager + ("</form>" if kind == "reservation" else "")


def _history_page(documents, *, redirect=None):
    page = SimpleNamespace(url="about:blank", goto=AsyncMock(), wait_for_selector=AsyncMock(), content=AsyncMock())
    async def navigate(url, **kwargs):
        page.url = redirect or url
    page.goto.side_effect = navigate
    page.content.side_effect = documents
    return page


@pytest.mark.parametrize("dates", [("20240229", "20260925"), ("20260901", ""), ("", "20260925")])
def test_loan_history_compact_dates_are_python310_compatible(monkeypatch, dates) -> None:
    class Python310Date(date):
        @classmethod
        def fromisoformat(cls, value):
            if len(value) != 10:
                raise ValueError("Python 3.10 requires ISO YYYY-MM-DD")
            return super().fromisoformat(value)

    monkeypatch.setattr(library, "date", Python310Date)
    result = library.parse_loan_history(_history_document(dates=dates))
    assert result["date_filters_raw"] == {"from": dates[0], "to": dates[1]}


@pytest.mark.parametrize("kind", ["loan", "reservation"])
def test_history_metadata_is_scoped_to_displayed_table(kind) -> None:
    html = _history_document(kind, total=1)
    html += '<div class="listInfo"><p class="totalCnt">총 <span>99</span> 건</p></div><form id="branch"><table class="mobileTable"></table><div class="paging"><a href="/other?pn=2">2</a></div></form>'
    result = getattr(library, f"parse_{kind}_history")(html)
    assert result["page"] == 1 and result["count"] == result["total"] == 1
    assert result["has_next"] is False and result["next_page"] is None
    assert result["has_pagination"] is False
    assert result["scope"] == "displayed_page"
    assert "private-action" not in str(result)


@pytest.mark.parametrize("kind", ["loan", "reservation"])
def test_history_unknown_total_and_next_are_not_invented(kind) -> None:
    result = getattr(library, f"parse_{kind}_history")(_history_document(kind))
    assert "total" not in result and "has_next" not in result and "next_page" not in result


@pytest.mark.parametrize("kind", ["loan", "reservation"])
def test_history_exact_duplicate_rows_are_deduplicated(kind) -> None:
    html = _history_document(kind, total=1)
    start, end = html.index("<tbody>") + len("<tbody>"), html.index("</tbody>")
    html = html[:end] + html[start:end] + html[end:]
    result = getattr(library, f"parse_{kind}_history")(html)
    assert result["count"] == 1


@pytest.mark.parametrize("kind", ["loan", "reservation"])
@pytest.mark.parametrize("change", ["empty_title", "duplicate_header", "broken_count", "count_too_small", "empty_with_positive_count", "empty_body"])
def test_history_malformed_source_is_not_empty(kind, change) -> None:
    html = _history_document(kind, total=1, rows=[] if change == "empty_with_positive_count" else None)
    if change == "empty_title":
        html = html.replace("<td>Example</td>", "<td> </td>")
    elif change == "duplicate_header":
        html = html.replace("<th>No.</th>", "<th>서명/저자</th>")
    elif change == "broken_count":
        html = html.replace("<span>1</span>", "<span>unknown</span>")
    elif change == "count_too_small":
        html = html.replace("<span>1</span>", "<span>0</span>")
    elif change == "empty_body":
        html = html[:html.index("<tbody>")] + "<tbody></tbody></table>"
    with pytest.raises(ScrapeFailedError):
        getattr(library, f"parse_{kind}_history")(html)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["loan", "reservation"])
async def test_history_default_fetch_keeps_one_argument_and_one_navigation(kind) -> None:
    page = _history_page([_history_document(kind, total=1)])
    result = await getattr(library, f"fetch_{kind}_history")(page)
    assert result["page"] == 1 and result["source_url"] == page.url
    assert not urlsplit(page.url).query and page.goto.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("options", [{"start_date": "2026-01-01"}, {"end_date": "2026-09-25"}, {"start_date": "2026-01-01", "end_date": "2026-09-25"}])
async def test_loan_history_uses_verified_compact_dates(options) -> None:
    dates = (options.get("start_date", "").replace("-", ""), options.get("end_date", "").replace("-", ""))
    page = _history_page([_history_document(dates=dates, total=1)])
    result = await library.fetch_loan_history(page, **options)
    assert result["date_filters_raw"] == {"from": dates[0], "to": dates[1]}
    query = parse_qs(urlsplit(page.goto.await_args.args[0]).query)
    assert query == {name: [value] for name, value in zip(("dtf", "dtt"), dates) if value}
    assert page.goto.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("options", [
    {"start_date": "2026-09-01"}, {"end_date": "2026-09-25"},
    {"start_date": "2026-09-01", "end_date": "2026-09-25"},
])
async def test_loan_history_unconfirmed_date_only_query_is_not_reported_as_empty(options) -> None:
    html = _history_document(total=0, rows=[])
    for name in ("dtf", "dtt"):
        html = html.replace(f'name="{name}" value=""', f'name="{name}"')
    page = _history_page([html])
    with pytest.raises(ScrapeFailedError, match="did not confirm the requested date filters"):
        await library.fetch_loan_history(page, **options)
    assert page.goto.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("dates", [("", ""), ("20260102", "20260925"), ("20260101", "20260924"), ("invalid", "20260925")])
async def test_loan_history_rejects_ignored_or_changed_dates(dates) -> None:
    page = _history_page([_history_document(dates=dates)])
    with pytest.raises(ScrapeFailedError):
        await library.fetch_loan_history(page, start_date="2026-01-01", end_date="2026-09-25")


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,page_key", [("loan", "pn"), ("reservation", "page")])
async def test_history_follows_only_observed_page_link(kind, page_key) -> None:
    first = _history_document(kind, links=(2,), total=3, page_key=page_key)
    second = _history_document(kind, current=2, links=(1, 3), total=3, page_key=page_key).replace("Example", "Second example").replace("BOOK1", "BOOK2")
    page = _history_page([first, second])
    result = await getattr(library, f"fetch_{kind}_history")(page, page_number=2)
    assert page.goto.await_count == 2
    assert parse_qs(urlsplit(page.goto.await_args.args[0]).query)[page_key] == ["2"]
    assert result["page"] == 2 and result["has_next"] is True and result["next_page"] == 3
    assert result["count"] == 1 and result["total"] == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["loan", "reservation"])
async def test_history_rejects_unavailable_page_without_guessing_url(kind) -> None:
    page = _history_page([_history_document(kind, total=1)])
    with pytest.raises(ScrapeFailedError):
        await getattr(library, f"fetch_{kind}_history")(page, page_number=2)
    assert page.goto.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["loan", "reservation"])
@pytest.mark.parametrize("failure", ["clamped", "echoed_page_identical_rows", "empty", "missing_marker"])
async def test_history_rejects_unverified_or_silently_clamped_page(kind, failure) -> None:
    first = _history_document(kind, links=(2,), total=3)
    second = _history_document(kind, current=1 if failure == "clamped" else 2, total=3, rows=[] if failure == "empty" else None)
    if failure == "missing_marker":
        second = second.replace("<strong>2</strong>", "").replace('<input name="pn" value="2">', "").replace("Example", "Second example")
    page = _history_page([first, second])
    with pytest.raises(ScrapeFailedError):
        await getattr(library, f"fetch_{kind}_history")(page, page_number=2)


@pytest.mark.asyncio
async def test_loan_history_rejects_changed_filters_between_pages() -> None:
    first = _history_document(links=(2,), dates=("20260101", "20260925"))
    second = _history_document(current=2, dates=("", "")).replace("Example", "Second example")
    page = _history_page([first, second])
    with pytest.raises(ScrapeFailedError):
        await library.fetch_loan_history(page, page_number=2)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["loan", "reservation"])
@pytest.mark.parametrize("href", ["https://example.test/?pn=2", "/myreserve/integratedCancel?pn=2", "javascript:submitCancel(2)"])
async def test_history_never_follows_unsafe_pagination(kind, href) -> None:
    html = _history_document(kind).replace("</strong>", f'</strong><a href="{href}">2</a>')
    page = _history_page([html])
    with pytest.raises(ScrapeFailedError):
        await getattr(library, f"fetch_{kind}_history")(page, page_number=2)
    assert page.goto.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["loan", "reservation"])
async def test_history_fetch_validates_before_navigation(kind) -> None:
    page = _history_page([])
    with pytest.raises(ValueError):
        await getattr(library, f"fetch_{kind}_history")(page, page_number=101)
    page.goto.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["loan", "reservation"])
async def test_history_rejects_redirected_first_page_query(kind) -> None:
    path = "/myloan/history" if kind == "loan" else "/myreserve/integratedhistory"
    html = _history_document(kind).replace("<strong>1</strong>", "").replace('<input name="pn" value="1">', "")
    page = _history_page([html], redirect=library.LIBRARY_BASE + path + "?pn=2")
    with pytest.raises(ScrapeFailedError):
        await getattr(library, f"fetch_{kind}_history")(page)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["loan", "reservation"])
async def test_history_default_endpoint_verifies_first_page_next_link(kind) -> None:
    html = _history_document(kind, links=(2,)).replace("<strong>1</strong>", "").replace('<input name="pn" value="1">', "")
    result = await getattr(library, f"fetch_{kind}_history")(_history_page([html]))
    assert result["page"] == 1 and result["next_page"] == 2 and result["has_next"] is True


@pytest.mark.parametrize("kind", ["loan", "reservation"])
def test_history_rejects_total_conflicting_with_next_link(kind) -> None:
    with pytest.raises(ScrapeFailedError):
        getattr(library, f"parse_{kind}_history")(_history_document(kind, links=(2,), total=1))


@pytest.mark.parametrize("name", ["dtf", "dtt"])
def test_loan_history_omitted_value_attribute_is_a_verified_blank_default(name) -> None:
    html = _history_document().replace(f'name="{name}" value=""', f'name="{name}"')
    assert library.parse_loan_history(html)["date_filters_raw"] == {"from": "", "to": ""}


@pytest.mark.parametrize("name", ["dtf", "dtt"])
def test_loan_history_missing_source_date_control_is_not_a_blank_default(name) -> None:
    html = _history_document().replace(f'<input name="{name}" value="">', "")
    with pytest.raises(ScrapeFailedError):
        library.parse_loan_history(html)


@pytest.mark.asyncio
@pytest.mark.parametrize("options", [{"start_date": "2026-02-30"}, {"start_date": "2026-09-25", "end_date": "2026-01-01"}])
async def test_loan_history_invalid_dates_fail_before_io(options) -> None:
    page = _history_page([])
    with pytest.raises(ValueError):
        await library.fetch_loan_history(page, **options)
    page.goto.assert_not_awaited()


BOOK_HTML = """
<ul><li class="items" id="item_CATTOT123"><dl>
<dt class="title">서명</dt><dd class="title"><a href="/search/detail/CATTOT123?tracking=1">Example <span>AI</span></a></dd>
<dt class="title">저자</dt><dd class="info">Example Author</dd>
<dt class="title">출판사</dt><dd class="info">Example Press</dd>
<dt class="title">출판년</dt><dd class="info">2026</dd>
<dt class="title">자료유형</dt><dd class="type info">Book</dd>
<dd class="holdingInfo"><p class="location"><a>Central<span class="availableBtn">Available</span></a></p></dd>
</dl></li></ul>
"""

NOTICE_HTML = """
<table class="mobileTable"><thead><tr><th>제목</th><th>작성일</th></tr></thead><tbody>
<tr><td class="title"><a href="/bbs/content/1_123">Opening hours</a></td><td class="reportDate">2026-09-22</td><td class="writer">Private author</td></tr>
<tr><td class="title"><a href="/bbs/content/1_123">Opening hours</a></td><td class="reportDate">2026-09-22</td></tr>
</tbody></table>
"""


def _catalog_document(*, total=22, page=1, query="위키드", campus="all", search_field="all"):
    from html import escape
    params = {"st": "KWRD", "si": library._CATALOG_FIELDS[search_field], "q": query, "cpp": "10"}
    if campus != "all":
        params.update(lmt0=library._CATALOG_CAMPUSES[campus], lmtsn="000000000006", lmtst="OR")
    controls = ''.join(f'<input type="hidden" name="{key}" value="{escape(value, quote=True)}">' for key, value in params.items())
    start = (page - 1) * 10
    rows = ''.join(BOOK_HTML.replace("CATTOT123", f"CATTOT{number}") for number in range(start + 1, min(start + 10, total) + 1))
    page_count = (total + 9) // 10
    pager = ''.join(f'<span>{number}</span>' if number == page else f'<a href="?{escape(urlencode({**params, "pn": number}), quote=True)}">{number}</a>' for number in range(1, page_count + 1))
    return f'<p class="searchCnt">총 <strong>{total}</strong>건 중 <strong>{total}</strong>건 출력</p><form>{controls}</form><select name="cpp"><option value="10" selected>10</option></select><div class="paging"><span>{pager}</span></div>{rows}'


@pytest.mark.asyncio
async def test_catalog_continuation_does_not_skip_locally_limited_results(monkeypatch):
    async def fetch(url, *, params):
        return _catalog_document(page=params["pn"])
    monkeypatch.setattr(httpclient, "get_html", fetch)
    request = {"query": "위키드", "limit": 3}
    seen, pages = [], []
    while request is not None:
        result = await library.fetch_book_search(**request)
        assert result["total"] == 22 and result["total_pages"] == 3
        assert result["page_size"] == 10 and result["filters_verified"] is True
        assert result["has_next"] == (result["next_request"] is not None)
        seen.extend(item["url"].rsplit("/", 1)[-1] for item in result["results"])
        pages.append((result["page"], result["offset"]))
        request = result["next_request"]
        assert len(pages) <= 10
    assert seen == [f"CATTOT{number}" for number in range(1, 23)]
    assert pages == [(1, 0), (1, 3), (1, 6), (1, 9), (2, 0), (2, 3), (2, 6), (2, 9), (3, 0)]


@pytest.mark.asyncio
@pytest.mark.parametrize(("total", "page", "count", "next_page"), [(32, 3, 10, 4), (32, 4, 2, None), (0, 1, 0, None)])
async def test_catalog_metadata_reports_final_page_and_explicit_zero(monkeypatch, total, page, count, next_page):
    monkeypatch.setattr(httpclient, "get_html", AsyncMock(return_value=_catalog_document(total=total, page=page)))
    result = await library.fetch_book_search("위키드", page=page)
    assert result["count"] == count and result["total"] == total
    assert result["displayed_total"] == total and result["source_limited"] is False
    assert result["next_page"] == next_page and result["has_next"] == (next_page is not None)
    assert result["source_url"].startswith(library.LIBRARY_BASE) and result["fetched_at"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", [
    lambda html: html.replace('value="TOTAL"', 'value="1"'),
    lambda html: html.replace('value="위키드"', 'value="different"'),
    lambda html: html.replace('<span>1</span>', '<span>2</span>'),
    lambda html: html.replace('value="10" selected', 'value="20" selected'),
    lambda html: html.replace('<strong>22</strong>', '<strong>0</strong>'),
    lambda html: html.replace('<p class="searchCnt">', '<p class="changed">'),
    lambda html: html.replace('href="?', 'href="https://example.test/?'),
    lambda html: html.replace('href="?', 'data-disabled="?'),
    lambda html: html.replace('<form>', '<form><input type="hidden" name="q" value="conflicting">'),
    lambda html: html.replace('CATTOT2', 'CATTOT1'),
])
async def test_catalog_rejects_changed_conditions_or_missing_metadata(monkeypatch, mutation):
    monkeypatch.setattr(httpclient, "get_html", AsyncMock(return_value=mutation(_catalog_document())))
    with pytest.raises(ScrapeFailedError):
        await library.fetch_book_search("위키드")


@pytest.mark.asyncio
async def test_catalog_preserves_source_total_when_displayed_results_are_limited(monkeypatch):
    html = _catalog_document(total=22, page=3).replace("<strong>22</strong>", "<strong>32</strong>", 1)
    monkeypatch.setattr(httpclient, "get_html", AsyncMock(return_value=html))
    result = await library.fetch_book_search("위키드", page=3)
    assert result["total"] == 32 and result["displayed_total"] == 22
    assert result["source_limited"] is True and result["total_pages"] == 3
    assert result["has_next"] is False and result["next_request"] is None


def test_public_book_parser_maps_fields_and_canonical_url() -> None:
    assert library.parse_book_search(BOOK_HTML) == [{
        "title": "Example AI", "author": "Example Author", "publisher": "Example Press",
        "published_year": "2026", "material_type": "Book",
        "url": "https://library.yonsei.ac.kr/search/detail/CATTOT123",
        "catalog_id": "CATTOT123", "detail_supported": True,
        "holdings": [{"location": "Central", "status": "Available", "campus": None}],
    }]


@pytest.mark.parametrize(("location", "campus"), [("[신촌]도서관/2층/", "sinchon"), ("[국제]언더우드/", "international"), ("[미래]도서관/", "mirae"), ("Other", None)])
def test_catalog_holdings_preserve_raw_location_and_normalize_campus(location, campus):
    result = library.parse_book_search(BOOK_HTML.replace("Central", location).replace("CATTOT123", "OTHER123"))[0]
    assert result["holdings"][0]["location"] == location
    assert result["holdings"][0]["campus"] == campus
    assert result["catalog_id"] == "OTHER123" and result["detail_supported"] is False


@pytest.mark.asyncio
async def test_catalog_tool_forwards_and_caches_all_options(monkeypatch):
    fetch = AsyncMock(return_value={"results": []})
    monkeypatch.setattr(library, "fetch_book_search", fetch)
    cache.clear()
    try:
        for options in ({}, {"campus": "sinchon"}, {"search_field": "author"}, {"offset": 3}):
            arguments = {"query": "위키드", "page": 1, "limit": 3, "campus": "all", "search_field": "all", "offset": 0, **options}
            await server.search_library_books(**arguments)
            await server.search_library_books(**arguments)
            fetch.assert_awaited_with(**arguments)
        assert fetch.await_count == 4
        with pytest.raises(ValueError):
            await server.search_library_books("위키드", offset=-1)
        assert fetch.await_count == 4
        schema = next(tool.inputSchema for tool in await server.mcp.list_tools() if tool.name == "search_library_books")
        assert set(schema["properties"]) == {"query", "page", "limit", "campus", "search_field", "offset"}
    finally:
        cache.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize("offset", [-1, 10, 0.5, True])
async def test_catalog_rejects_invalid_offset_before_io(monkeypatch, offset):
    fetch = AsyncMock()
    monkeypatch.setattr(httpclient, "get_html", fetch)
    with pytest.raises(ValueError):
        await library.fetch_book_search("위키드", offset=offset)
    fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_catalog_page_bound_is_not_claimed_as_complete(monkeypatch):
    monkeypatch.setattr(httpclient, "get_html", AsyncMock(return_value=_catalog_document(total=1001, page=100)))
    result = await library.fetch_book_search("위키드", page=100)
    assert result["has_next"] is True and result["page_limit_reached"] is True
    assert result["next_request"] is None and result["next_page"] == 101


@pytest.mark.asyncio
async def test_catalog_rejects_ignored_campus_and_past_last_row(monkeypatch):
    monkeypatch.setattr(httpclient, "get_html", AsyncMock(return_value=_catalog_document(total=2)))
    with pytest.raises(ScrapeFailedError):
        await library.fetch_book_search("위키드", campus="sinchon")
    with pytest.raises(ValueError):
        await library.fetch_book_search("위키드", offset=2)


def test_library_notices_are_deduplicated_without_author() -> None:
    assert library.parse_library_notices(NOTICE_HTML) == [{
        "title": "Opening hours", "date": "2026-09-22",
        "url": "https://library.yonsei.ac.kr/bbs/content/1_123",
    }]


def test_malformed_notice_row_is_not_silently_skipped() -> None:
    changed = NOTICE_HTML.replace("</tbody>", '<tr><td class="title">Missing link</td><td class="reportDate">2026-09-22</td></tr></tbody>')
    with pytest.raises(ScrapeFailedError):
        library.parse_library_notices(changed)


def test_explicitly_deleted_notice_is_not_a_schema_error() -> None:
    changed = NOTICE_HTML.replace("</tbody>", '<tr><td class="title">관리자에 의해 삭제된 게시물입니다.</td><td class="reportDate">2026-09-22</td></tr></tbody>')
    assert library.parse_library_notices(changed) == library.parse_library_notices(NOTICE_HTML)


@pytest.mark.parametrize("parser_name", ["parse_book_search", "parse_library_notices"])
def test_library_changed_markup_is_not_empty_data(parser_name) -> None:
    with pytest.raises(ScrapeFailedError):
        getattr(library, parser_name)("<html><h1>Service unavailable</h1></html>")


def test_catalog_rejects_external_detail_link() -> None:
    changed = BOOK_HTML.replace("/search/detail/CATTOT123?tracking=1", "https://example.test/search/detail/123")
    with pytest.raises(ScrapeFailedError):
        library.parse_book_search(changed)


def test_catalog_explicit_zero_is_empty() -> None:
    assert library.parse_book_search('<p class="searchCnt">Total <strong>0</strong></p>') == []


@pytest.mark.asyncio
async def test_public_html_follows_same_origin_redirect(monkeypatch) -> None:
    requests = []

    def handle(request):
        requests.append(request)
        if len(requests) == 1:
            assert request.url.params["q"] == "AI & ML"
            return httpx.Response(302, headers={"Location": "/results"})
        return httpx.Response(200, text=BOOK_HTML)

    client_class = httpx.AsyncClient
    monkeypatch.setattr(httpclient.httpx, "AsyncClient", lambda **kwargs: client_class(transport=httpx.MockTransport(handle), **kwargs))
    result = await httpclient.get_html("https://library.yonsei.ac.kr/search/tot/result", params={"q": "AI & ML"})
    assert result == BOOK_HTML
    assert len(requests) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("location", ["https://example.test/", "http://library.yonsei.ac.kr/", "https://user@library.yonsei.ac.kr/"])
async def test_public_html_blocks_unsafe_redirect(monkeypatch, location) -> None:
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(302, headers={"Location": location})

    client_class = httpx.AsyncClient
    monkeypatch.setattr(httpclient.httpx, "AsyncClient", lambda **kwargs: client_class(transport=httpx.MockTransport(handle), **kwargs))
    with pytest.raises(httpx.HTTPError):
        await httpclient.get_html("https://library.yonsei.ac.kr/search/tot/result")
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_book_search_uses_public_http(monkeypatch) -> None:
    fetch = AsyncMock(return_value=_catalog_document(total=11, page=2, query="AI & ML"))
    monkeypatch.setattr(httpclient, "get_html", fetch, raising=False)
    result = await library.fetch_book_search("  AI & ML  ", page=2, limit=1)
    assert result["query"] == "AI & ML"
    assert result["page"] == 2 and result["count"] == 1
    fetch.assert_awaited_once_with(
        "https://library.yonsei.ac.kr/search/tot/result",
        params={"st": "KWRD", "si": "TOTAL", "q": "AI & ML", "pn": 2, "cpp": 10},
    )


@pytest.mark.asyncio
async def test_book_search_sends_verified_campus_and_title_filters(monkeypatch):
    fetch = AsyncMock(return_value=_catalog_document(campus="sinchon_international", search_field="title"))
    monkeypatch.setattr(httpclient, "get_html", fetch)
    await library.fetch_book_search("위키드", campus="sinchon_international", search_field="title")
    params = fetch.call_args.kwargs["params"]
    assert params["si"] == "1"
    assert params["lmt0"] == "YNLIB;GSISL;MUSEL;OTHER;UGSTL;YSLIB;ARCHL;BUSIL;KORCL;IOKSL;LAWSL;MULTL;MATHL;MUSIC;UML"
    assert params["lmtsn"] == "000000000006" and params["lmtst"] == "OR"


@pytest.mark.asyncio
@pytest.mark.parametrize("options", [{"campus": "unknown"}, {"search_field": "publisher"}])
async def test_book_search_rejects_unknown_filters_before_network(monkeypatch, options):
    fetch = AsyncMock()
    monkeypatch.setattr(httpclient, "get_html", fetch)
    with pytest.raises(ValueError):
        await library.fetch_book_search("위키드", **options)
    fetch.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(("query", "page", "limit"), [("", 1, 10), (" ", 1, 10), ("A" * 201, 1, 10), ("AI", 0, 10), ("AI", 101, 10), ("AI", 1, 0), ("AI", 1, 11)])
async def test_book_search_validates_before_network(monkeypatch, query, page, limit) -> None:
    fetch = AsyncMock()
    monkeypatch.setattr(httpclient, "get_html", fetch, raising=False)
    with pytest.raises(ValueError):
        await library.fetch_book_search(query, page=page, limit=limit)
    fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_library_notices_use_public_http(monkeypatch) -> None:
    fetch = AsyncMock(return_value=NOTICE_HTML)
    monkeypatch.setattr(httpclient, "get_html", fetch, raising=False)
    result = await library.fetch_library_notices(limit=1)
    assert result["count"] == 1
    fetch.assert_awaited_once_with("https://library.yonsei.ac.kr/bbs/list/1")


@pytest.mark.asyncio
async def test_library_http_failure_is_sanitized(monkeypatch) -> None:
    fetch = AsyncMock(side_effect=httpx.ConnectError("private-query"))
    monkeypatch.setattr(httpclient, "get_html", fetch, raising=False)
    with pytest.raises(ScrapeFailedError) as caught:
        await library.fetch_book_search("AI")
    assert "private-query" not in str(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "fetch_name", "arguments", "payload"),
    [
        ("search_library_books", "fetch_book_search", {"query": "AI"}, {"query": "AI", "page": 1, "count": 0, "results": []}),
        ("get_library_notices", "fetch_library_notices", {}, {"count": 0, "notices": []}),
    ],
)
async def test_public_tools_cache_without_login(monkeypatch, tool_name, fetch_name, arguments, payload) -> None:
    fetch = AsyncMock(return_value=payload)
    monkeypatch.setattr(library, fetch_name, fetch)

    def forbidden_login():
        raise AssertionError("Public tools must not start a browser session")

    monkeypatch.setattr(server, "get_library_session", forbidden_login)
    monkeypatch.setattr(server, "_account", forbidden_login)
    cache.clear()
    try:
        tool = getattr(server, tool_name)
        assert await tool(**arguments) == payload
        assert await tool(**arguments) == payload
        assert fetch.await_count == 1
    finally:
        cache.clear()


def _public_seat_payload():
    return {f"{building}_{kind}_{field}": 0 for building in ("center", "yonsei") for kind in ("general", "pc", "study", "notebook") for field in ("total", "use")}


@pytest.mark.parametrize("payload", [{}, None, {"error": "service unavailable"}])
def test_public_seats_reject_non_data(payload) -> None:
    with pytest.raises(ScrapeFailedError):
        seats._parse(payload)


@pytest.mark.parametrize("invalid", [None, -1, "loading", 1.5, True, 101])
def test_public_seats_reject_invalid_counts(invalid) -> None:
    payload = _public_seat_payload()
    payload.update(center_general_total=100, center_general_use=invalid)
    with pytest.raises(ScrapeFailedError):
        seats._parse(payload)


def test_public_seats_preserve_legitimate_zero() -> None:
    assert seats._parse(_public_seat_payload())["remaining"] == 0
    payload = _public_seat_payload()
    payload.update(center_general_total=100, center_general_use=30)
    assert seats._parse(payload)["remaining"] == 70


@pytest.mark.asyncio
async def test_new_read_tools_are_registered() -> None:
    names = {tool.name for tool in await server.mcp.list_tools()}
    assert {"get_lms_assignments", "search_library_books", "get_library_notices"} <= names


NOTICE_BODY_HTML = """
<div class="boardInfo"><p>2026-09-22</p><p class="boardInfoTitle">Opening hours</p><dl><dd>Private author</dd></dl></div>
<div class="boardContent">Please see the schedule.<img src="/image/schedule.png"></div>
"""


@pytest.mark.asyncio
async def test_library_notice_body_identifies_unread_images(monkeypatch) -> None:
    fetch = AsyncMock(return_value=NOTICE_BODY_HTML)
    monkeypatch.setattr(httpclient, "get_html", fetch)
    result = await library.fetch_library_notice("https://library.yonsei.ac.kr/bbs/content/1_123")
    assert result["title"] == "Opening hours"
    assert result["date"] == "2026-09-22"
    assert result["body"] == "Please see the schedule."
    assert result["author"] is None
    assert result["image_count"] == 1
    assert result["note"]
    assert "Private author" not in str(result)


@pytest.mark.asyncio
async def test_get_notice_routes_library_without_login(monkeypatch) -> None:
    payload = {"title": "Opening hours", "body": "Test"}
    fetch = AsyncMock(return_value=payload)
    monkeypatch.setattr(library, "fetch_library_notice", fetch, raising=False)
    monkeypatch.setattr(server, "_account", lambda: pytest.fail("Must not load credentials"))
    cache.clear()
    try:
        assert await server.get_notice("https://library.yonsei.ac.kr/bbs/content/1_123") == payload
        assert fetch.await_count == 1
    finally:
        cache.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize("url", [
    "http://ys.learnus.org/mod/ubboard/article.php?id=1",
    "https://ys.learnus.org.example.test/mod/ubboard/article.php?id=1",
    "https://example.test/?ys.learnus.org/mod/ubboard/article.php",
    "https://user@ys.learnus.org/mod/ubboard/article.php?id=1",
    "https://ys.learnus.org/login/logout.php",
])
async def test_notice_dispatch_rejects_unsafe_urls_before_login(monkeypatch, url) -> None:
    monkeypatch.setattr(server, "_account", lambda: pytest.fail("Must validate before login"))
    with pytest.raises(ValueError):
        await server.get_notice(url)


@pytest.mark.asyncio
async def test_library_notice_restricts_general_notice_path(monkeypatch) -> None:
    fetch = AsyncMock()
    monkeypatch.setattr(httpclient, "get_html", fetch)
    with pytest.raises(ValueError):
        await library.fetch_library_notice("https://library.yonsei.ac.kr/myloan/list")
    fetch.assert_not_awaited()


def test_scholarship_history_excludes_identity_fields() -> None:
    result = erp.parse_scholarship_history({"dsSscl121": [{
        "syy": "2026", "smtDivCd": "10", "scalNm": "Test scholarship",
        "scalApplcAmt": 100000, "sclarPymntDt": "20260901",
        "stuno": "private-student", "scalEdycNo": "private-record",
    }]})
    assert result == {"count": 1, "scholarships": [{
        "year": "2026", "term_code": "10", "name": "Test scholarship",
        "amount": 100000, "payment_date_raw": "20260901",
    }]}


@pytest.mark.parametrize("payload", [{}, {"dsSscl121": None}, {"dsSscl121": [{}]}, {"dsSscl121": [None]}])
def test_scholarship_missing_schema_is_not_empty(payload) -> None:
    with pytest.raises(ScrapeFailedError):
        erp.parse_scholarship_history(payload)


@pytest.mark.asyncio
async def test_scholarship_fetch_uses_verified_read_endpoint(monkeypatch) -> None:
    capture = AsyncMock(return_value={"scholarships": {"dsSscl121": []}})
    monkeypatch.setattr(erp, "_open_menu_and_capture", capture)
    assert await erp.fetch_scholarship_history(None) == {"count": 0, "scholarships": []}
    capture.assert_awaited_once_with(None, "장학", "장학수혜내역조회", {"scholarships": "findStdntRecfvDtlsList.do"})


def test_exam_schedule_distinguishes_unconfigured_period() -> None:
    result = erp.parse_exam_schedule({"dsSles450": []}, {"syy": "2026", "smtDivNm": "2학기"}, None, "중간시험")
    assert result["count"] == 0
    assert result["period_configured"] is False
    assert result["note"]
    assert result["term"] == "2026-2학기"
    assert result["exam_type"] == "중간시험"


def test_exam_schedule_maps_only_exam_fields() -> None:
    result = erp.parse_exam_schedule({"dsSles450": [{
        "subjtnb": "TEST101", "corseDvclsNo": "01", "subjtNm": "Test",
        "examDt": "20261020", "lessnLestmDivNm": "3", "lecrmNm": "Room A",
        "examDivNm": "중간시험", "cgprfNm": "Instructor", "private": "omit",
    }]}, {"syy": "2026", "smtDivNm": "2학기"}, {"beginDttm": "20260901000000"}, "중간시험")
    assert result["period_configured"] is True
    assert result["exams"] == [{
        "course_code": "TEST101", "section": "01", "course_name": "Test",
        "exam_date_raw": "20261020", "time_raw": "3", "room": "Room A",
        "exam_type": "중간시험", "professor": "Instructor",
    }]


@pytest.mark.parametrize("payload", [{}, {"dsSles450": None}, {"dsSles450": [{}]}])
def test_missing_exam_schema_is_not_empty(payload) -> None:
    with pytest.raises(ScrapeFailedError):
        erp.parse_exam_schedule(payload, {}, None, "중간시험")


def test_course_catalog_maps_verified_fields_and_limits_output() -> None:
    row = {"subjtnb": "TEST101", "subjtNm": "Test", "corseDvclsNo": "01", "syy": "2026", "smtDivCd": "20", "cgprfNm": "Instructor", "cdt": 3, "lctreTimeNm": "월2", "lecrmNm": "A", "estblDeprtNm": "Test department", "private": "omit"}
    result = erp.parse_course_catalog({"dsSles251": [row, row]}, "Test", 1, {"year": "2026"})
    assert result["count"] == 1 and result["fetched_count"] == 2
    assert result["truncated"] is True and result["filters"] == {"year": "2026"}
    assert result["courses"][0]["course_code"] == "TEST101"
    assert result["courses"][0]["credits"] == 3
    assert "private" not in result["courses"][0]


@pytest.mark.parametrize("payload", [{}, {"dsSles251": None}, {"dsSles251": [{}]}])
def test_course_catalog_missing_schema_is_not_empty(payload) -> None:
    with pytest.raises(ScrapeFailedError):
        erp.parse_course_catalog(payload, "Test", 10, {})


@pytest.mark.asyncio
@pytest.mark.parametrize(("keyword", "limit"), [("", 10), ("A", 10), ("A" * 101, 10), ("AI", 0), ("AI", 51)])
async def test_course_search_validates_before_browser(keyword, limit) -> None:
    with pytest.raises(ValueError):
        await erp.fetch_course_catalog(None, keyword, limit)


@pytest.mark.asyncio
async def test_course_search_selects_course_name_before_query(monkeypatch) -> None:
    monkeypatch.setattr(erp, "_open_menu_and_capture", AsyncMock())
    response = SimpleNamespace(ok=True, request=SimpleNamespace(post_data_json={
        "@d1#kwd": "자료", "@d1#searchGbn": "2", "@d1#kwdDivCd": "2",
    }), json=AsyncMock(return_value={"dsSles251": []}))

    @asynccontextmanager
    async def pending(*args, **kwargs):
        yield SimpleNamespace(value=AsyncMock(return_value=response)())

    page = MagicMock()
    page.expect_response = pending
    page.locator.return_value.last.focus = AsyncMock()
    page.locator.return_value.last.press = AsyncMock()
    page.locator.return_value.last.input_value = AsyncMock(return_value="교과목명")
    page.locator.return_value.nth.return_value.fill = AsyncMock()
    page.get_by_text.return_value.last.click = AsyncMock()
    result = await erp.fetch_course_catalog(page, "자료")
    page.locator.return_value.last.press.assert_any_await("ArrowDown")
    assert result["filters"]["keyword_type"] == "2"


SEAT_HTML = """<table class="seatTbl"><thead><tr>
<th>실명</th><th>전체좌석</th><th>사용중</th><th>이용가능석</th><th>운영시간</th><th>이용률</th><th>추가정보안내</th>
</tr></thead><tbody>
<tr><td>Room A 배정불가</td><td>100(110)</td><td>20</td><td>80</td><td>06:00 ~ 22:00</td><td>20%</td><td></td></tr>
<tr><td>Room B 배정가능</td><td>50</td><td>10</td><td>40</td><td>09:00 ~ 21:00</td><td>20%</td><td></td></tr>
</tbody></table>"""


def test_seats_distinguish_displayed_remaining_from_assignable_seats() -> None:
    result = library.parse_seat_rooms(SEAT_HTML)
    assert result["count"] == 2
    assert result["total"] == 150 and result["in_use"] == 30
    assert result["available"] == 120
    assert result["assignable_available"] == 40
    assert result["unassignable_rooms"] == 1
    assert result["availability_note"]


@pytest.mark.parametrize("html", ["<html>Login</html>", SEAT_HTML.replace("이용가능석", "Changed"), SEAT_HTML.replace("<td>80</td>", "<td>-</td>"), SEAT_HTML.replace("<td>80</td>", "<td>800</td>"), SEAT_HTML.replace("<td>100(110)</td>", "<td>loading</td>")])
def test_seat_source_errors_are_not_zero_availability(html) -> None:
    with pytest.raises(ScrapeFailedError):
        library.parse_seat_rooms(html)


def test_seat_parser_uses_headers_not_position() -> None:
    html = SEAT_HTML.replace("<th>사용중</th><th>이용가능석</th>", "<th>이용가능석</th><th>사용중</th>")
    html = html.replace("<td>20</td><td>80</td>", "<td>80</td><td>20</td>").replace("<td>10</td><td>40</td>", "<td>40</td><td>10</td>")
    assert library.parse_seat_rooms(html)["available"] == 120


def test_seat_parser_ignores_only_empty_full_width_separator() -> None:
    html = SEAT_HTML.replace("</tbody>", '<tr><td colspan="7"></td></tr></tbody>')
    assert library.parse_seat_rooms(html)["count"] == 2


def test_seat_source_total_is_not_counted_as_another_room() -> None:
    html = SEAT_HTML.replace("</tbody>", '<tr><td>합계</td><td>150(160)</td><td>30</td><td>120</td><td></td><td>20%</td><td></td></tr></tbody>')
    result = library.parse_seat_rooms(html)
    assert result["count"] == 2 and result["total"] == 150 and result["available"] == 120
    assert result["source_totals_match"] is True
    with pytest.raises(ScrapeFailedError):
        library.parse_seat_rooms(html.replace('<td>150(160)</td>', '<td>151(160)</td>'))


def test_live_open_and_full_seat_labels_are_not_schema_failures() -> None:
    html = SEAT_HTML.replace("Room A 배정불가", "Room A 좌석배정").replace("Room B 배정가능", "Room B FULL").replace("<td>10</td><td>40</td>", "<td>50</td><td>0</td>")
    result = library.parse_seat_rooms(html)
    assert result["rooms"][0]["name"] == "Room A"
    assert result["rooms"][0]["assignable"] is True
    assert result["rooms"][1]["name"] == "Room B"
    assert result["rooms"][1]["assignable"] is False
    assert result["assignable_available"] == 80
    assert result["unassignable_rooms"] == 1


RESERVATION_HTML = """<table class="mobileTable"><thead><tr>
<th></th><th>No.</th><th>서명/저자</th><th>소장처</th><th>예약순위</th><th>예약일</th><th>도착 통보일</th><th>예약상태</th>
</tr></thead><tbody><tr><td><input value="private-id"></td><td>1</td><td>Example Book</td><td>Central</td><td>2</td><td>2026-09-20</td><td></td><td>Waiting</td></tr></tbody></table>"""


def test_book_reservations_map_columns_not_action_fields() -> None:
    result = library.parse_my_reservations(RESERVATION_HTML)
    assert result == {"count": 1, "reservations": [{
        "title_author": "Example Book", "location": "Central", "queue_position": "2",
        "reservation_date": "2026-09-20", "notification_date": "", "status": "Waiting",
    }]}


@pytest.mark.parametrize("html", ["<h1>Login</h1>", RESERVATION_HTML.replace("예약순위", "Unknown"), RESERVATION_HTML.replace("<td>2</td>", "")])
def test_book_reservation_schema_errors_are_not_empty(html) -> None:
    with pytest.raises(ScrapeFailedError):
        library.parse_my_reservations(html)


def test_loan_empty_requires_explicit_marker_and_headers() -> None:
    headers = "".join(f"<th>{name}</th>" for name in library._LOAN_FIELD_MAP)
    html = f'<table class="mobileTable"><thead><tr>{headers}</tr></thead><tbody><tr><td colspan="7">결과가 없습니다.</td></tr></tbody></table>'
    assert library.parse_my_loans(html) == {"count": 0, "loans": []}
    with pytest.raises(ScrapeFailedError):
        library.parse_my_loans("<html>Login</html>")
    with pytest.raises(ScrapeFailedError):
        library.parse_my_loans(html.replace("결과가 없습니다.", "Loading"))


def test_loan_nonempty_fields_are_mapped_exactly() -> None:
    headers = "".join(f"<th>{name}</th>" for name in library._LOAN_FIELD_MAP)
    values = ["Example Book", "Central", "BOOK-1", "2026-09-01", "2026-09-30", "0", "1"]
    cells = "".join(f"<td>{value}</td>" for value in values)
    html = f'<table class="mobileTable"><thead><tr>{headers}</tr></thead><tbody><tr>{cells}</tr></tbody></table>'
    result = library.parse_my_loans(html)
    assert result["loans"][0] == dict(zip(library._LOAN_FIELD_MAP.values(), values))


HISTORY_HTML = """<table class="table-coursemos"><thead><tr><th>연도</th><th>학기</th><th>강좌명</th></tr></thead>
<tbody><tr><td>2025</td><td>2학기</td><td><a href="https://ys.learnus.org/course/view.php?id=123">Example</a></td></tr></tbody></table>"""


def test_course_history_uses_verified_table() -> None:
    result = learnus.parse_course_history(HISTORY_HTML)
    assert result["courses"] == [{"year": "2025", "semester": "2학기", "name": "Example", "id": "123", "url": "https://ys.learnus.org/course/view.php?id=123"}]
    assert result["count"] == 1


def test_course_history_explicit_empty_not_login_page() -> None:
    html = HISTORY_HTML.replace('<td>2025</td><td>2학기</td><td><a href="https://ys.learnus.org/course/view.php?id=123">Example</a></td>', '<td colspan="3">참여중인 강좌가 없습니다.</td>')
    assert learnus.parse_course_history(html)["count"] == 0
    with pytest.raises(ScrapeFailedError):
        learnus.parse_course_history("<h1>Login</h1>")
    with pytest.raises(ScrapeFailedError):
        learnus.parse_course_history(HISTORY_HTML.replace("ys.learnus.org", "example.test"))


@pytest.mark.asyncio
@pytest.mark.parametrize(("year", "semester"), [(1900, "all"), (9999, "all"), (2026, "bad")])
async def test_course_history_input_validation(year, semester) -> None:
    with pytest.raises(ValueError):
        await learnus.fetch_course_history(None, year, semester)


@pytest.mark.asyncio
@pytest.mark.parametrize(("tool_name", "fetch_name", "owner", "session_name", "arguments", "payload"), [
    ("get_scholarship_history", "fetch_scholarship_history", erp, "get_erp_session", {}, {"count": 0, "scholarships": []}),
    ("get_exam_schedule", "fetch_exam_schedule", erp, "get_erp_session", {}, {"count": 0, "exams": []}),
    ("search_courses", "fetch_course_catalog", erp, "get_erp_session", {"keyword": "인공지능", "limit": 3}, {"count": 0, "courses": []}),
    ("get_lms_course_history", "fetch_course_history", learnus, "get_session", {"year": 2025}, {"count": 0, "courses": []}),
    ("get_my_reservations", "fetch_my_reservations", library, "get_library_session", {}, {"count": 0, "reservations": []}),
])
async def test_new_authenticated_tools_reuse_account_cache(monkeypatch, tool_name, fetch_name, owner, session_name, arguments, payload) -> None:
    fetch = AsyncMock(return_value=payload)
    monkeypatch.setattr(owner, fetch_name, fetch)
    monkeypatch.setattr(server, "_account", lambda: "test-account")
    async def run(action):
        return await action(None)
    monkeypatch.setattr(server, session_name, lambda: SimpleNamespace(run=run))
    cache.clear()
    try:
        tool = getattr(server, tool_name)
        assert await tool(**arguments) == payload
        assert await tool(**arguments) == payload
        assert fetch.await_count == 1
        assert tool_name in {tool.name for tool in await server.mcp.list_tools()}
    finally:
        cache.clear()


ASSIGNMENT_STATUS_HTML = """<body id="page-mod-assign-view"><h2>Example assignment</h2>
<div class="submissionstatustable"><table>
<tr><td>제출 여부</td><td>제출 안 함</td></tr>
<tr><td>채점 상황</td><td class="submissiongraded">채점됨</td></tr>
<tr><td>종료 일시</td><td>2026-09-25 23:59</td></tr>
<tr><td>마감까지 남은 기한</td><td class="overdue">마감 경과</td></tr>
<tr><td>최종 수정 일시</td><td>-</td></tr>
<tr><td>제출물 설명</td><td>Private submission content</td></tr>
</table></div></body>"""


def test_assignment_status_does_not_infer_submission_from_grade() -> None:
    result = learnus.parse_assignment_status(ASSIGNMENT_STATUS_HTML, "123")
    assert result["submission_status"] == "not_submitted"
    assert result["submission_status_raw"] == "제출 안 함"
    assert result["grading_status_raw"] == "채점됨"
    assert result["due"] == "2026-09-25T23:59:00+09:00"
    assert result["overdue_marker"] is True
    assert "Private submission" not in str(result)


@pytest.mark.parametrize(("status", "expected"), [("제출 완료", "submitted"), ("초안(미제출)", "draft"), ("새로운 상태", "unknown")])
def test_assignment_submission_states_remain_explicit(status, expected) -> None:
    result = learnus.parse_assignment_status(ASSIGNMENT_STATUS_HTML.replace("제출 안 함", status), "123")
    assert result["submission_status"] == expected


def test_unknown_assignment_due_is_not_guessed() -> None:
    result = learnus.parse_assignment_status(ASSIGNMENT_STATUS_HTML.replace("2026-09-25 23:59", "미정"), "123")
    assert result["due"] is None and result["due_raw"] == "미정"
    with pytest.raises(ScrapeFailedError):
        learnus.parse_assignment_status("<h2>Login</h2>", "123")


@pytest.mark.asyncio
@pytest.mark.parametrize("assignment_id", ["", "../1", "1&action=submit", "123abc"])
async def test_assignment_status_rejects_invalid_id(assignment_id) -> None:
    with pytest.raises(ValueError):
        await learnus.fetch_assignment_status(None, assignment_id)


GRADE_DATA = {
    "dsSgra100": [
        {"syy": "2025", "smtDivCd": "20", "subjtnb": "TEST101", "subjtNm": "Example", "cmpsjCdt": "3", "gradeDivCdView": "A+", "cgprfNm": "Teacher"},
        {"syy": "2026", "smtDivCd": "10", "subjtnb": "TEST102", "subjtNm": "Other", "cmpsjCdt": "2", "gradeDivCdView": "B", "cgprfNm": "Teacher"},
    ],
    "dsSgra120": [{"syy": "2025", "smtDivCd": "20", "acqsCdt": 3}, {"syy": "2026", "smtDivCd": "10", "acqsCdt": 2}],
    "dsStdntInfo": [{"acqsCdt": 5, "bwa": 0, "stdntNm": "private-name", "stuno": "private-id"}],
}


def test_grades_use_actual_course_dataset_and_credit_field() -> None:
    result = erp._parse_grades(GRADE_DATA)
    assert result["count"] == 2
    assert result["courses"][0]["course_code"] == "TEST101"
    assert result["courses"][0]["credits"] == "3"
    assert result["courses"][0]["grade"] == "A+"
    assert result["courses"][0]["year"] == "2025"
    assert result["summary"]["gpa"] == 0
    assert "private-name" not in str(result)
    assert "private-id" not in str(result)


def test_grade_filters_do_not_relabel_cumulative_summary() -> None:
    result = erp._parse_grades(GRADE_DATA, year=2025, term_code="20")
    assert result["count"] == 1
    assert result["courses"][0]["course_code"] == "TEST101"
    assert len(result["terms"]) == 1
    assert result["summary"]["total_earned_credits"] == 5
    assert result["summary_scope"] == "all_terms"
    assert result["filters"] == {"year": 2025, "term_code": "20"}
    assert erp._parse_grades(GRADE_DATA, year=2024)["count"] == 0


@pytest.mark.parametrize("data", [{}, {"dsSgra100": None, "dsSgra120": []}, {"dsSgra100": [{}], "dsSgra120": []}])
def test_grade_schema_errors_are_not_new_student(data) -> None:
    with pytest.raises(ScrapeFailedError):
        erp._parse_grades(data)


@pytest.mark.asyncio
async def test_exam_filter_selects_final_before_inquiry(monkeypatch) -> None:
    monkeypatch.setattr(erp, "_open_menu_and_capture", AsyncMock(return_value={
        "term": {"dmSyySmt": {"syy": "2026", "smtDivNm": "2학기"}},
        "period": {"dmUnvfcSyySmt": None},
    }))
    response = SimpleNamespace(ok=True, json=AsyncMock(return_value={"dsSles450": []}))

    @asynccontextmanager
    async def pending(*args, **kwargs):
        yield SimpleNamespace(value=AsyncMock(return_value=response)())

    page = MagicMock()
    page.expect_response = pending
    combo = page.locator.return_value.last
    combo.focus = AsyncMock()
    combo.press = AsyncMock()
    combo.input_value = AsyncMock(side_effect=["중간", "기말"])
    page.get_by_text.return_value.last.click = AsyncMock()
    result = await erp.fetch_exam_schedule(page, exam_type="final")
    combo.press.assert_any_await("ArrowDown")
    assert result["exam_type"] == "기말"


@pytest.mark.asyncio
async def test_exam_filter_rejects_unsupported_kind_before_browser() -> None:
    with pytest.raises(ValueError):
        await erp.fetch_exam_schedule(None, exam_type="invalid")


@pytest.mark.asyncio
async def test_assignment_detail_tool_uses_account_cache(monkeypatch) -> None:
    fetch = AsyncMock(return_value={"assignment_id": "123", "submission_status": "draft"})
    monkeypatch.setattr(learnus, "fetch_assignment_status", fetch)
    monkeypatch.setattr(server, "_account", lambda: "test-account")
    async def run(action):
        return await action(None)
    monkeypatch.setattr(server, "get_session", lambda: SimpleNamespace(run=run))
    cache.clear()
    try:
        assert (await server.get_lms_assignment_status("123"))["submission_status"] == "draft"
        await server.get_lms_assignment_status("123")
        fetch.assert_awaited_once_with(None, "123")
    finally:
        cache.clear()


@pytest.mark.asyncio
async def test_schedule_composes_existing_tools_without_optional_sources(monkeypatch) -> None:
    monkeypatch.setattr(server, "get_lms_deadlines", AsyncMock(return_value=[]))
    timetable = {"courses": [{"time_raw": "월2", "slots": [{"day": "월", "period": 2}]}]}
    monkeypatch.setattr(server, "get_my_timetable", AsyncMock(return_value=timetable))
    loans = AsyncMock()
    exams = AsyncMock()
    monkeypatch.setattr(server, "get_my_loans", loans)
    monkeypatch.setattr(server, "get_exam_schedule", exams)
    result = await server.get_my_schedule(days=7, include_loans=False)
    assert result["weekly_timetable"] == timetable
    assert result["exams"] is None
    assert result["count"] == 0
    loans.assert_not_awaited()
    exams.assert_not_awaited()


@pytest.mark.asyncio
async def test_profile_default_excludes_pii_without_mutating_cache(monkeypatch) -> None:
    payload = {"name": "Test Person", "student_no": "private-id", "department": "Test", "terms": []}
    monkeypatch.setattr(server, "_account", lambda: "test-account")
    monkeypatch.setattr(server.cache, "cached", AsyncMock(return_value=payload))
    result = await server.get_student_profile()
    assert "name" not in result and "student_no" not in result
    assert result["pii_included"] is False
    included = await server.get_student_profile(include_pii=True)
    assert included["name"] == "Test Person"
    assert included["pii_included"] is True
    assert payload["name"] == "Test Person"


@pytest.mark.asyncio
async def test_grade_and_exam_tool_filters_are_forwarded(monkeypatch) -> None:
    async def run(action):
        return await action(None)
    monkeypatch.setattr(server, "get_erp_session", lambda: SimpleNamespace(run=run))
    monkeypatch.setattr(server, "_account", lambda: "test-account")
    grades = AsyncMock(return_value={"count": 0})
    exams = AsyncMock(return_value={"count": 0})
    monkeypatch.setattr(erp, "fetch_grades", grades)
    monkeypatch.setattr(erp, "fetch_exam_schedule", exams)
    cache.clear()
    try:
        await server.get_grades(year=2026, term_code="10")
        await server.get_grades(year=2026, term_code="20")
        assert grades.await_count == 2
        grades.assert_any_await(None, 2026, "10")
        await server.get_exam_schedule(exam_type="final")
        exams.assert_awaited_once_with(None, "final")
    finally:
        cache.clear()


@pytest.mark.asyncio
async def test_catalog_filter_selection_checks_final_value() -> None:
    combo = SimpleNamespace(input_value=AsyncMock(side_effect=["겨울학기", "1학기"]), focus=AsyncMock(), press=AsyncMock())
    await erp.select_catalog_option(combo, ["1학기", "여름학기", "2학기", "겨울학기"], "1학기")
    assert combo.press.await_count == 4
    combo.press.assert_any_await("ArrowUp")
    failed = SimpleNamespace(input_value=AsyncMock(side_effect=["2학기", "2학기"]), focus=AsyncMock(), press=AsyncMock())
    with pytest.raises(ScrapeFailedError):
        await erp.select_catalog_option(failed, ["1학기", "2학기"], "1학기")


@pytest.mark.asyncio
@pytest.mark.parametrize("filters", [{"year": 1900}, {"year": 9999}, {"term_code": "invalid"}, {"campus_code": "s999"}])
async def test_catalog_optional_filters_validate_before_browser(filters) -> None:
    with pytest.raises(ValueError):
        await erp.fetch_course_catalog(None, "인공지능", **filters)


def test_catalog_results_apply_explicit_filters_before_limit() -> None:
    rows = [
        {"subjtnb": "A", "subjtNm": "AI old", "corseDvclsNo": "01", "syy": "2025", "smtDivCd": "10", "campsBusnsCd": "s1"},
        {"subjtnb": "B", "subjtNm": "AI new", "corseDvclsNo": "01", "syy": "2026", "smtDivCd": "20", "campsBusnsCd": "s3"},
    ]
    result = erp.parse_course_catalog({"dsSles251": rows}, "AI", 1, {}, requested_filters={"year": 2026, "term_code": "20", "campus_code": "s3"})
    assert result["count"] == 1 and result["courses"][0]["course_code"] == "B"
    assert result["courses"][0]["campus_code"] == "s3"
    assert result["fetched_count"] == 2
    assert result["matching_count"] == 1


@pytest.mark.asyncio
async def test_catalog_year_uses_keyboard_and_waits_for_matching_response(monkeypatch) -> None:
    monkeypatch.setattr(erp, "_open_menu_and_capture", AsyncMock())
    page = MagicMock()
    field = page.locator.return_value
    field.input_value = AsyncMock(return_value="2026")
    field.click = AsyncMock()
    field.press = AsyncMock()
    field.press_sequentially = AsyncMock()
    field.fill = AsyncMock()
    field.last.focus = AsyncMock()
    field.last.press = AsyncMock()
    field.last.input_value = AsyncMock(return_value="교과목명")
    field.nth.return_value.fill = AsyncMock()
    page.get_by_text.return_value.last.click = AsyncMock()
    predicates = []
    response = SimpleNamespace(ok=True, finished=AsyncMock(), request=SimpleNamespace(post_data_json={"@d1#kwd": "AI", "@d1#searchGbn": "2", "@d1#kwdDivCd": "2", "@d1#syy": "2025"}), json=AsyncMock(return_value={"dsSles251": []}))

    @asynccontextmanager
    async def pending(predicate, **kwargs):
        predicates.append(predicate)
        yield SimpleNamespace(value=AsyncMock(return_value=response)())

    page.expect_response = pending
    await erp.fetch_course_catalog(page, "AI", year=2025)
    field.press_sequentially.assert_awaited_once_with("2025")
    field.fill.assert_not_awaited()
    old = SimpleNamespace(url="https://underwood1.yonsei.ac.kr/sch/sles/SlescsCtr/findSchSlesHandbList.do", request=SimpleNamespace(post_data_json={"@d1#syy": "2026"}))
    assert predicates[0](old) is False


ACADEMIC_HTML = '''<input id="year" value="2026"><input id="half" value="second">
<div id="timeTableList"><div class="box-sch"><div class="num"><h3><span>10월</span><span>October</span></h3></div>
<div class="desc"><dl><dt>27 (Tue) ~ 02 (Mon)</dt><dd>Example application period</dd></dl></div></div>
<div class="box-sch"><div class="num"><h3><span>1월</span><span>January</span></h3></div>
<div class="desc"><dl><dt>01 (Fri)</dt><dd>New year</dd></dl></div></div></div>'''


def test_academic_calendar_keeps_cross_month_raw_range() -> None:
    from yonsei_portal_mcp.scrapers import academic

    result = academic.parse_calendar(ACADEMIC_HTML)
    assert result["academic_year"] == 2026 and result["semester"] == "second"
    assert result["months"][0]["month"] == 10
    assert result["months"][0]["events"][0]["date_raw"] == "27 (Tue) ~ 02 (Mon)"
    assert result["months"][1]["display_year"] == 2027
    assert result["count"] == 2
    assert result["date_note"]


def test_academic_calendar_normalizes_rendering_whitespace_only() -> None:
    from yonsei_portal_mcp.scrapers import academic

    html = ACADEMIC_HTML.replace("27 (Tue) ~ 02 (Mon)", "27\n\t(Tue) \n ~ 02\t(Mon)")
    assert academic.parse_calendar(html)["months"][0]["events"][0]["date_raw"] == "27 (Tue) ~ 02 (Mon)"


@pytest.mark.parametrize("html", ["<h1>Error</h1>", ACADEMIC_HTML.replace('<input id="year" value="2026">', ''), ACADEMIC_HTML.replace('<dt>01 (Fri)</dt>', ''), ACADEMIC_HTML.replace('>1월<', '>99월<')])
def test_academic_calendar_requires_source_schema(html) -> None:
    from yonsei_portal_mcp.scrapers import academic

    with pytest.raises(ScrapeFailedError):
        academic.parse_calendar(html)


@pytest.mark.asyncio
async def test_catalog_tool_filter_cache_is_separate(monkeypatch) -> None:
    async def run(action):
        return await action(None)
    monkeypatch.setattr(server, "get_erp_session", lambda: SimpleNamespace(run=run))
    monkeypatch.setattr(server, "_account", lambda: "test-account")
    fetch = AsyncMock(return_value={"count": 0, "courses": []})
    monkeypatch.setattr(erp, "fetch_course_catalog", fetch)
    cache.clear()
    try:
        await server.search_courses("AI", year=2026, term_code="20", campus_code="s1")
        await server.search_courses("AI", year=2026, term_code="20", campus_code="s3")
        await server.search_courses("AI", year=2026, term_code="20", campus_code="s3")
        assert fetch.await_count == 2
        fetch.assert_any_await(None, "AI", 20, year=2026, term_code="20", campus_code="s3")
    finally:
        cache.clear()


@pytest.mark.asyncio
async def test_academic_calendar_tool_needs_no_account(monkeypatch) -> None:
    from yonsei_portal_mcp.scrapers import academic
    fetch = AsyncMock(return_value={"months": [], "count": 0})
    monkeypatch.setattr(academic, "fetch_calendar", fetch)
    monkeypatch.setattr(server, "_account", lambda: pytest.fail("Public calendar must not load credentials"))
    cache.clear()
    try:
        assert (await server.get_academic_calendar())["count"] == 0
        await server.get_academic_calendar()
        fetch.assert_awaited_once()
    finally:
        cache.clear()


@pytest.mark.asyncio
async def test_timetable_export_passes_only_explicit_configuration(monkeypatch) -> None:
    timetable = {"courses": [{"course_code": "TEST", "course_name": "Course", "section": "01", "time_raw": "화2", "slots": [{"day_en": "Tue", "period": 2}]}]}
    fetch = AsyncMock(return_value=timetable)
    monkeypatch.setattr(server, "get_my_timetable", fetch)
    result = await server.export_timetable_ics("2026-09-01", "2026-12-21", {"2": {"start": "10:00", "end": "10:50"}}, exclude_dates=["2026-09-22"])
    assert "RRULE:FREQ=WEEKLY" in result and "EXDATE:20260922T010000Z" in result
    fetch.assert_awaited_once()
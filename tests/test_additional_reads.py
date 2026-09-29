from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from yonsei_portal_mcp.errors import ScrapeFailedError
from yonsei_portal_mcp.scrapers import learnus, library


@pytest.mark.parametrize(("raw", "expected"), [
    ("2026-9-2", "2026-09-02"),
    ("2026. 9. 2", "2026-09-02"),
    ("2026/9/2", "2026-09-02"),
    ("2024-02-29", "2024-02-29"),
    ("2026년 9월 2일", "2026-09-02"),
    ("2026-02-29", None),
    ("2026.13.01", None),
    ("2026/04/31", None),
    ("2026년 2월 30일", None),
    ("2026-09/22", None),
    ("12026-09-22", None),
    ("2026-09-222", None),
    (None, None),
])
def test_notice_date_normalization(raw, expected):
    assert learnus._norm_date(raw) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", ["2026-9-2", "2026. 9. 2", "2026/9/2"])
async def test_notice_body_preserves_numeric_date(raw):
    page = SimpleNamespace(
        goto=AsyncMock(), wait_for_timeout=AsyncMock(),
        evaluate=AsyncMock(return_value={"date": raw}), wait_for_function=AsyncMock(),
        url=learnus.LEARNUS_HOME + "mod/ubboard/article.php?id=123",
    )
    result = await learnus.fetch_notice_body(page, learnus.LEARNUS_HOME + "mod/ubboard/article.php?id=123")
    assert result["date"] == "2026-09-02"


@pytest.fixture
def assignment_status_html():
    from test_read_tools import ASSIGNMENT_STATUS_HTML
    return ASSIGNMENT_STATUS_HTML


@pytest.mark.parametrize("nested_cells", [
    "<td>Private nested submission</td>",
    "<td>종료 일시</td><td>Private nested submission</td>",
])
@pytest.mark.parametrize("table_class", [False, True])
def test_assignment_status_ignores_nested_submission_rows(assignment_status_html, nested_cells, table_class):
    html = assignment_status_html.replace(
        "Private submission content",
        f"<table><tbody><tr>{nested_cells}</tr></tbody></table>",
    )
    if table_class:
        html = html.replace('<div class="submissionstatustable"><table>', '<div><table class="submissionstatustable">')
    result = learnus.parse_assignment_status(html, "123")
    assert result["submission_status"] == "not_submitted"
    assert result["due"] == "2026-09-25T23:59:00+09:00"
    assert "Private" not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("final_url", [
    "https://ys.learnus.org/mod/assign/view.php?id=456",
    "https://ys.learnus.org/mod/assign/view.php",
    "https://ys.learnus.org/mod/assign/view.php?id=123&id=456",
    "https://ys.learnus.org/mod/assign/view.php?id=123&id=",
    "https://ys.learnus.org:444/mod/assign/view.php?id=123",
    "https://other.test/mod/assign/view.php?id=123",
    "https://ys.learnus.org/login/index.php?id=123",
])
async def test_assignment_status_rejects_wrong_final_page(assignment_status_html, final_url):
    page = SimpleNamespace(
        goto=AsyncMock(), wait_for_selector=AsyncMock(),
        content=AsyncMock(return_value=assignment_status_html), url=final_url,
    )
    with pytest.raises(ScrapeFailedError):
        await learnus.fetch_assignment_status(page, "123")
    page.content.assert_not_awaited()


@pytest.mark.asyncio
async def test_assignment_status_accepts_requested_final_id(assignment_status_html):
    page = SimpleNamespace(
        goto=AsyncMock(), wait_for_selector=AsyncMock(), wait_for_function=AsyncMock(),
        content=AsyncMock(return_value=assignment_status_html),
        url="https://ys.learnus.org/mod/assign/view.php?lang=ko&id=123",
    )
    result = await learnus.fetch_assignment_status(page, "123")
    assert result["assignment_id"] == "123" and result["fetched_at"]
    assert "Private submission content" not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("fetch_name", ["fetch_courses", "fetch_notices"])
async def test_learnus_dashboard_reads_force_korean(fetch_name):
    from urllib.parse import parse_qs, urlsplit

    page = SimpleNamespace(
        goto=AsyncMock(), wait_for_selector=AsyncMock(), evaluate=AsyncMock(return_value=[]),
        wait_for_function=AsyncMock(), url=learnus.LEARNUS_HOME,
    )
    await getattr(learnus, fetch_name)(page)
    actual = page.goto.call_args.args[0]
    assert parse_qs(urlsplit(actual).query).get("lang") == ["ko"]


@pytest.fixture(params=[
    "fetch_courses", "fetch_notices", "fetch_deadlines", "fetch_attendance",
    "fetch_course_materials", "fetch_notice_body", "fetch_course_history",
    "fetch_assignment_status", "fetch_gradebook",
])
def korean_navigation(request, assignment_status_html):
    from test_read_tools import HISTORY_HTML

    cases = {
        "fetch_courses": ({}, "", [], ""),
        "fetch_notices": ({}, "", [], ""),
        "fetch_deadlines": ({"course_map": {}}, "calendar/view.php?view=upcoming", [], ""),
        "fetch_attendance": ({"course_id": "123"}, "report/ubcompletion/user_progress_a.php?id=123", [["Week"]], ""),
        "fetch_course_materials": ({"course_id": "123"}, "course/view.php?id=123", [], ""),
        "fetch_notice_body": ({"url": learnus.LEARNUS_HOME + "mod/ubboard/article.php?id=123&bwid=456&lang=en&lang=en"}, "mod/ubboard/article.php?id=123&bwid=456", {}, ""),
        "fetch_course_history": ({}, "local/ubion/user/index.php?year=all&semester=all", {"year": "all", "semester": "all", "semester_label": "전체"}, HISTORY_HTML),
        "fetch_assignment_status": ({"assignment_id": "123"}, "mod/assign/view.php?id=123", [], assignment_status_html),
        "fetch_gradebook": ({"course_id": "123"}, "grade/report/user/index.php?id=123", [], GRADEBOOK),
    }
    arguments, path, payload, html = cases[request.param]
    browser_page = SimpleNamespace(
        goto=AsyncMock(return_value=SimpleNamespace(ok=True)),
        wait_for_function=AsyncMock(), wait_for_selector=AsyncMock(), wait_for_timeout=AsyncMock(),
        evaluate=AsyncMock(return_value=payload), content=AsyncMock(return_value=html),
        url=learnus.LEARNUS_HOME + path,
    )
    return getattr(learnus, request.param), arguments, browser_page


@pytest.mark.asyncio
async def test_korean_navigation_verifies_dom_after_consumed_query(korean_navigation):
    from urllib.parse import parse_qs, urlsplit

    fetch, arguments, browser_page = korean_navigation
    await fetch(browser_page, **arguments)
    assert parse_qs(urlsplit(browser_page.goto.call_args.args[0]).query)["lang"] == ["ko"]
    assert any("document.documentElement.lang" in call.args[0] for call in browser_page.wait_for_function.await_args_list)


@pytest.mark.asyncio
async def test_korean_navigation_rejects_non_korean_dom(korean_navigation):
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError

    fetch, arguments, browser_page = korean_navigation

    async def wait_for_function(script, **kwargs):
        if "document.documentElement.lang" in script:
            raise PlaywrightTimeoutError("Synthetic English DOM")

    browser_page.wait_for_function.side_effect = wait_for_function
    with pytest.raises(ScrapeFailedError):
        await fetch(browser_page, **arguments)
    browser_page.evaluate.assert_not_awaited()
    browser_page.content.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(("language", "expected"), [("ko", True), ("ko-KR", True), ("en", False), ("", False), ("korean", False)])
async def test_korean_navigation_language_dom_marker(local_learnus_dom, language, expected):
    await local_learnus_dom.set_content(f'<html lang="{language}"><body></body></html>')
    assert await local_learnus_dom.evaluate(learnus._KOREAN_JS) is expected


@pytest.fixture
def course_history_page():
    from test_read_tools import HISTORY_HTML

    browser_page = SimpleNamespace(
        goto=AsyncMock(return_value=SimpleNamespace(ok=True)),
        wait_for_function=AsyncMock(), wait_for_selector=AsyncMock(),
        evaluate=AsyncMock(return_value={"year": "all", "semester": "all", "semester_label": "전체"}),
        content=AsyncMock(return_value=HISTORY_HTML), url="",
    )

    async def goto(url, **kwargs):
        browser_page.url = url
        return SimpleNamespace(ok=True)

    browser_page.goto.side_effect = goto
    return browser_page


def test_course_history_rejects_duplicate_course_ids():
    from bs4 import BeautifulSoup
    from test_read_tools import HISTORY_HTML

    soup = BeautifulSoup(HISTORY_HTML, "html.parser")
    row = str(soup.select_one("tbody tr"))
    with pytest.raises(ScrapeFailedError, match="중복"):
        learnus.parse_course_history(HISTORY_HTML.replace("</tbody>", row + "</tbody>"))


@pytest.mark.asyncio
@pytest.mark.parametrize("arguments", [{}, {"year": 2025, "semester": "20", "page": 1}])
async def test_course_history_displayed_result_metadata(course_history_page, arguments):
    from datetime import datetime
    from urllib.parse import parse_qs, urlsplit

    course_history_page.evaluate.return_value = {
        "year": str(arguments.get("year", "all")),
        "semester": arguments.get("semester", "all"),
        "semester_label": "2학기" if arguments.get("semester") == "20" else "전체",
    }
    result = await learnus.fetch_course_history(course_history_page, **arguments)
    assert result["count"] == len(result["courses"]) == 1
    assert result["year"] == arguments.get("year")
    assert result["semester"] == arguments.get("semester", "all")
    assert result["page"] == 1
    assert result["has_next"] is None and result["next_page"] is None
    assert result["has_pagination"] is False and result["pagination_supported"] is False
    assert result["scope"] == "displayed_result" and result["scope_note"]
    assert result["filters_verified"] is True
    assert "total" not in result and "total_pages" not in result
    assert result["source_url"] == course_history_page.url
    assert datetime.fromisoformat(result["fetched_at"]).utcoffset().total_seconds() == 9 * 3600
    query = parse_qs(urlsplit(course_history_page.goto.call_args.args[0]).query)
    assert query == {"year": [str(arguments.get("year", "all"))], "semester": [arguments.get("semester", "all")], "lang": ["ko"]}
    course_history_page.goto.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("selected", [
    None,
    {"year": "all", "semester": "20", "semester_label": "2학기"},
    {"year": "2025", "semester": "all", "semester_label": "전체"},
    {"year": "2025", "semester": "20", "semester_label": ""},
])
async def test_course_history_rejects_ignored_or_unconfirmed_filters(course_history_page, selected):
    course_history_page.evaluate.return_value = selected
    with pytest.raises(ScrapeFailedError, match="필터"):
        await learnus.fetch_course_history(course_history_page, year=2025, semester="20")


@pytest.mark.asyncio
@pytest.mark.parametrize("selected", [
    {"year": "2024", "semester": "20", "semester_label": "2학기"},
    {"year": "2025", "semester": "10", "semester_label": "1학기"},
])
async def test_course_history_rejects_rows_outside_selected_filters(course_history_page, selected):
    course_history_page.evaluate.return_value = selected
    with pytest.raises(ScrapeFailedError, match="필터"):
        await learnus.fetch_course_history(course_history_page, year=int(selected["year"]), semester=selected["semester"])


@pytest.mark.asyncio
@pytest.mark.parametrize("requested_page", [0, -1, 101, 1000, True, 1.5, "1", None])
async def test_course_history_page_bounds_before_navigation(course_history_page, requested_page):
    with pytest.raises(ValueError, match="1.*100"):
        await learnus.fetch_course_history(course_history_page, page=requested_page)
    course_history_page.goto.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("requested_page", [2, 100])
async def test_course_history_rejects_unverified_later_pages(course_history_page, requested_page):
    with pytest.raises(ValueError, match="페이지 이동"):
        await learnus.fetch_course_history(course_history_page, page=requested_page)
    course_history_page.goto.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("paging", [
    '<div class="pagination"><a href="?page=2">2</a></div>',
    '<div class="paging" hidden><button>Next</button></div>',
    '<a rel="next" hidden href="?page=2">Next</a>',
    '<input type="hidden" name="page" value="1">',
])
async def test_course_history_new_paging_controls_fail_closed(course_history_page, paging):
    course_history_page.content.return_value += paging
    with pytest.raises(ScrapeFailedError, match="페이지 이동"):
        await learnus.fetch_course_history(course_history_page)
    course_history_page.goto.assert_awaited_once()


@pytest.fixture(params=[
    ("fetch_deadlines", {"course_map": {}}, learnus.CALENDAR_UPCOMING, []),
    ("fetch_attendance", {"course_id": "123"}, learnus.PROGRESS_URL.format(course_id="123"), [["Week", "Progress"]]),
    ("fetch_course_materials", {"course_id": "123"}, learnus.COURSE_VIEW_URL.format(course_id="123"), []),
])
def learnus_read(request):
    name, arguments, url, payload = request.param
    page = SimpleNamespace(
        goto=AsyncMock(return_value=SimpleNamespace(ok=True)),
        wait_for_timeout=AsyncMock(), wait_for_function=AsyncMock(),
        evaluate=AsyncMock(return_value=payload), url=url,
    )
    return getattr(learnus, name), arguments, page


@pytest.mark.asyncio
async def test_learnus_all_ready_reads_force_korean(learnus_read):
    from urllib.parse import parse_qs, urlsplit

    fetch, arguments, page = learnus_read
    await fetch(page, **arguments)
    query = parse_qs(urlsplit(page.goto.call_args.args[0]).query)
    assert query.pop("lang", None) == ["ko"]
    assert query == parse_qs(urlsplit(page.url).query)


@pytest.mark.parametrize("language", ["lang=en", "lang=en&lang=ko&lang=en", "lang="])
def test_learnus_korean_url_preserves_other_query_values(language):
    from urllib.parse import parse_qs, urlsplit

    url = learnus.LEARNUS_HOME + "mod/ubboard/article.php?id=123&bwid=456&" + language + "&search=a%2Bb&empty=#post"
    result = urlsplit(learnus._korean_url(url))
    assert result.path == "/mod/ubboard/article.php"
    assert result.fragment == ""
    assert parse_qs(result.query, keep_blank_values=True) == {
        "id": ["123"], "bwid": ["456"], "lang": ["ko"], "search": ["a+b"], "empty": [""],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("url", [
    "https://ys.learnus.org.other.test/mod/ubboard/article.php?id=123",
    "https://other.test/mod/ubboard/article.php?id=123&host=ys.learnus.org",
    "https://ys.learnus.org:444/mod/ubboard/article.php?id=123",
    "https://user@ys.learnus.org/mod/ubboard/article.php?id=123",
    "http://ys.learnus.org/mod/ubboard/article.php?id=123",
    "https://ys.learnus.org/mod/ubboard/article.php/other?id=123",
    "https://ys.learnus.org/mod/ubboard/article.php?id=123&id=456",
])
async def test_learnus_notice_rejects_unsafe_input_before_navigation(url):
    with pytest.raises(ValueError):
        await learnus.fetch_notice_body(None, url)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    "origin", "path", "query", "duplicate_query", "blank_query", "scheme", "port", "userinfo",
])
async def test_learnus_reads_reject_wrong_final_page(learnus_read, change):
    fetch, arguments, page = learnus_read
    changes = {
        "origin": page.url.replace("ys.learnus.org", "other.test"),
        "path": "https://ys.learnus.org/login/index.php?" + page.url.split("?", 1)[1],
        "query": page.url.replace("upcoming", "month").replace("123", "456"),
        "duplicate_query": page.url + "&" + page.url.split("?", 1)[1],
        "blank_query": page.url + "&" + page.url.split("?", 1)[1].split("=", 1)[0] + "=",
        "scheme": page.url.replace("https:", "http:"),
        "port": page.url.replace("ys.learnus.org", "ys.learnus.org:444"),
        "userinfo": page.url.replace("ys.learnus.org", "user@ys.learnus.org"),
    }
    page.url = changes[change]
    with pytest.raises(ScrapeFailedError):
        await fetch(page, **arguments)
    page.evaluate.assert_not_awaited()


@pytest.mark.asyncio
async def test_learnus_reads_reject_http_error_page(learnus_read):
    fetch, arguments, page = learnus_read
    page.goto.return_value = SimpleNamespace(ok=False)
    with pytest.raises(ScrapeFailedError):
        await fetch(page, **arguments)
    page.evaluate.assert_not_awaited()


@pytest.mark.asyncio
async def test_learnus_reads_reject_missing_structure(learnus_read):
    fetch, arguments, page = learnus_read
    page.evaluate.return_value = None
    with pytest.raises(ScrapeFailedError):
        await fetch(page, **arguments)


@pytest.mark.asyncio
async def test_learnus_reads_require_page_readiness(learnus_read):
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError

    fetch, arguments, page = learnus_read
    page.wait_for_function.side_effect = PlaywrightTimeoutError("Synthetic missing page structure")
    with pytest.raises(ScrapeFailedError):
        await fetch(page, **arguments)
    page.evaluate.assert_not_awaited()


@pytest.mark.asyncio
async def test_learnus_reads_accept_verified_empty_payload(learnus_read):
    fetch, arguments, page = learnus_read
    result = await fetch(page, **arguments)
    if fetch is learnus.fetch_deadlines:
        assert result == []
    elif fetch is learnus.fetch_attendance:
        assert result == {"course_id": "123", "header": ["Week", "Progress"], "weeks": []}
    else:
        assert result == {"course_id": "123", "section_count": 0, "activity_count": 0, "sections": []}
    assert page.wait_for_function.await_count == 2
    page.wait_for_timeout.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("fetch_name", ["fetch_attendance", "fetch_course_materials"])
@pytest.mark.parametrize("course_id", ["", "123&id=456", "../123", "１２３"])
async def test_learnus_course_reads_validate_id_before_navigation(fetch_name, course_id):
    with pytest.raises(ValueError):
        await getattr(learnus, fetch_name)(None, course_id)


@pytest.fixture
async def local_learnus_dom():
    from playwright.async_api import async_playwright

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        try:
            page = await browser.new_page()
            await page.route("**/*", lambda route: route.abort())
            yield page
        finally:
            await browser.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(("fetch_name", "arguments", "url", "html", "key"), [
    ("fetch_deadlines", {"course_map": {}}, learnus.CALENDAR_UPCOMING,
     '<main id="region-main">No events</main><script>globalThis.M = {str: {calendar: {noupcomingevents: "No events"}}}</script>', None),
    ("fetch_attendance", {"course_id": "123"}, learnus.PROGRESS_URL.format(course_id="123"),
     '<table class="user_progress_table"><tr><th>Week</th><th>Progress</th></tr></table>', "weeks"),
])
async def test_learnus_reads_local_dom_readiness(local_learnus_dom, fetch_name, arguments, url, html, key):
    await local_learnus_dom.route(learnus._korean_url(url), lambda route: route.fulfill(status=200, content_type="text/html", body='<html lang="ko">' + html + '</html>'))
    result = await getattr(learnus, fetch_name)(local_learnus_dom, **arguments)
    assert (result[key] if key else result) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(("raw", "expected"), [
    ("2026-9-2", "2026-09-02"),
    ("2026. 9. 2", "2026-09-02"),
    ("2026/9/2", "2026-09-02"),
    ("2026-02-29", None),
    ("2026-09/22", None),
    ("12026-09-22", None),
    ("2026-09-222", None),
])
async def test_notice_body_dom_numeric_dates(local_learnus_dom, raw, expected):
    await local_learnus_dom.set_content(f'<h3>Notice</h3><div class="boardInfo">Author\n{raw}</div><div class="text_to_html">Body</div>')
    page = SimpleNamespace(
        goto=AsyncMock(), wait_for_timeout=AsyncMock(), evaluate=local_learnus_dom.evaluate,
        wait_for_function=AsyncMock(), url=learnus.LEARNUS_HOME + "mod/ubboard/article.php?id=123",
    )
    result = await learnus.fetch_notice_body(page, learnus.LEARNUS_HOME + "mod/ubboard/article.php?id=123")
    assert result["date"] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("final_id", ["123", "456"])
async def test_attendance_verified_redirect_keeps_course_identity(final_id):
    page = SimpleNamespace(
        goto=AsyncMock(return_value=None), wait_for_function=AsyncMock(),
        evaluate=AsyncMock(return_value=[["Week", "Progress"], ["1", "0%"]]),
        url=f"https://ys.learnus.org/report/ubcompletion/user_progress_a.php?id={final_id}",
    )
    if final_id != "123":
        with pytest.raises(ScrapeFailedError):
            await learnus.fetch_attendance(page, "123")
    else:
        result = await learnus.fetch_attendance(page, "123")
        assert result["weeks"] == [{"Week": "1", "Progress": "0%"}]


@pytest.mark.asyncio
@pytest.mark.parametrize(("message", "style", "expected"), [
    ("계획된 일정이 없습니다.", "", []),
    ("계획된 일정이 없습니다.", "display:none", None),
    ("Loading", "", None),
])
async def test_learnus_calendar_verified_empty_marker(local_learnus_dom, message, style, expected):
    await local_learnus_dom.set_content(
        '<div class="maincalendar" data-region="calendar"><div class="eventlist">'
        f'<span class="calendar-information calendar-no-results" style="{style}">{message}</span>'
        '</div></div>'
    )
    assert await local_learnus_dom.evaluate(learnus._CALENDAR_JS) == expected


@pytest.mark.asyncio
async def test_learnus_calendar_dom_distinguishes_empty_from_missing(local_learnus_dom):
    page = local_learnus_dom
    for html in ['<h1>Login</h1>', '<main id="region-main">Loading</main>']:
        await page.set_content(html)
        assert await page.evaluate(learnus._CALENDAR_JS) is None
    await page.set_content('<main id="region-main"><p>No upcoming events (source text)</p></main>')
    assert await page.evaluate(learnus._CALENDAR_JS) is None
    await page.evaluate("globalThis.M = {str: {calendar: {noupcomingevents: 'No upcoming events (source text)'}}}")
    assert await page.evaluate(learnus._CALENDAR_JS) == []
    await page.set_content('''<main id="region-main"><div data-region="event-item">
        <a data-action="view-event" href="https://ys.learnus.org/calendar/view.php?course=123&time=1790000000">Task</a>
        <span class="date">Tomorrow</span></div></main>''')
    events = await page.evaluate(learnus._CALENDAR_JS)
    assert len(events) == 1 and events[0]["title"] == "Task"


@pytest.mark.asyncio
async def test_learnus_attendance_dom_distinguishes_empty_from_missing(local_learnus_dom):
    page = local_learnus_dom
    for html in ['<h1>Unavailable</h1>', '<table class="user_progress_table"></table>']:
        await page.set_content(html)
        assert await page.evaluate(learnus._ATTENDANCE_JS) is None
    await page.set_content('<table class="user_progress_table"><tr><th>Week</th><th>Progress</th></tr></table>')
    assert await page.evaluate(learnus._ATTENDANCE_JS) == [["Week", "Progress"]]
    await page.set_content('<table class="user_progress_table"><tr><th>Week</th><th>Progress</th></tr><tr><td>1</td><td>0%</td></tr></table>')
    assert await page.evaluate(learnus._ATTENDANCE_JS) == [["Week", "Progress"], ["1", "0%"]]


@pytest.mark.asyncio
async def test_learnus_materials_dom_distinguishes_empty_from_missing(local_learnus_dom):
    page = local_learnus_dom
    for html in ['<h1>Unavailable</h1>', '<div class="course-content">Loading</div>']:
        await page.set_content(html)
        assert await page.evaluate(learnus._MATERIALS_JS) is None
    await page.set_content('<div class="course-content"><ul></ul></div>')
    assert await page.evaluate(learnus._MATERIALS_JS) is None
    await page.set_content('<div class="course-content"><ul><li class="section" id="section-1"><h3 class="sectionname">Week 1</h3></li></ul></div>')
    assert await page.evaluate(learnus._MATERIALS_JS) == [{"id": "section-1", "name": "Week 1", "activities": []}]
    await page.set_content('''<div class="course-content"><ul><li class="section" id="section-1"><h3 class="sectionname">Week 1</h3>
        <ul><li class="activity modtype_assign"><a href="https://ys.learnus.org/mod/assign/view.php?id=456"><span class="instancename">Task</span></a></li></ul>
        </li></ul></div>''')
    sections = await page.evaluate(learnus._MATERIALS_JS)
    assert sections[0]["activities"][0]["mod"] == "assign"


@pytest.mark.asyncio
async def test_materials_wait_for_populated_course_sections(local_learnus_dom):
        url = learnus.COURSE_VIEW_URL.format(course_id="123")
        html = '''<div class="course-content"></div><script>
        setTimeout(() => {
            document.querySelector('.course-content').innerHTML = '<ul><li class="section" id="section-1"><h3 class="sectionname">Week 1</h3><ul><li class="activity modtype_assign"><a href="/mod/assign/view.php?id=456">Task</a></li></ul></li></ul>';
        }, 300);
        </script>'''
        await local_learnus_dom.route(learnus._korean_url(url), lambda route: route.fulfill(status=200, content_type="text/html", body='<html lang="ko">' + html + '</html>'))
        result = await learnus.fetch_course_materials(local_learnus_dom, "123")
        assert result["activity_count"] == 1
        assert result["sections"][0]["activities"][0]["type"] == "assign"


GRADEBOOK = '''<table class="user-grade"><thead><tr>
<th class="column-itemname" colspan="2">성적 항목</th><th class="column-grade">성적</th><th class="column-weight">가중치</th><th class="column-feedback">피드백</th>
</tr></thead><tbody>
<tr><th class="column-itemname" colspan="5">Category</th></tr>
<tr><th class="column-itemname"><a>Task</a></th><td class="column-grade" headers="private-student">0</td><td class="column-weight">20%</td><td class="column-feedback">Private feedback</td></tr>
<tr><th class="column-itemname baggt">Total</th><td class="column-grade">-</td><td class="column-weight">-</td><td class="column-feedback"></td></tr>
</tbody></table>'''


def test_gradebook_keeps_zero_unavailable_and_totals_distinct():
    result = learnus.parse_gradebook(GRADEBOOK, "123")
    assert result["count"] == 3
    assert [row["kind"] for row in result["items"]] == ["category", "item", "total"]
    assert result["items"][1]["grade_raw"] == "0"
    assert result["items"][1]["grade_available"] is True
    assert result["items"][2]["grade_raw"] == "-"
    assert result["items"][2]["grade_available"] is False
    assert "Private feedback" not in str(result) and "private-student" not in str(result)
    assert result["feedback_included"] is False
    assert learnus.parse_gradebook(GRADEBOOK, "123", include_feedback=True)["items"][1]["feedback"] == "Private feedback"


def test_gradebook_hidden_values_are_not_returned():
    html = GRADEBOOK.replace('headers="private-student">0', 'hidden>99')
    result = learnus.parse_gradebook(html, "123")
    assert result["items"][1]["grade_raw"] is None
    assert result["items"][1]["grade_available"] is False
    assert "99" not in str(result)


@pytest.mark.parametrize("include_feedback", [False, True])
def test_gradebook_nested_feedback_table_is_not_a_grade_row(include_feedback):
    html = GRADEBOOK.replace("Private feedback", "<table><tbody><tr><td>Rubric</td></tr></tbody></table>")
    result = learnus.parse_gradebook(html, "123", include_feedback=include_feedback)
    assert result["count"] == 3
    if include_feedback:
        assert result["items"][1]["feedback"] == "Rubric"
    else:
        assert "Rubric" not in str(result)


def test_gradebook_optional_range_and_percentage_columns():
    html = GRADEBOOK.replace(
        '<th class="column-feedback">',
        '<th class="column-range">Range</th><th class="column-percentage">Percentage</th><th class="column-feedback">',
    ).replace(
        '<td class="column-feedback">',
        '<td class="column-range">0-100</td><td class="column-percentage">0%</td><td class="column-feedback">',
    )
    result = learnus.parse_gradebook(html, "123")
    assert result["items"][1]["range_raw"] == "0-100"
    assert result["items"][1]["percentage_raw"] == "0%"


def test_gradebook_ignores_inline_hidden_descriptions_and_rows():
    html = GRADEBOOK.replace('>Total</th>', '>Total<div class="gradeitemdescription" style="display: none;">Hidden explanation</div></th>')
    result = learnus.parse_gradebook(html, "123")
    assert result["items"][2]["name"] == "Total"
    assert "Hidden explanation" not in str(result)
    hidden = GRADEBOOK.replace('<tr><th class="column-itemname"><a>Task</a>', '<tr style="display: none;"><th class="column-itemname"><a>Task</a>')
    hidden_result = learnus.parse_gradebook(hidden, "123", include_feedback=True)
    assert "Private feedback" not in str(hidden_result)
    assert all(item["name"] != "Task" for item in hidden_result["items"])


@pytest.mark.parametrize("html", ["<h1>Login</h1>", GRADEBOOK.replace('class="column-grade"', 'class="changed"'), GRADEBOOK.replace('<td class="column-grade" headers="private-student">0</td>', ''), GRADEBOOK.replace('<a>Task</a>', '')])
def test_gradebook_rejects_missing_schema(html):
    with pytest.raises(ScrapeFailedError):
        learnus.parse_gradebook(html, "123")


@pytest.mark.asyncio
@pytest.mark.parametrize("course_id", ["", "1&userid=2", "../1", "１２３"])
async def test_gradebook_validates_id_before_browser(course_id):
    with pytest.raises(ValueError):
        await learnus.fetch_gradebook(None, course_id)


COPIES = '''<table class="searchTable"><thead><tr><th>No.</th><th>등록번호</th><th>청구기호</th><th>소장처</th><th>도서상태</th><th>반납예정일</th><th>예약</th><th>매체정보</th></tr></thead><tbody>
<tr><td>1</td><td>BOOK1</td><td>123 A</td><td>Central 2F</td><td><span class="status available">대출가능</span></td><td></td><td><button data-id="secret-action">Reserve</button></td><td></td></tr>
<tr><td>2</td><td>BOOK2</td><td>123 A c.2</td><td>Central 2F</td><td>대출중</td><td>2026-10-01</td><td></td><td></td></tr>
</tbody></table>'''


def test_book_copies_preserve_per_copy_status_and_blank_due_date():
    result = library.parse_book_copies(COPIES, "CATTOT123")
    assert result["count"] == 2
    assert result["copies"][0] == {"reg_no": "BOOK1", "call_number": "123 A", "location": "Central 2F", "status_raw": "대출가능", "due_date_raw": "", "campus": None}
    assert result["copies"][1]["due_date_raw"] == "2026-10-01"
    assert "secret-action" not in str(result) and "Reserve" not in str(result)


@pytest.mark.parametrize(("location", "campus"), [("[신촌]도서관/2층/", "sinchon"), ("[국제]언더우드/", "international"), ("[미래]도서관/", "mirae"), ("Other", None)])
def test_copy_campus_keeps_unknown_locations_unknown(location, campus):
    result = library.parse_book_copies(COPIES.replace("Central 2F", location), "CATTOT123")
    assert all(copy["campus"] == campus and copy["location"] == location for copy in result["copies"])


@pytest.mark.parametrize("html", ["<h1>Unavailable</h1>", COPIES.replace("청구기호", "Changed"), COPIES.replace("<td>BOOK1</td>", ""), COPIES.replace("<td>BOOK1</td>", "<td></td>")])
def test_book_copies_reject_missing_or_shifted_fields(html):
    with pytest.raises(ScrapeFailedError):
        library.parse_book_copies(html, "CATTOT123")


@pytest.mark.asyncio
@pytest.mark.parametrize("catalog_id", ["", "../1", "CATTOT123?other=1", "https://example.test/", "123"])
async def test_book_detail_id_validation_happens_before_network(monkeypatch, catalog_id):
    fetch = AsyncMock()
    monkeypatch.setattr(library.httpclient, "get_html", fetch)
    with pytest.raises(ValueError):
        await library.fetch_book_detail(catalog_id)
    fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_book_detail_uses_public_fixed_host(monkeypatch):
    fetch = AsyncMock(return_value=COPIES)
    monkeypatch.setattr(library.httpclient, "get_html", fetch)
    result = await library.fetch_book_detail("CATTOT123")
    fetch.assert_awaited_once_with("https://library.yonsei.ac.kr/search/detail/CATTOT123")
    assert result["count"] == 2 and result["fetched_at"] and result["source_url"]


LOAN_HISTORY = '''<form id="form" action="/myloan/history" method="get"><input name="dtf" value="20260101"><input name="dtt" value="20260922"></form>
<table class="mobileTable"><thead><tr><th>No.</th><th>서명/저자</th><th>소장처</th><th>등록번호</th><th>대출일</th><th>반납일</th><th>반납유형</th></tr></thead>
<tbody><tr><td>1</td><td>Example Book</td><td>Central</td><td>BOOK1</td><td>2026-09-01</td><td>2026-09-10</td><td>Normal</td></tr></tbody></table>
<div class="paging"><a href="/myloan/history?pn=2">2</a></div>'''

RESERVE_HISTORY = '''<form action="/myreserve/integratedCancel" method="post"><input name="paramStr" value="private-action"></form>
<table class="mobileTable"><thead><tr><th>No.</th><th>서명/저자</th><th>소장처</th><th>예약순위</th><th>예 약일</th><th>도착 통보일</th><th>예약상태</th></tr></thead>
<tbody><tr><td>1</td><td>Example Book</td><td>Central</td><td>1</td><td>2026-09-01</td><td></td><td>Cancelled</td></tr></tbody></table>'''


def test_loan_history_does_not_confuse_return_date_with_due_date():
    result = library.parse_loan_history(LOAN_HISTORY)
    assert result["count"] == 1
    assert result["loans"][0]["return_date"] == "2026-09-10"
    assert result["loans"][0]["return_type"] == "Normal"
    assert "due_date" not in result["loans"][0]
    assert result["date_filters_raw"] == {"from": "20260101", "to": "20260922"}
    assert result["scope"] == "displayed_page" and result["has_pagination"] is True


def test_reservation_history_excludes_post_actions():
    result = library.parse_reservation_history(RESERVE_HISTORY)
    assert result["count"] == 1
    assert result["reservations"][0]["status"] == "Cancelled"
    assert result["scope"] == "displayed_page"
    assert "private-action" not in str(result)


@pytest.mark.parametrize(("parser", "html", "width", "key"), [
    ("parse_loan_history", LOAN_HISTORY, 7, "loans"),
    ("parse_reservation_history", RESERVE_HISTORY, 7, "reservations"),
])
def test_history_explicit_empty_and_broken_table_are_distinct(parser, html, width, key):
    import re
    parse = getattr(library, parser)
    empty = re.sub(r"<tbody>.*?</tbody>", f'<tbody><tr><td colspan="{width}">등록된 자료가 없습니다.</td></tr></tbody>', html)
    assert parse(empty)[key] == []
    with pytest.raises(ScrapeFailedError):
        parse(empty.replace("등록된 자료가 없습니다.", "Loading"))
    with pytest.raises(ScrapeFailedError):
        parse("<h1>Login</h1>")


@pytest.mark.asyncio
@pytest.mark.parametrize(("fetch_name", "path", "html"), [
    ("fetch_loan_history", "/myloan/history", LOAN_HISTORY),
    ("fetch_reservation_history", "/myreserve/integratedhistory", RESERVE_HISTORY),
])
async def test_history_fetch_only_navigates_to_read_page(fetch_name, path, html):
    from types import SimpleNamespace
    page = SimpleNamespace(goto=AsyncMock(), wait_for_selector=AsyncMock(), content=AsyncMock(return_value=html), url="https://library.yonsei.ac.kr" + path)
    result = await getattr(library, fetch_name)(page)
    page.goto.assert_awaited_once_with(page.url, wait_until="domcontentloaded")
    assert result["source_url"] == page.url and result["fetched_at"]


@pytest.mark.asyncio
@pytest.mark.parametrize(("tool_name", "fetch_name", "owner", "session_name", "arguments"), [
    ("get_lms_gradebook", "fetch_gradebook", learnus, "get_session", {"course_id": "123"}),
    ("get_my_loan_history", "fetch_loan_history", library, "get_library_session", {}),
    ("get_my_reservation_history", "fetch_reservation_history", library, "get_library_session", {}),
])
async def test_authenticated_tools_separate_accounts_and_cache(monkeypatch, tool_name, fetch_name, owner, session_name, arguments):
    from types import SimpleNamespace
    from yonsei_portal_mcp import server, cache

    fetch = AsyncMock(return_value={"count": 1})
    monkeypatch.setattr(owner, fetch_name, fetch)
    monkeypatch.setattr(server, "_account", lambda: "first-account")
    async def run(action):
        return await action(None)
    monkeypatch.setattr(server, session_name, lambda: SimpleNamespace(run=run))
    cache.clear()
    try:
        tool = getattr(server, tool_name)
        assert await tool(**arguments) == {"count": 1}
        await tool(**arguments)
        assert fetch.await_count == 1
        monkeypatch.setattr(server, "_account", lambda: "second-account")
        await tool(**arguments)
        assert fetch.await_count == 2
        assert tool_name in {tool.name for tool in await server.mcp.list_tools()}
    finally:
        cache.clear()


@pytest.mark.asyncio
async def test_gradebook_feedback_opt_in_separates_cache(monkeypatch):
    from types import SimpleNamespace
    from yonsei_portal_mcp import server, cache

    fetch = AsyncMock(side_effect=[{"feedback_included": True}, {"feedback_included": False}])
    monkeypatch.setattr(learnus, "fetch_gradebook", fetch)
    monkeypatch.setattr(server, "_account", lambda: "test-account")
    async def run(action):
        return await action(None)
    monkeypatch.setattr(server, "get_session", lambda: SimpleNamespace(run=run))
    cache.clear()
    try:
        assert (await server.get_lms_gradebook("123", include_feedback=True))["feedback_included"]
        assert not (await server.get_lms_gradebook("123"))["feedback_included"]
        assert fetch.await_count == 2
    finally:
        cache.clear()


@pytest.mark.asyncio
async def test_public_detail_tool_never_loads_account(monkeypatch):
    from yonsei_portal_mcp import server, cache

    monkeypatch.setattr(server, "_account", lambda: pytest.fail("Public tool loaded credentials"))
    fetch = AsyncMock(return_value={"count": 1})
    monkeypatch.setattr(library, "fetch_book_detail", fetch)
    cache.clear()
    try:
        assert await server.get_library_book_detail("CATTOT123") == {"count": 1}
        await server.get_library_book_detail("CATTOT123")
        fetch.assert_awaited_once_with("CATTOT123")
        assert "get_library_book_detail" in {tool.name for tool in await server.mcp.list_tools()}
    finally:
        cache.clear()


@pytest.mark.asyncio
async def test_new_tools_reject_bad_ids_before_credentials(monkeypatch):
    from yonsei_portal_mcp import server

    monkeypatch.setattr(server, "_account", lambda: pytest.fail("Must validate before loading credentials"))
    with pytest.raises(ValueError):
        await server.get_lms_gradebook("123&userid=other")
    with pytest.raises(ValueError):
        await server.get_library_book_detail("https://example.test")
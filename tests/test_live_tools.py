"""Opt-in read-only MCP smoke test; never prints tool payloads or credentials."""
from __future__ import annotations

import json
import os
import sys
from urllib.parse import parse_qs, urlsplit

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


@pytest.mark.live
@pytest.mark.asyncio
async def test_all_read_tools_over_stdio() -> None:
    if os.getenv("RUN_LIVE_PORTAL") != "1":
        pytest.skip("set RUN_LIVE_PORTAL=1 for real read-only portal access")

    checked = set()
    with open(os.devnull, "w") as errlog:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "yonsei_portal_mcp"],
            env=os.environ.copy(),
        )
        async with stdio_client(params, errlog=errlog) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                registered = {tool.name for tool in (await session.list_tools()).tools}

                async def invoke(name, arguments, expected_type, required_keys=()):
                    try:
                        result = await session.call_tool(name, arguments)
                    except Exception as exc:
                        pytest.fail(f"{name}: {type(exc).__name__}", pytrace=False)
                    failed = bool(result.isError)
                    if failed:
                        pytest.fail(f"{name}: MCP tool error (payload suppressed)", pytrace=False)
                    payload = result.structuredContent
                    if payload is None:
                        text = "\n".join(getattr(part, "text", "") for part in result.content)
                        if expected_type is str:
                            payload = text
                        else:
                            try:
                                payload = json.loads(text)
                            except ValueError:
                                pytest.fail(f"{name}: invalid JSON response", pytrace=False)
                    if isinstance(payload, dict) and set(payload) == {"result"}:
                        payload = payload["result"]
                    valid = isinstance(payload, expected_type)
                    if required_keys and valid:
                        valid = set(required_keys) <= payload.keys()
                    if not valid:
                        pytest.fail(f"{name}: unexpected response schema", pytrace=False)
                    checked.add(name)
                    print(f"{name}: PASS", flush=True)
                    return payload

                courses = await invoke("get_lms_courses", {}, list)
                notices = await invoke("get_lms_notices", {}, list)
                await invoke("get_lms_deadlines", {}, list)
                await invoke("search_notices", {"query": "장학금"}, dict, ("count", "results"))
                await invoke("get_lms_overview", {}, dict, ("courses", "upcoming_deadlines"))
                profile = await invoke("get_student_profile", {}, dict, ("department", "terms", "pii_included"))
                private_excluded = "name" not in profile and "student_no" not in profile and not profile["pii_included"]
                assert private_excluded, "Profile default must exclude name/student number"
                timetable = await invoke("get_my_timetable", {}, dict, ("courses", "count"))
                grades = await invoke("get_grades", {}, dict, ("courses", "summary", "summary_scope"))
                if grades["courses"]:
                    sample = grades["courses"][0]
                    filtered = await invoke("get_grades", {"year": int(sample["year"]), "term_code": sample["term_code"]}, dict)
                    expected_rows = [row for row in grades["courses"] if row["year"] == sample["year"] and row["term_code"] == sample["term_code"]]
                    filters_match = (
                        filtered.get("courses") == expected_rows
                        and filtered.get("count") == len(expected_rows)
                        and filtered.get("summary") == grades["summary"]
                        and filtered.get("summary_scope") == grades["summary_scope"] == "all_terms"
                    )
                    assert filters_match, "Grade source/filter mismatch"
                await invoke("get_my_loans", {}, dict, ("loans", "count"))
                await invoke("get_my_reservations", {}, dict, ("reservations", "count"))
                await invoke("get_my_loan_history", {}, dict, ("loans", "count", "scope", "date_filters_raw"))
                await invoke("get_my_reservation_history", {}, dict, ("reservations", "count", "scope"))
                await invoke("get_scholarship_history", {}, dict, ("scholarships", "count"))
                await invoke("get_exam_schedule", {}, dict, ("exams", "count", "period_configured", "exam_type"))
                final_exams = await invoke("get_exam_schedule", {"exam_type": "final"}, dict)
                final_selected = "기말" in final_exams["exam_type"]
                assert final_selected, "Final exam filter not reflected in source"
                await invoke("get_my_schedule", {"days": 7, "include_exams": True}, dict, ("window", "events", "weekly_timetable", "exams", "undated_items"))
                catalog = await invoke("search_courses", {"keyword": "인공지능", "limit": 3}, dict, ("courses", "filters", "truncated"))
                valid_catalog = catalog["filters"]["keyword_type"] == "2" and all("인공지능" in row["course_name"] for row in catalog["courses"])
                assert valid_catalog, "Catalog keyword and source filters disagree"
                scoped = await invoke("search_courses", {"keyword": "인공지능", "limit": 3, "year": 2026, "term_code": "10", "campus_code": "s3"}, dict)
                scoped_valid = scoped["requested_filters"] == {"year": 2026, "term_code": "10", "campus_code": "s3"} and all(str(row["year"]) == "2026" and row["term_code"] == "10" and row["campus_code"] == "s3" for row in scoped["courses"])
                assert scoped_valid, "Catalog scoped result differs from requested filters"
                history = await invoke("get_lms_course_history", {}, dict, ("courses", "count", "has_pagination"))
                await invoke("get_library_seats", {}, dict)
                seats = await invoke("get_library_seat_rooms", {}, dict, ("rooms", "count", "assignable_available", "source_totals_match"))
                valid_seats = seats["source_totals_match"] is True and all(room["name"] != "합계" for room in seats["rooms"])
                assert valid_seats, "Seat rooms must exclude source total and reconcile totals"
                calendar = await invoke("export_calendar_ics", {}, str)
                valid_calendar = calendar.startswith("BEGIN:VCALENDAR")
                assert valid_calendar, "Calendar format invalid"
                academic = await invoke("get_academic_calendar", {}, dict, ("academic_year", "semester", "months", "date_note", "source_url"))
                calendar_count_matches = academic["count"] == sum(len(month["events"]) for month in academic["months"])
                assert calendar_count_matches, "Public calendar item count mismatch"
                periods = {slot["period"] for course in timetable["courses"] for slot in course["slots"]}
                fixture_supported = bool(periods) and all(1 <= period <= 20 for period in periods)
                assert fixture_supported, "Live timetable needs an updated explicit-time test fixture"
                test_times = {str(period): {"start": f"{7 + period // 2:02d}:{30 * (period % 2):02d}", "end": f"{7 + period // 2:02d}:{30 * (period % 2) + 25:02d}"} for period in periods}
                recurring = await invoke("export_timetable_ics", {"start_date": "2026-09-01", "end_date": "2026-09-30", "period_times": test_times, "exclude_dates": ["2026-09-24"]}, str)
                expected_events = sum(len({(slot["day_en"], slot["period"]) for slot in course["slots"]}) for course in timetable["courses"])
                recurring_valid = recurring.count("BEGIN:VEVENT") == expected_events and recurring.count("RRULE:FREQ=WEEKLY;") == expected_events
                assert recurring_valid, "Synthetic explicit-time recurrence does not match timetable slots"
                books = await invoke("search_library_books", {"query": "인공지능", "limit": 2}, dict, ("results", "count", "page"))
                if not books["results"]:
                    pytest.fail("Need one catalog result for copy detail verification", pytrace=False)
                catalog_id = urlsplit(books["results"][0]["url"]).path.rsplit("/", 1)[-1]
                await invoke("get_library_book_detail", {"catalog_id": catalog_id}, dict, ("catalog_id", "count", "copies"))
                library_notices = await invoke("get_library_notices", {"limit": 2}, dict, ("notices", "count"))
                if not library_notices["notices"]:
                    pytest.fail("Need a public library notice to test the body route", pytrace=False)
                await invoke("get_notice", {"url": library_notices["notices"][0]["url"]}, dict, ("title", "body", "image_count"))

                if not courses or not notices:
                    pytest.fail("Need an accessible course and notice for dependent tools", pytrace=False)
                course_id = courses[0]["id"]
                course_boards = await invoke("get_lms_boards", {"course_id": course_id}, dict, ("boards", "count", "source_url"))
                if not course_boards["boards"]:
                    pytest.fail("Need a course board for read-only listing verification", pytrace=False)
                await invoke("get_lms_board_posts", {"board_id": course_boards["boards"][0]["board_id"]}, dict, ("posts", "count", "unlinked_count", "scope"))
                gradebook = await invoke("get_lms_gradebook", {"course_id": course_id}, dict, ("course_id", "items", "feedback_included"))
                no_feedback = not gradebook["feedback_included"] and all("feedback" not in item for item in gradebook["items"])
                assert no_feedback, "Gradebook feedback must be opt-in"
                await invoke("get_lms_attendance", {"course_id": course_id}, dict, ("weeks", "header"))
                await invoke("get_lms_course_materials", {"course_id": course_id}, dict, ("sections", "activity_count"))
                await invoke("get_lms_assignments", {"course_id": course_id}, dict, ("assignments", "count"))
                await invoke("get_notice", {"url": notices[0]["url"]}, dict, ("title", "body", "url"))
                inspected = set()
                found_assignment = None
                for course in history["courses"] + courses:
                    if course["id"] in inspected:
                        continue
                    inspected.add(course["id"])
                    assignments = await invoke("get_lms_assignments", {"course_id": course["id"]}, dict)
                    if assignments["assignments"]:
                        found_assignment = assignments["assignments"][0]
                        break
                if found_assignment is None:
                    pytest.fail("No accessible assignment to verify the detail tool", pytrace=False)
                assignment_id = parse_qs(urlsplit(found_assignment["url"]).query)["id"][0]
                await invoke("get_lms_assignment_status", {"assignment_id": assignment_id}, dict, ("submission_status", "grading_status_raw", "due_raw", "fetched_at"))
                assert registered == checked, "Not all registered MCP tools were exercised"


@pytest.mark.live
@pytest.mark.asyncio
async def test_course_boards_match_source_and_korean_navigation() -> None:
    if os.getenv("RUN_LIVE_PORTAL") != "1":
        pytest.skip("set RUN_LIVE_PORTAL=1 for course board source verification")
    from yonsei_portal_mcp.scrapers import boards, learnus
    from yonsei_portal_mcp.session import get_session

    async def check(page):
        await page.goto(learnus.LEARNUS_HOME + "?lang=en", wait_until="domcontentloaded")
        english = await page.evaluate("document.documentElement.lang.toLowerCase().startsWith('en')")
        if not english:
            pytest.fail("Need an actual English source before Korean collection check", pytrace=False)
        current = await learnus.fetch_courses(page)
        korean = await page.evaluate("document.documentElement.lang.toLowerCase().startsWith('ko')")
        if not korean:
            pytest.fail("LearnUs did not switch collection to Korean", pytrace=False)
        history = await learnus.fetch_course_history(page)
        ids = {course["id"] for course in current}
        previous = [course for course in history["courses"] if course["id"] not in ids]
        if not current or not previous:
            pytest.fail("Need current and previous course samples", pytrace=False)
        linked_count = 0
        for course in (current[0], previous[0]):
            listing = await boards.fetch_boards(page, course["id"])
            raw = await page.locator("table.ubboard_table > tbody > tr").evaluate_all(
                r"rows=>rows.filter(row=>row.children.length>1).map(row=>{const cells=[...row.children],offset=cells.length===4?1:0,link=cells[offset].querySelector('a');return {board_id:new URL(link.href).searchParams.get('id'),name:link.innerText.trim(),post_count:Number(cells[offset+1].innerText),updated_raw:cells[offset+2].innerText.trim(),url:link.href}})"
            )
            matches = listing["boards"] == raw
            if not matches:
                pytest.fail("Course boards differ from source (payload suppressed)", pytrace=False)
            for board in listing["boards"]:
                result = await boards.fetch_posts(page, board["board_id"])
                raw = await page.locator("table.ubboard_table > tbody > tr").evaluate_all(
                    r"rows=>rows.filter(row=>row.children.length===5).map(row=>{const cells=[...row.children],link=cells[1].querySelector('a[href]');return link?{post_id:new URL(link.href).searchParams.get('bwid'),title:link.innerText.trim(),date_raw:cells[3].innerText.trim(),url:link.href}:null})"
                )
                expected = [record for record in raw if record is not None]
                matches = result["posts"] == expected and result["unlinked_count"] == raw.count(None)
                if not matches:
                    pytest.fail("Board posts differ from source (payload suppressed)", pytrace=False)
                linked_count += result["count"]
        if not linked_count:
            pytest.fail("Need linked posts to verify nonempty source fields", pytrace=False)

    session = get_session()
    try:
        await session.run(check)
    except Exception as exc:
        pytest.fail(f"Course board source verification: {type(exc).__name__}", pytrace=False)
    finally:
        await session.close()


@pytest.mark.live
@pytest.mark.asyncio
async def test_gradebook_copies_and_history_match_source() -> None:
    if os.getenv("RUN_LIVE_PORTAL") != "1":
        pytest.skip("set RUN_LIVE_PORTAL=1 for additional read source comparison")
    from yonsei_portal_mcp.scrapers import learnus, library
    from yonsei_portal_mcp.session import get_session, get_library_session

    async def gradebook(page):
        current = await learnus.fetch_courses(page)
        current_ids = {course["id"] for course in current}
        historical = [course for course in (await learnus.fetch_course_history(page))["courses"] if course["id"] not in current_ids]
        if not current or not historical:
            pytest.fail("Need current and historical courses for gradebook verification", pytrace=False)
        for course in (current[0], historical[0]):
            result = await learnus.fetch_gradebook(page, course["id"], include_feedback=True)
            raw = await page.locator("table.user-grade > tbody > tr:visible").evaluate_all(
                r"rows=>rows.map(row=>Object.fromEntries([...row.querySelectorAll(':scope > th,:scope > td')].flatMap(cell=>[...cell.classList].filter(name=>name.startsWith('column-')&&name!=='column-leader').map(name=>[name,cell.innerText.replace(/\s+/g,' ').trim()]))))"
            )
            matches = len(raw) == result["count"]
            columns = {"column-itemname": "name", "column-grade": "grade_raw", "column-weight": "weight_raw", "column-range": "range_raw", "column-percentage": "percentage_raw", "column-feedback": "feedback", "column-contributiontocoursetotal": "contribution_raw"}
            for source, item in zip(raw, result["items"]):
                matches = matches and all(item.get(field) == source[column] for column, field in columns.items() if column in source)
            if not matches:
                pytest.fail("Gradebook source fields mismatch (payload suppressed)", pytrace=False)

    async def library_reads(page):
        books = await library.fetch_book_search("인공지능", limit=1)
        catalog_id = urlsplit(books["results"][0]["url"]).path.rsplit("/", 1)[-1]
        details = await library.fetch_book_detail(catalog_id)
        await page.goto(details["source_url"], wait_until="domcontentloaded")
        await page.wait_for_selector("table.searchTable tbody tr")
        async def original_tables(selector):
            return await page.locator(selector).evaluate_all(
                r"tables=>tables.map(table=>({headers:[...table.querySelectorAll('thead th,thead td')].map(cell=>cell.innerText.replace(/\s/g,'')),rows:[...table.querySelectorAll('tbody tr')].map(row=>[...row.querySelectorAll('td')].map(cell=>cell.innerText.replace(/\s+/g,' ').trim()))}))"
            )
        fields = {"등록번호": "reg_no", "청구기호": "call_number", "소장처": "location", "도서상태": "status_raw", "반납예정일": "due_date_raw"}
        expected = []
        for table in await original_tables("table.searchTable"):
            expected.extend({field: row[table["headers"].index(header)] for header, field in fields.items()} for row in table["rows"])
        matches = expected == details["copies"]
        if not matches:
            pytest.fail("Book copies differ from browser fields (payload suppressed)", pytrace=False)
        for fetch, key, fields in (
            (library.fetch_loan_history, "loans", {"서명/저자": "title_author", "소장처": "location", "등록번호": "reg_no", "대출일": "loan_date", "반납일": "return_date", "반납유형": "return_type"}),
            (library.fetch_reservation_history, "reservations", {"서명/저자": "title_author", "소장처": "location", "예약순위": "queue_position", "예약일": "reservation_date", "도착통보일": "notification_date", "예약상태": "status"}),
        ):
            result = await fetch(page)
            table = next(table for table in await original_tables("table.mobileTable") if fields.keys() <= set(table["headers"]))
            rows = [row for row in table["rows"] if len(row) == len(table["headers"])]
            expected = [{field: row[table["headers"].index(header)] for header, field in fields.items()} for row in rows]
            matches = expected == result[key] and len(expected) == result["count"]
            if not matches:
                pytest.fail(f"{key} history source mismatch (payload suppressed)", pytrace=False)

    for session, action in ((get_session(), gradebook), (get_library_session(), library_reads)):
        try:
            await session.run(action)
        except Exception as exc:
            pytest.fail(f"Additional reads source comparison: {type(exc).__name__}", pytrace=False)
        finally:
            await session.close()


@pytest.mark.live
@pytest.mark.asyncio
async def test_library_fields_match_rendered_source() -> None:
    if os.getenv("RUN_LIVE_PORTAL") != "1":
        pytest.skip("set RUN_LIVE_PORTAL=1 for source comparison")
    from yonsei_portal_mcp.scrapers import library
    from yonsei_portal_mcp.session import get_library_session

    session = get_library_session()

    async def public_seats(page):
        from yonsei_portal_mcp.scrapers import seats as public

        await page.goto("https://library.yonsei.ac.kr/", wait_until="domcontentloaded")
        raw = await page.evaluate("async () => { const response = await fetch('/seat/info'); if (!response.ok) throw new Error('Seat HTTP error'); return response.json(); }")
        result = public._parse(raw)
        checks = []
        for row in result["rows"]:
            prefix = row["building_code"] + "_" + row["seat_type_code"]
            checks.extend([row["total"] == raw[prefix + "_total"], row["in_use"] == raw[prefix + "_use"], row["remaining"] == raw[prefix + "_total"] - raw[prefix + "_use"]])
        checks.append(result["remaining"] == sum(row["remaining"] for row in result["rows"]))
        if not all(checks):
            pytest.fail("Public seat source mismatch", pytrace=False)

    async def seats(page):
        result = await library.fetch_seat_rooms(page)
        rows = await page.locator("table.seatTbl tbody tr").evaluate_all(
            "rows => rows.map(row => [...row.querySelectorAll('td')].map(cell => cell.innerText.trim())).filter(row => row.length === 7)"
        )
        totals = [row for row in rows if row[0] == "합계"]
        source = [row for row in rows if row[0] != "합계"]
        checks = [len(source) == result["count"], len(totals) == 1]
        for row, room in zip(source, result["rooms"]):
            checks.extend([
                int(row[1].split("(")[0].replace(",", "")) == room["total"],
                int(row[2].replace(",", "")) == room["in_use"],
                int(row[3].replace(",", "")) == room["available"],
                row[0].endswith(("배정가능", "좌석배정")) == room["assignable"],
            ])
        checks.append(sum(int(row[3].replace(",", "")) for row in source if row[0].endswith(("배정가능", "좌석배정"))) == result["assignable_available"])
        if totals:
            checks.append(int(totals[0][3].replace(",", "")) == result["available"])
        if not all(checks):
            pytest.fail("Seat field/source total mismatch (payload suppressed)", pytrace=False)

    async def personal(page, fetch, key, mapping):
        result = await fetch(page)
        tables = await page.locator("table.mobileTable").evaluate_all(
            r"tables => tables.map(table => ({headers:[...table.querySelectorAll('thead th,thead td')].map(cell=>cell.innerText.replace(/\s/g,'')),rows:[...table.querySelectorAll('tbody tr')].map(row=>[...row.querySelectorAll('td')].map(cell=>cell.innerText.replace(/\s+/g,' ').trim()))}))"
        )
        table = next(table for table in tables if mapping.keys() <= set(table["headers"]))
        rows = [row for row in table["rows"] if len(row) == len(table["headers"])]
        expected = [{field: row[table["headers"].index(header)] for header, field in mapping.items()} for row in rows]
        valid = expected == result[key] and len(expected) == result["count"]
        if not valid:
            pytest.fail(f"{key}: source field mismatch (payload suppressed)", pytrace=False)

    try:
        await session.run(public_seats)
        await session.run(seats)
        await session.run(lambda page: personal(page, library.fetch_my_loans, "loans", {
            "서명/저자": "title_author", "소장처": "location", "등록번호": "reg_no",
            "대출일": "loan_date", "반납예정일": "due_date", "연체료": "overdue_fee", "연장횟수": "renew_count",
        }))
        await session.run(lambda page: personal(page, library.fetch_my_reservations, "reservations", {
            "서명/저자": "title_author", "소장처": "location", "예약순위": "queue_position",
            "예약일": "reservation_date", "도착통보일": "notification_date", "예약상태": "status",
        }))
    except Exception as exc:
        pytest.fail(f"Library source comparison: {type(exc).__name__} (payload suppressed)", pytrace=False)
    finally:
        await session.close()


@pytest.mark.live
@pytest.mark.asyncio
async def test_academic_details_match_source() -> None:
    if os.getenv("RUN_LIVE_PORTAL") != "1":
        pytest.skip("set RUN_LIVE_PORTAL=1 for academic source comparison")
    from yonsei_portal_mcp.scrapers import erp, learnus
    from yonsei_portal_mcp.session import get_erp_session, get_session

    async def grades(page):
        async with page.expect_response(lambda response: urlsplit(response.url).path == "/sch/sgra/SgrargCtr/findAllGradeDtlAsSyySmtList.do") as pending:
            result = await erp.fetch_grades(page)
        raw = await (await pending.value).json()
        source = raw["dsSgra100"]
        matches = len(source) == result["count"]
        for original, course in zip(source, result["courses"]):
            matches = matches and (
                course["course_code"] == original["subjtnb"]
                and course["course_name"] == original["subjtNm"]
                and course["credits"] == original["cmpsjCdt"]
                and course["year"] == str(original["syy"])
                and course["term_code"] == str(original["smtDivCd"])
            )
        info = raw.get("dsStdntInfo") or []
        if info:
            matches = matches and result["summary"]["total_earned_credits"] == info[0].get("acqsCdt") and result["summary"]["gpa"] == info[0].get("bwa")
        if not matches:
            pytest.fail("Grade source fields mismatch (payload suppressed)", pytrace=False)

    async def assignment(page):
        for course in (await learnus.fetch_course_history(page))["courses"]:
            candidates = learnus.assignments_from_materials(await learnus.fetch_course_materials(page, course["id"]))["assignments"]
            if not candidates:
                continue
            assignment_id = parse_qs(urlsplit(candidates[0]["url"]).query)["id"][0]
            result = await learnus.fetch_assignment_status(page, assignment_id)
            original = await page.locator(".submissionstatustable tr").evaluate_all(
                "rows=>Object.fromEntries(rows.map(row=>[...row.querySelectorAll('td,th')].map(cell=>cell.innerText.trim())))"
            )
            matches = (
                result["submission_status_raw"] == original["제출 여부"]
                and result["grading_status_raw"] == original.get("채점 상황")
                and result["due_raw"] == original.get("종료 일시")
            )
            if not matches:
                pytest.fail("Assignment source fields mismatch (payload suppressed)", pytrace=False)
            return
        pytest.fail("No accessible assignment for source comparison", pytrace=False)

    for session, action in ((get_erp_session(), grades), (get_session(), assignment)):
        try:
            await session.run(action)
        except Exception as exc:
            pytest.fail(f"Academic source comparison: {type(exc).__name__}", pytrace=False)
        finally:
            await session.close()


@pytest.mark.live
@pytest.mark.asyncio
async def test_public_academic_calendar_matches_browser() -> None:
    if os.getenv("RUN_LIVE_PORTAL") != "1":
        pytest.skip("set RUN_LIVE_PORTAL=1 for public calendar source comparison")
    from playwright.async_api import async_playwright
    from yonsei_portal_mcp.scrapers.academic import CALENDAR_URL, parse_calendar

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.goto(CALENDAR_URL, wait_until="domcontentloaded")
            await page.wait_for_selector("#timeTableList .box-sch .desc dl")
            result = parse_calendar(await page.content())
            raw = await page.locator("#timeTableList .box-sch").evaluate_all(
                r"boxes => boxes.map(box => ({month:parseInt(box.querySelector('.num h3 span').innerText), events:[...box.querySelectorAll('.desc dl')].map(row=>({date_raw:row.querySelector('dt').textContent.replace(/\s+/g,' ').trim(), title:row.querySelector('dd').textContent.replace(/\s+/g,' ').trim()}))}))"
            )
            parsed = [{"month": month["month"], "events": month["events"]} for month in result["months"]]
            matches = raw == parsed
            assert matches, "Public academic calendar differs from browser source"
        finally:
            await browser.close()


@pytest.mark.live
@pytest.mark.asyncio
async def test_course_history_displayed_result_matches_filter_union() -> None:
    if os.getenv("RUN_LIVE_PORTAL") != "1":
        pytest.skip("set RUN_LIVE_PORTAL=1 for bounded course history comparison")
    import logging

    from yonsei_portal_mcp.scrapers import learnus
    from yonsei_portal_mcp.session import get_session

    calls = 0
    summaries = []

    def require(condition, message):
        if not condition:
            pytest.fail(message + " (payload suppressed)", pytrace=False)

    async def check(page):
        nonlocal calls

        async def read(year=None, semester="all"):
            nonlocal calls
            require(calls < 11, "History comparison query budget exceeded")
            calls += 1
            result = await learnus.fetch_course_history(page, year=year, semester=semester)
            source = await page.evaluate("""() => ({
                filters: Object.fromEntries([...document.querySelectorAll('select[name="year"],select[name="semester"]')]
                    .map(select => [select.name, {value:select.value, options:[...select.options]
                        .filter(option => !option.disabled).map(option => ({value:option.value,label:option.textContent.trim()}))}])),
                rows: [...document.querySelectorAll('table.table-coursemos > tbody > tr')]
                    .filter(row => row.children.length === 3).map(row => ({
                        year:row.children[0].innerText.trim(), semester:row.children[1].innerText.trim(),
                        id:new URL(row.children[2].querySelector('a[href]').href).searchParams.get('id')})),
                paging: [...document.querySelectorAll('.pagination,.paging,[rel="next"],[rel="prev"],[name="page"],[name="pageNo"],a[href*="page="],a[href*="pageNo="]')]
                    .map(node => ({hidden:!node.getClientRects().length}))
            })""")
            filters = source["filters"]
            require(filters["year"]["value"] == str(year if year is not None else "all")
                    and filters["semester"]["value"] == semester, "History selected filters mismatch")
            records = [{key: course[key] for key in ("year", "semester", "id")} for course in result["courses"]]
            require(records == source["rows"] and result["count"] == len(records), "History rows differ from displayed DOM")
            ids = {row["id"] for row in source["rows"]}
            duplicates = len(source["rows"]) - len(ids)
            require(duplicates == 0, "Duplicate history IDs in displayed DOM")
            require(not source["paging"], "History has visible or hidden paging controls")
            semester_label = next(option["label"] for option in filters["semester"]["options"] if option["value"] == semester)
            require(all((year is None or row["year"] == str(year))
                        and (semester == "all" or row["semester"] == semester_label)
                        for row in source["rows"]), "History row terms differ from selected filters")
            require(result["scope"] == "displayed_result" and result["filters_verified"] is True
                    and result["has_next"] is None and result["pagination_supported"] is False,
                    "History scope metadata overstates source evidence")
            summaries.append({"year": year if year is not None else "all", "semester": semester,
                              "count": len(ids), "duplicates": duplicates,
                              "paging_controls": len(source["paging"]),
                              "hidden_paging_controls": sum(control["hidden"] for control in source["paging"])})
            return ids, source

        all_ids, source = await read()
        years = [option["value"] for option in source["filters"]["year"]["options"] if option["value"] != "all"]
        semesters = [option for option in source["filters"]["semester"]["options"] if option["value"] != "all"]
        require(bool(all_ids) and bool(years) and 0 < len(semesters) <= 4,
                "Need nonempty history and bounded advertised filters")
        require(all(option["value"] in {"10", "11", "20", "21"} for option in semesters),
                "Source advertises an unsupported semester")
        semester_union = set()
        for option in semesters:
            ids, _ = await read(semester=option["value"])
            expected = {row["id"] for row in source["rows"] if row["semester"] == option["label"]}
            require(ids == expected, "All-years semester result differs from all/all subset")
            semester_union.update(ids)
        require(semester_union == all_ids, "All/all differs from advertised semester union")

        populated_years = {row["year"] for row in source["rows"]}
        require(populated_years <= set(years), "Displayed year absent from advertised choices")
        selected_year = max(populated_years, key=int)
        year_union = set()
        for option in semesters:
            ids, _ = await read(year=int(selected_year), semester=option["value"])
            expected = {row["id"] for row in source["rows"]
                        if row["year"] == selected_year and row["semester"] == option["label"]}
            require(ids == expected, "Year/semester result differs from all/all subset")
            year_union.update(ids)
        require(year_union == {row["id"] for row in source["rows"] if row["year"] == selected_year},
                "Year semester union differs from all/all subset")
        previous_year = next((year for year in years if int(year) < int(selected_year)), None)
        if previous_year is not None:
            ids, _ = await read(year=int(previous_year))
            require(ids == {row["id"] for row in source["rows"] if row["year"] == previous_year},
                    "Previous-year result differs from all/all subset")

        require(calls < 11, "No budget remaining for current-course comparison")
        calls += 1
        current_ids = {course["id"] for course in await learnus.fetch_courses(page)}
        print(json.dumps({"calls": calls, "all_count": len(all_ids), "semester_union_count": len(semester_union),
                          "current_count": len(current_ids), "current_in_history": len(current_ids & all_ids),
                          "current_not_in_history": len(current_ids - all_ids),
                          "all_current_in_history": current_ids <= all_ids,
                          "selected_filters_and_rows_match": True, "results": summaries}), flush=True)
        require(bool(current_ids), "Need current courses for history overlap comparison")

    async def guarded_check(page):
        try:
            await check(page)
        except Exception as exc:
            pytest.fail(f"History source comparison: {type(exc).__name__} (payload suppressed)", pytrace=False)

    session = get_session()
    previous_logging = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        await session.run(guarded_check)
    except Exception as exc:
        pytest.fail(f"History session: {type(exc).__name__} (payload suppressed)", pytrace=False)
    finally:
        try:
            await session.close()
        finally:
            logging.disable(previous_logging)
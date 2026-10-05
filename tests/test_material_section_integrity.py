"""Offline Chromium regressions for course-section ownership and identity."""
from __future__ import annotations

import pytest
from playwright.async_api import async_playwright

from yonsei_portal_mcp.errors import ScrapeFailedError
from yonsei_portal_mcp.scrapers import learnus


@pytest.fixture
async def material_page():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        context = await browser.new_context(service_workers="block")
        await context.route("**/*", lambda route: route.abort())
        try:
            yield await context.new_page()
        finally:
            await context.close()
            await browser.close()


def activity(identifier="101", *, title="Report", url_id=None):
    return (
        f'<li class="activity modtype_assign" id="module-{identifier}">'
        f'<a href="/mod/assign/view.php?id={url_id or identifier}">'
        f'<span class="instancename">{title}<span class="accesshide">과제</span></span>'
        '</a></li>'
    )


def section(identifier="1", *, contents=None, attributes="", name="1주차"):
    return (
        f'<li class="section main" id="section-{identifier}" {attributes}>'
        f'<h3 class="sectionname">{name}</h3>'
        f'<ul>{activity() if contents is None else contents}</ul></li>'
    )


def course(contents):
    return f'<div class="course-content"><ul>{contents}</ul></div>'


async def read_materials(page, html):
    url = learnus._korean_url(learnus.COURSE_VIEW_URL.format(course_id="123"))
    await page.context.route(
        url, lambda route: route.fulfill(
            status=200, content_type="text/html; charset=utf-8", body=f'<html lang="ko">{html}</html>',
        ),
    )
    return await learnus.fetch_course_materials(page, "123")


def assert_assignment_counts(result, expected):
    assert result["section_count"] == len(result["sections"])
    assert result["activity_count"] == sum(len(s["activities"]) for s in result["sections"]) == expected
    assignments = learnus.assignments_from_materials(result)
    assert assignments["count"] == len(assignments["assignments"]) == expected
    return assignments["assignments"]


@pytest.mark.asyncio
async def test_sections_outside_course_content_are_not_materials(material_page):
    result = await read_materials(material_page, course(section()) + '<aside><ul>' + section("9", contents=activity("999")) + '</ul></aside>')
    assert_assignment_counts(result, 1)
    assert [s["id"] for s in result["sections"]] == ["section-1"]


@pytest.mark.asyncio
async def test_nested_section_activity_belongs_only_to_nearest_section(material_page):
    html = course(section("1", contents=section("2", contents=activity("202"), name="2주차")))
    result = await read_materials(material_page, html)
    assignments = assert_assignment_counts(result, 1)
    assert result["sections"][0]["activities"] == []
    assert assignments[0]["week"] == 2
    assert assignments[0]["section"] == "2주차"


@pytest.mark.asyncio
async def test_parent_section_does_not_borrow_nested_heading(material_page):
    html = course(section("1", contents=section("2", contents=activity("202"), name="2주차")))
    html = html.replace('<h3 class="sectionname">1주차</h3>', '')
    result = await read_materials(material_page, html)
    assert_assignment_counts(result, 1)
    assert [s["id"] for s in result["sections"]] == ["section-2"]


@pytest.mark.asyncio
@pytest.mark.parametrize("hide", ['hidden', 'style="display:none"', 'style="visibility:hidden"'])
@pytest.mark.parametrize("separate_root", [False, True])
async def test_identical_responsive_section_clone_counted_once(material_page, hide, separate_root):
    clone = section(attributes=hide)
    html = course(clone) + course(section()) if separate_root else course(clone + section())
    result = await read_materials(material_page, html)
    assert_assignment_counts(result, 1)
    assert result["section_count"] == 1
    assert result["sections"][0]["name"] == "1주차"


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["name", "url", "title", "missing_activity"])
async def test_conflicting_section_id_fails_closed_even_when_hidden(material_page, change):
    clones = {
        "name": section(name="Different section", attributes="hidden"),
        "url": section(contents=activity(url_id="999"), attributes="hidden"),
        "title": section(contents=activity(title="Different task"), attributes="hidden"),
        "missing_activity": section(contents="", attributes="hidden"),
    }
    with pytest.raises(ScrapeFailedError, match="중복"):
        await read_materials(material_page, course(clones[change] + section()))


@pytest.mark.asyncio
async def test_identical_activity_id_clone_in_one_section_counted_once(material_page):
    contents = activity() + '<div hidden><ul>' + activity() + '</ul></div>'
    result = await read_materials(material_page, course(section(contents=contents)))
    assert_assignment_counts(result, 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["url", "title", "type", "owner"])
async def test_conflicting_activity_id_fails_closed(material_page, change):
    clones = {
        "url": activity(url_id="999"),
        "title": activity(title="Changed task"),
        "type": activity().replace("modtype_assign", "modtype_quiz"),
        "owner": activity(),
    }
    html = (course(section() + section("2", contents=clones[change], name="2주차"))
            if change == "owner" else course(section(contents=activity() + clones[change])))
    with pytest.raises(ScrapeFailedError, match="중복"):
        await read_materials(material_page, html)


# Preservation cases intentionally pass before further changes: identity must
# never be inferred from matching titles, inferred weeks, URLs or visibility.
@pytest.mark.asyncio
async def test_selector_union_selects_one_dom_node_once(material_page):
    result = await read_materials(material_page, course(section()))
    assert_assignment_counts(result, 1)
    assert result == {
        "course_id": "123", "section_count": 1, "activity_count": 1,
        "sections": [{"id": "section-1", "week": 1, "name": "1주차", "activities": [
            {"type": "assign", "title": "Report", "url": "https://ys.learnus.org/mod/assign/view.php?id=101"},
        ]}],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("same_url", [False, True])
async def test_same_titles_and_weeks_with_distinct_activity_ids_survive(material_page, same_url):
    result = await read_materials(material_page, course(
        section(contents=activity("101") + activity("102", url_id="101" if same_url else "102"))
        + section("2", contents=activity("103")),
    ))
    assignments = assert_assignment_counts(result, 3)
    assert [s["id"] for s in result["sections"]] == ["section-1", "section-2"]
    assert [s["week"] for s in result["sections"]] == [1, 1]
    assert [a["title"] for a in assignments] == ["Report"] * 3
    assert assignments[-1]["url"].endswith("id=103")


@pytest.mark.asyncio
@pytest.mark.parametrize("hidden_part", ["section", "activities", "course"])
async def test_collapsed_course_content_is_not_discarded(material_page, hidden_part):
    html = course(section(attributes='hidden' if hidden_part == "section" else ""))
    if hidden_part == "activities":
        html = html.replace('<ul><li class="activity', '<ul style="display:none"><li class="activity')
    if hidden_part == "course":
        html = '<div style="display:none">' + html + '</div>'
    result = await read_materials(material_page, html)
    assignments = assert_assignment_counts(result, 1)
    assert assignments[0]["section"] == "1주차"
    assert assignments[0]["title"] == "Report"


@pytest.mark.asyncio
async def test_unidentified_same_title_activities_are_not_guessed_to_be_clones(material_page):
    contents = (activity() + activity()).replace(' id="module-101"', '')
    result = await read_materials(material_page, course(section(contents=contents)))
    assert_assignment_counts(result, 2)


@pytest.mark.asyncio
async def test_unidentified_same_named_sections_remain_distinct(material_page):
    html = course(section(contents=activity("101")) + section(contents=activity("102")))
    result = await read_materials(material_page, html.replace(' id="section-1"', ''))
    assert_assignment_counts(result, 2)
    assert result["section_count"] == 2


@pytest.mark.asyncio
async def test_outside_section_cannot_establish_ready_course(material_page):
    await material_page.set_content('<aside><ul>' + section() + '</ul></aside>')
    assert await material_page.evaluate(learnus._MATERIALS_JS) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["section_clone", "section_conflict", "activity_clone", "activity_conflict", "owner_conflict"])
async def test_python_parser_validates_identity_before_counting(monkeypatch, kind):
    from copy import deepcopy
    from typing import cast
    from unittest.mock import AsyncMock
    from playwright.async_api import Page

    page = cast(Page, object())  # The raw-read seam is replaced, not browser JS.
    raw_activity = {"id": "module-101", "mod": "assign", "title": "Report", "url": "https://ys.learnus.org/mod/assign/view.php?id=101"}
    raw_section = {"id": "section-1", "name": "1주차", "activities": [raw_activity]}
    raw = [deepcopy(raw_section)]
    if kind.startswith("section") or kind == "owner_conflict":
        raw.append(deepcopy(raw_section))
        if kind == "section_conflict":
            raw[-1]["name"] = "Conflicting name"
        if kind == "owner_conflict":
            raw[-1]["id"] = "section-2"
    else:
        raw[0]["activities"].append(deepcopy(raw_activity))
        if kind == "activity_conflict":
            raw[0]["activities"][-1]["url"] += "&different=1"
    original = deepcopy(raw)
    monkeypatch.setattr(learnus, "_read_ready_page", AsyncMock(return_value=raw))
    if kind.endswith("conflict"):
        with pytest.raises(ScrapeFailedError, match="중복"):
            await learnus.fetch_course_materials(page, "123")
    else:
        assert_assignment_counts(await learnus.fetch_course_materials(page, "123"), 1)
    assert raw == original

"""Offline Chromium regressions for nested activity metadata ownership."""
from __future__ import annotations

import pytest

from tests.test_material_section_integrity import (
    activity,
    course,
    material_page as _material_page,
    read_materials,
    section,
)

material_page = _material_page


@pytest.mark.asyncio
@pytest.mark.parametrize("other_section", [False, True])
async def test_empty_outer_label_cannot_borrow_nested_metadata(material_page, other_section):
    nested = activity("202")
    if other_section:
        nested = section("2", contents=nested, name="2주차")
    outer = '<li class="activity modtype_label" id="module-outer"><ul>' + nested + '</ul></li>'
    result = await read_materials(material_page, course(section(contents=outer)))

    assert result["activity_count"] == 1
    assert result["section_count"] == (2 if other_section else 1)
    assert result["sections"][0]["activities"] == ([] if other_section else [{
        "type": "assign", "title": "Report",
        "url": "https://ys.learnus.org/mod/assign/view.php?id=202",
    }])
    assert result["sections"][-1]["activities"] == [{
        "type": "assign", "title": "Report",
        "url": "https://ys.learnus.org/mod/assign/view.php?id=202",
    }]


@pytest.mark.asyncio
@pytest.mark.parametrize("other_section", [False, True])
@pytest.mark.parametrize("field", ["title", "type_label", "fallback"])
async def test_owned_metadata_text_excludes_nested_owners(material_page, other_section, field):
    from yonsei_portal_mcp.scrapers import learnus

    nested = activity("202", title="Nested report")
    # No nested anchor: Chromium must retain the outer fallback link as authored.
    nested = nested.replace('<a href="/mod/assign/view.php?id=202">', '').replace('</a>', '')
    if other_section:
        nested = section("2", contents=nested, name="2주차")
    nested = '<ul>' + nested + '</ul>'
    metadata = {
        "title": '<div class="instancename">Own title' + nested
                 + '<span class="accesshide">Own type</span></div>',
        "type_label": '<div class="instancename">Own title'
                      + '<div class="accesshide">Own type' + nested + '</div></div>',
        "fallback": '<a href="/mod/label/view.php?id=101">Own title' + nested + '</a>',
    }[field]
    outer = '<li class="activity modtype_label" id="module-outer">' + metadata + '</li>'
    result = await read_materials(material_page, course(section(contents=outer)))
    raw = await material_page.evaluate(learnus._MATERIALS_JS)

    assert result["sections"][0]["activities"][0] == {
        "type": "label", "title": "Own title",
        "url": "https://ys.learnus.org/mod/label/view.php?id=101" if field == "fallback" else None,
    }
    assert raw[0]["activities"][0]["type_label"] == (None if field == "fallback" else "Own type")
    assert result["activity_count"] == 2
    assert result["sections"][-1]["activities"][-1] == {
        "type": "assign", "title": "Nested report", "url": None,
    }


# Preservation cases: genuine metadata and existing fallbacks remain readable.
@pytest.mark.asyncio
@pytest.mark.parametrize("other_section", [False, True])
async def test_genuine_metadata_after_nested_activity_is_preserved(material_page, other_section):
    nested = activity("202", title="Nested report")
    if other_section:
        nested = section("2", contents=nested, name="2주차")
    outer = activity("101", title="Own report").replace(
        '<a href=', '<ul>' + nested + '</ul><a href=', 1,
    )
    result = await read_materials(material_page, course(section(contents=outer)))
    assert result["activity_count"] == 2
    assert result["sections"][0]["activities"][0] == {
        "type": "assign", "title": "Own report",
        "url": "https://ys.learnus.org/mod/assign/view.php?id=101",
    }
    assert result["sections"][-1]["activities"][-1] == {
        "type": "assign", "title": "Nested report",
        "url": "https://ys.learnus.org/mod/assign/view.php?id=202",
    }


@pytest.mark.asyncio
async def test_section_only_boundary_cannot_supply_outer_metadata(material_page):
    nested = '<div class="section main"><a href="/mod/assign/view.php?id=202">' \
             '<span class="instancename">Not owned</span></a></div>'
    outer = '<li class="activity modtype_label" id="module-outer">' + nested + '</li>'
    result = await read_materials(material_page, course(section(contents=outer)))
    assert result["activity_count"] == 0
    assert result["sections"][0]["activities"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(("metadata", "title", "url"), [
    ('<span class="instancename"> Plain <b>own</b> title </span>', 'Plain own title', None),
    ('<a href="/own#fragment"> Plain <b>link</b> title </a>', 'Plain link title',
     'https://ys.learnus.org/own'),
    ('<span class="instancename"></span><a href="/own">Fallback title</a>', 'Fallback title',
     'https://ys.learnus.org/own'),
    ('<a href="/own">Visible<span hidden>Hidden</span> title</a>', 'Visible title',
     'https://ys.learnus.org/own'),
    ('<a href="/own"></a>', '', 'https://ys.learnus.org/own'),
])
async def test_plain_own_metadata_and_link_fallback_are_preserved(material_page, metadata, title, url):
    outer = '<li class="activity modtype_label" id="module-outer">' + metadata + '</li>'
    result = await read_materials(material_page, course(section(contents=outer)))
    assert result["activity_count"] == 1
    assert result["sections"][0]["activities"] == [{"type": "label", "title": title, "url": url}]

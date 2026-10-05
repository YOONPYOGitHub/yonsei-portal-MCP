"""Offline timetable regressions using only non-private cell labels/classes."""
from __future__ import annotations

import pytest

from yonsei_portal_mcp.errors import ScrapeFailedError
from yonsei_portal_mcp.scrapers.facilities import parse_timeline


@pytest.fixture
def observed_shape_cells():
    """Reconstruct the sanitized 09–21/30-minute DOM shape, without account data."""
    cells = []
    for minute in range(9 * 60, 21 * 60 + 1, 30):
        classes = []
        if minute <= 13 * 60:
            classes.append("past")
        elif 19 * 60 <= minute < 21 * 60:
            classes.append("use")
        if minute % 60 == 0:
            classes.append("times")
        cells.append({"label": str(minute // 60) if minute % 60 == 0 else "", "classes": classes})
    return cells


def test_observed_past_cells_preserve_raw_marks_and_true_slot_count(observed_shape_cells):
    slots = parse_timeline(observed_shape_cells, 30)

    assert len(slots) == (21 - 9) * 60 // 30
    assert slots[0]["start"] == "09:00"
    assert slots[-1]["end"] == "21:00"
    for slot, cell in zip(slots, observed_shape_cells[:-1]):
        used, past = "use" in cell["classes"], "past" in cell["classes"]
        assert slot["used_mark"] is used
        assert slot["past_mark"] is past
        assert slot["display_status"] == ("과거 표시" if past else "사용 표시" if used else "표시 없음")
        assert set(slot) == {"start", "end", "used_mark", "past_mark", "display_status"}


@pytest.mark.parametrize("classes", [["use", "past"], ["past", "times", "use"]])
def test_overlapping_use_and_past_marks_both_remain_visible(classes):
    cells = [{"label": "9", "classes": classes}, {"label": "10", "classes": ["times"]}]

    assert parse_timeline(cells, 60) == [{
        "start": "09:00", "end": "10:00", "used_mark": True, "past_mark": True,
        "display_status": "사용 표시 · 과거 표시",
    }]


@pytest.mark.parametrize("classes,used,past,status", [
    ([], False, False, "표시 없음"),
    (["times"], False, False, "표시 없음"),
    (["use"], True, False, "사용 표시"),
    (["times", "use"], True, False, "사용 표시"),
    (["past"], False, True, "과거 표시"),
    (["past", "times"], False, True, "과거 표시"),
])
def test_raw_mark_combinations_never_claim_availability(classes, used, past, status):
    cells = [{"label": "9", "classes": classes}, {"label": "10", "classes": ["times"]}]
    assert parse_timeline(cells, 60) == [{
        "start": "09:00", "end": "10:00", "used_mark": used,
        "past_mark": past, "display_status": status,
    }]


@pytest.mark.parametrize("classes", [[], ["past"], ["past", "times"], ["past", "use", "times"]])
def test_end_cell_is_validated_but_never_returned_as_a_slot(classes):
    cells = [{"label": "23", "classes": ["times"]}, {"label": "24", "classes": classes}]
    assert parse_timeline(cells, 60) == [{
        "start": "23:00", "end": "24:00", "used_mark": False,
        "past_mark": False, "display_status": "표시 없음",
    }]


@pytest.mark.parametrize("unknown", ["unknown", "past-tense", "pastExtra", "Past", "PAST", " past", "past ", "disable", "available", "ng-past"])
@pytest.mark.parametrize("index", [0, 1, 2])
def test_unknown_classes_still_fail_even_alongside_past(unknown, index):
    cells = [{"label": "9", "classes": ["past", "times"]},
             {"label": "", "classes": ["past"]},
             {"label": "10", "classes": ["times"]}]
    cells[index]["classes"].append(unknown)
    with pytest.raises(ScrapeFailedError, match="시간 또는 상태 표시"):
        parse_timeline(cells, 30)


@pytest.mark.parametrize("unit", [True, False, 0, -1, 7, 25, 61, 30.0, "30", None])
def test_past_does_not_relax_unit_validation(observed_shape_cells, unit):
    with pytest.raises(ScrapeFailedError, match="구간 단위"):
        parse_timeline(observed_shape_cells, unit)


@pytest.mark.parametrize("unit", [1, 2, 3, 4, 5, 6, 10, 12, 15, 20, 30, 60])
def test_valid_units_keep_exact_intervals_and_exclude_end_cell(unit):
    cells = [{"label": str(minute // 60) if minute % 60 == 0 else "",
              "classes": ["past", "times"] if minute % 60 == 0 else ["past"]}
             for minute in range(9 * 60, 10 * 60 + 1, unit)]
    slots = parse_timeline(cells, unit)
    assert len(slots) == 60 // unit == len(cells) - 1
    for index, slot in enumerate(slots):
        start, end = 9 * 60 + index * unit, 9 * 60 + (index + 1) * unit
        assert slot["start"] == f"{start // 60:02d}:{start % 60:02d}"
        assert slot["end"] == f"{end // 60:02d}:{end % 60:02d}"
        assert slot["past_mark"] is True and slot["used_mark"] is False


@pytest.mark.parametrize("index,label", [(0, "09"), (0, "９"), (0, ""), (0, "25"), (1, "9"), (2, "11"), (-1, "20"), (-1, "25"), (-1, "")])
def test_past_does_not_relax_time_labels(observed_shape_cells, index, label):
    observed_shape_cells[index]["label"] = label
    with pytest.raises(ScrapeFailedError):
        parse_timeline(observed_shape_cells, 30)


@pytest.mark.parametrize("change", ["missing", "extra", "wrong_unit"])
def test_past_does_not_relax_cell_count(observed_shape_cells, change):
    if change == "missing":
        observed_shape_cells.pop(1)
    elif change == "extra":
        observed_shape_cells.insert(1, {"label": "", "classes": ["past"]})
    with pytest.raises(ScrapeFailedError, match="구간 수"):
        parse_timeline(observed_shape_cells, 60 if change == "wrong_unit" else 30)

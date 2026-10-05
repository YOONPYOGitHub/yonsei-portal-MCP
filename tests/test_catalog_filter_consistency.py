"""Deterministic ERP scope regressions; no browser or live source required."""
from copy import deepcopy
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from yonsei_portal_mcp.errors import ScrapeFailedError
from yonsei_portal_mcp.scrapers import erp


FILTERS = {"year": "2026", "term_code": "20", "campus_code": "s3"}
SOURCE_KEYS = {"year": "syy", "term_code": "smtDivCd", "campus_code": "campsBusnsCd"}


def catalog_row(**changes):
    return {
        "subjtnb": "TEST101", "subjtNm": "Synthetic AI", "corseDvclsNo": "01",
        "syy": "2026", "smtDivCd": "20", "campsBusnsCd": "s3", **changes,
    }


@pytest.mark.parametrize(("key", "actual"), [
    ("year", "2025"), ("term_code", "10"), ("campus_code", "s1"),
])
def test_default_disagreement_retains_rows_but_never_claims_verified_scope(key, actual):
    row = catalog_row(**{SOURCE_KEYS[key]: actual})
    payload = {"dsSles251": [row]}
    original = deepcopy(payload)
    result = erp.parse_course_catalog(payload, "AI", 20, FILTERS)

    assert result["filters"] == FILTERS
    assert result["filters_scope"] == "source_request"
    assert result["requested_filters"] == {}
    assert result["courses"][0][key] == actual
    assert result["observed_scope"][key] == [actual]
    assert result["filter_consistency"]["scope"] == "fetched_rows"
    assert result["filter_consistency"]["fields"][key] == {
        "expected": FILTERS[key], "origin": "source", "status": "mismatch",
        "mismatch_count": 1, "missing_count": 0,
    }
    assert result["warnings"]
    assert result["excluded_count"] == 0
    assert result["result_status"] == "ok"
    assert payload == original


@pytest.mark.parametrize("key", SOURCE_KEYS)
@pytest.mark.parametrize("missing", ["absent", None, "", " "])
def test_missing_default_row_scope_is_unverified_without_inventing_values(key, missing):
    row = catalog_row()
    if missing == "absent":
        del row[SOURCE_KEYS[key]]
    else:
        row[SOURCE_KEYS[key]] = missing
    result = erp.parse_course_catalog({"dsSles251": [row]}, "AI", 20, FILTERS)

    assert result["count"] == 1
    assert result["observed_scope"][key] == ([] if missing == "absent" else [missing])
    assert result["filter_consistency"]["fields"][key] == {
        "expected": FILTERS[key], "origin": "source", "status": "unverified",
        "mismatch_count": 0, "missing_count": 1,
    }
    assert result["warnings"]


@pytest.mark.parametrize("key", SOURCE_KEYS)
@pytest.mark.parametrize("missing", ["absent", None, "", " "])
def test_missing_source_condition_does_not_infer_a_default_from_rows(key, missing):
    filters = dict(FILTERS)
    if missing == "absent":
        del filters[key]
    else:
        filters[key] = missing
    result = erp.parse_course_catalog({"dsSles251": [catalog_row()]}, "AI", 20, filters)

    assert result["filters"] == filters
    assert result["observed_scope"][key] == [FILTERS[key]]
    assert result["filter_consistency"]["fields"][key] == {
        "expected": None if missing == "absent" else missing,
        "origin": "unspecified" if missing == "absent" else "source",
        "status": "unverified", "mismatch_count": 0, "missing_count": 0,
    }
    assert result["warnings"]


@pytest.mark.parametrize("fetched", [0, 1, 200])
def test_explicit_zero_matches_are_not_reported_as_no_source_data(fetched):
    rows = [catalog_row(syy="2025") for _ in range(fetched)]
    result = erp.parse_course_catalog(
        {"dsSles251": rows}, "AI", 1, FILTERS, requested_filters={"year": 2026},
    )
    assert result["result_status"] == ("source_empty" if fetched == 0 else "no_matching_rows")
    assert result["count"] == result["matching_count"] == 0
    assert result["fetched_count"] == result["excluded_count"] == fetched
    assert result["truncated"] is (fetched >= 200)
    if fetched:
        assert any("제외" in warning for warning in result["warnings"])
        assert result["filter_consistency"]["fields"]["year"]["mismatch_count"] == fetched
    else:
        assert all(field["status"] == "unverified" for field in result["filter_consistency"]["fields"].values())
        assert result["observed_scope"] == {key: [] for key in SOURCE_KEYS}


@pytest.mark.parametrize("key", SOURCE_KEYS)
@pytest.mark.parametrize("missing", ["absent", None, "", " ", [], {}, True])
def test_explicit_scope_requires_verifiable_fields_even_beyond_limit(key, missing):
    row = catalog_row()
    if missing == "absent":
        del row[SOURCE_KEYS[key]]
    else:
        row[SOURCE_KEYS[key]] = missing
    with pytest.raises(ScrapeFailedError, match="필터 검증"):
        erp.parse_course_catalog(
            {"dsSles251": [catalog_row(), row]}, "AI", 1, FILTERS,
            requested_filters={key: FILTERS[key]},
        )


@pytest.mark.parametrize("key", SOURCE_KEYS)
@pytest.mark.parametrize("value", [[], {}, True, 2026.0])
def test_unsupported_default_scope_types_are_not_certified_by_equal_values(key, value):
    filters = {**FILTERS, key: value}
    row = catalog_row(**{SOURCE_KEYS[key]: value})
    result = erp.parse_course_catalog({"dsSles251": [row]}, "AI", 20, filters)
    assert result["filters"][key] == value
    assert result["courses"][0][key] == value
    assert result["observed_scope"][key] == [value]
    assert result["filter_consistency"]["fields"][key]["status"] == "unverified"
    assert result["filter_consistency"]["fields"][key]["missing_count"] == 1
    assert result["warnings"]


@pytest.mark.parametrize(("requested", "expected_codes"), [
    ({}, ["OLD", "PARTIAL", "MATCH"]),
    ({"year": 2026, "term_code": None}, ["PARTIAL", "MATCH"]),
    ({"year": 2026, "term_code": "20", "campus_code": "s3"}, ["MATCH"]),
])
@pytest.mark.parametrize("limit", [1, 2, 20])
def test_mixed_scopes_apply_only_explicit_filters_before_limit(requested, expected_codes, limit):
    rows = [
        catalog_row(subjtnb="OLD", syy="2025"),
        catalog_row(subjtnb="PARTIAL", smtDivCd="10", campsBusnsCd="s1"),
        catalog_row(subjtnb="MATCH"),
    ]
    result = erp.parse_course_catalog(
        {"dsSles251": rows}, "AI", limit, FILTERS, requested_filters=requested,
    )
    assert [row["course_code"] for row in result["courses"]] == expected_codes[:limit]
    assert result["fetched_count"] == 3
    assert result["matching_count"] == len(expected_codes)
    assert result["count"] == min(limit, len(expected_codes))
    assert result["excluded_count"] == 3 - len(expected_codes)
    assert result["truncated"] is (len(expected_codes) > limit)
    assert result["observed_scope"] == {
        "year": ["2025", "2026"], "term_code": ["20", "10"], "campus_code": ["s3", "s1"],
    }
    assert result["requested_filters"] == {key: value for key, value in requested.items() if value is not None}
    for key, field in result["filter_consistency"]["fields"].items():
        assert field["status"] == "mismatch"
        assert field["mismatch_count"] == 1
        assert field["origin"] == ("requested" if requested.get(key) is not None else "source")
    assert result["warnings"]


@pytest.mark.parametrize("fetched", [199, 200])
def test_server_cap_remains_truncated_after_explicit_filtering(fetched):
    rows = [catalog_row(syy="2025") for _ in range(fetched - 1)] + [catalog_row()]
    result = erp.parse_course_catalog(
        {"dsSles251": rows}, "AI", 1, FILTERS, requested_filters={"year": 2026},
    )
    assert result["count"] == result["matching_count"] == 1
    assert result["excluded_count"] == fetched - 1
    assert result["truncated"] is (fetched >= 200)
    assert result["courses"][0]["year"] == "2026"


@pytest.mark.parametrize("requested", [{}, {"year": 2026}, {"year": 2026, "term_code": "20", "campus_code": "s3"}])
def test_matching_scope_preserves_raw_types_without_warnings(requested):
    filters = {**FILTERS, "year": 2026, "college_code": "", "department_code": None}
    result = erp.parse_course_catalog(
        {"dsSles251": [catalog_row(syy=2026), catalog_row()]}, "AI", 20, filters,
        requested_filters=requested,
    )
    assert result["filters"] == filters
    assert result["observed_scope"]["year"] == [2026, "2026"]
    assert [row["year"] for row in result["courses"]] == [2026, "2026"]
    assert all(field["status"] == "matched" for field in result["filter_consistency"]["fields"].values())
    assert result["count"] == result["matching_count"] == result["fetched_count"] == 2
    assert result["excluded_count"] == 0
    assert result["warnings"] == []


def test_default_checks_every_fetched_row_including_missing_values_after_limit():
    result = erp.parse_course_catalog(
        {"dsSles251": [catalog_row(), catalog_row(smtDivCd="10"), catalog_row(smtDivCd=None)]},
        "AI", 1, FILTERS,
    )
    assert result["count"] == 1
    assert result["matching_count"] == result["fetched_count"] == 3
    assert result["observed_scope"]["term_code"] == ["20", "10", None]
    field = result["filter_consistency"]["fields"]["term_code"]
    assert field["status"] == "mismatch"
    assert field["mismatch_count"] == field["missing_count"] == 1


def test_source_values_are_not_normalized_or_replaced_with_known_ui_codes():
    filters = {"year": " 2026 ", "term_code": "SOURCE-TERM", "campus_code": "SOURCE-CAMPUS"}
    row = catalog_row(syy=" 2026 ", smtDivCd="SOURCE-TERM", campsBusnsCd="SOURCE-CAMPUS")
    result = erp.parse_course_catalog({"dsSles251": [row]}, "AI", 20, filters)
    assert result["filters"] == filters
    assert result["observed_scope"] == {key: [value] for key, value in filters.items()}
    assert result["warnings"] == []  # Equality is checked, not invented UI-code semantics.


def test_observed_scope_keeps_distinct_json_types_even_when_python_equality_agrees():
    result = erp.parse_course_catalog(
        {"dsSles251": [catalog_row(syy=2026), catalog_row(syy=2026.0), catalog_row(syy=2026)]},
        "AI", 20, FILTERS,
    )
    observed = result["observed_scope"]["year"]
    assert len(observed) == 2
    assert [type(value) for value in observed] == [int, float]
    assert result["filter_consistency"]["fields"]["year"]["missing_count"] == 1


@pytest.fixture
def captured_catalog(monkeypatch):
    """Fake only browser I/O; exercise the real fetch and parser together."""
    monkeypatch.setattr(erp, "_open_menu_and_capture", AsyncMock())

    def make(conditions, rows):
        response = SimpleNamespace(
            ok=True, request=SimpleNamespace(post_data_json=conditions),
            json=AsyncMock(return_value={"dsSles251": rows}),
        )

        @asynccontextmanager
        async def pending(*args, **kwargs):
            yield SimpleNamespace(value=AsyncMock(return_value=response)())

        page = MagicMock()
        page.expect_response = pending
        field = page.locator.return_value
        field.input_value = AsyncMock(return_value="2026")
        field.last.focus = AsyncMock()
        field.last.press = AsyncMock()
        field.last.input_value = AsyncMock(return_value="교과목명")
        options = [
            SimpleNamespace(input_value=AsyncMock(return_value="2학기"), fill=AsyncMock()),
            SimpleNamespace(input_value=AsyncMock(return_value="대학원(신촌)"), fill=AsyncMock()),
        ]
        field.nth.side_effect = lambda index: options[index]
        page.get_by_text.return_value.last.click = AsyncMock()
        return page, response

    return make


def source_conditions(**changes):
    return {
        "@d1#kwd": "AI", "@d1#searchGbn": "2", "@d1#kwdDivCd": "2",
        "@d1#syy": "2026", "@d1#smtDivCd": "20", "@d1#campsBusnsCd": "s3",
        "@d1#univCd": "", "@d1#faclyCd": None, **changes,
    }


@pytest.mark.parametrize("requested", [{}, {"year": 2026}])
@pytest.mark.parametrize("rows", [[], [catalog_row()], [catalog_row(smtDivCd="10")]])
async def test_fetch_keeps_source_conditions_separate_from_partial_requested_scope(captured_catalog, requested, rows):
    page, response = captured_catalog(source_conditions(), rows)
    result = await erp.fetch_course_catalog(page, "AI", **requested)
    assert result["filters"] == {
        **FILTERS, "college_code": "", "department_code": None, "keyword_type": "2",
    }
    assert result["requested_filters"] == requested
    assert result["count"] == len(rows)
    assert result["result_status"] == ("ok" if rows else "source_empty")
    status = "unverified" if not rows else "matched" if rows[0]["smtDivCd"] == "20" else "mismatch"
    assert result["filter_consistency"]["fields"]["term_code"]["status"] == status
    response.json.assert_awaited_once()


@pytest.mark.parametrize("key", SOURCE_KEYS)
@pytest.mark.parametrize("source_value", [None, "", "different"])
async def test_fetch_fails_closed_when_explicit_filter_is_absent_or_changed_in_request(captured_catalog, key, source_value):
    conditions = source_conditions(**{"@d1#" + SOURCE_KEYS[key]: source_value})
    page, response = captured_catalog(conditions, [catalog_row()])
    requested: dict = {key: 2026 if key == "year" else FILTERS[key]}
    with pytest.raises(ScrapeFailedError, match="요청 필터와 서버 조회 조건"):
        await erp.fetch_course_catalog(page, "AI", **requested)
    response.json.assert_not_awaited()


async def test_fetch_missing_default_conditions_never_invents_scope(captured_catalog):
    conditions = source_conditions()
    for source in SOURCE_KEYS.values():
        del conditions["@d1#" + source]
    page, _ = captured_catalog(conditions, [catalog_row()])
    result = await erp.fetch_course_catalog(page, "AI")
    assert all(result["filters"][key] is None for key in SOURCE_KEYS)
    assert result["observed_scope"] == {key: [value] for key, value in FILTERS.items()}
    assert all(field["status"] == "unverified" for field in result["filter_consistency"]["fields"].values())
    assert result["warnings"]

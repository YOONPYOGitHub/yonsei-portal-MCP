"""Synthetic-only refusal contracts and legacy sealed-summary compatibility."""
import json

import pytest

from tests.qa.records import RecordError, RunStore, seal_run, verify_archive


def make_store(tmp_path):
    return RunStore.create(tmp_path.resolve() / "synthetic", {
        "timestamp": "test", "model": "test", "execution_mode": "synthetic",
    })


def refusal_catalog():
    return [{"id": "q.refusal", "primary_tool": "read", "expected_tools": []}]


def test_refusal_is_explicit_with_no_fictitious_calls(tmp_path):
    store = make_store(tmp_path)
    store.save_answer("q.refusal", {
        "status": "refused", "answer": "Cannot provide that synthetic information.",
        "reason": "Outside permitted scope", "call_ids": [],
    })
    summary = store.summarize(refusal_catalog(), ["q.refusal"])
    assert summary["selected_counts"]["refused"] == 1
    assert sum(summary["selected_counts"].values()) == 1
    assert summary["calls"] == {"total": 0, "referenced": 0, "reused": 0}
    assert summary["primary_tools"]["called"] == 0
    assert summary["primary_tools"]["answered"] == 0
    assert list((store.path / "calls").iterdir()) == []
    saved = json.loads((store.path / "answers/q.refusal.json").read_text())
    assert saved["evidence"] == []
    sealed = seal_run(store, refusal_catalog(), ["q.refusal"])
    assert verify_archive(store.path) == sealed


@pytest.mark.parametrize("field", ["answer", "reason"])
@pytest.mark.parametrize("value", [None, "", " \n", 1, []])
def test_refusal_requires_nonempty_answer_and_reason(tmp_path, field, value):
    store = make_store(tmp_path)
    record = {"status": "refused", "answer": "Synthetic refusal", "reason": "Synthetic scope"}
    record[field] = value
    with pytest.raises(RecordError):
        store.save_answer("q.refusal", record)
    assert list((store.path / "answers").iterdir()) == []


def test_version_two_summaries_include_zero_refusals_and_keep_legacy_shape(tmp_path):
    store = make_store(tmp_path)
    catalog = refusal_catalog()
    legacy = store.summarize(catalog, ["q.refusal"])
    current = store.summarize(catalog, ["q.refusal"], schema_version=2)
    assert "refused" not in legacy["selected_counts"]
    assert current["selected_counts"] == dict(legacy["selected_counts"], refused=0)
    assert seal_run(store, catalog, ["q.refusal"]) == current
    checkpoint = json.loads((store.path / "checkpoint.json").read_text())
    assert checkpoint["version"] == 2
    assert verify_archive(store.path) == current


def test_legacy_checkpoint_normalizes_only_absent_zero_refusals_readonly(tmp_path):
    store = make_store(tmp_path)
    catalog = refusal_catalog()
    store.save_answer("q.refusal", {"status": "blocked", "reason": "Synthetic blocker"})
    seal_run(store, catalog, ["q.refusal"])
    path = store.path / "checkpoint.json"
    checkpoint = json.loads(path.read_text())
    checkpoint["version"] = 1
    checkpoint["summary"]["selected_counts"].pop("refused", None)
    path.write_text(json.dumps(checkpoint))
    original = path.read_bytes()
    summary = verify_archive(store.path)
    assert summary["selected_counts"]["refused"] == 0
    assert summary["selected_counts"]["blocked"] == 1
    assert path.read_bytes() == original


@pytest.mark.parametrize("mutation", ["drop_nonzero", "unknown", "boolean", "float", "negative", "missing_current", "unknown_version"])
def test_checkpoint_normalization_never_loses_counts(tmp_path, mutation):
    store = make_store(tmp_path)
    store.save_answer("q.refusal", {"status": "refused", "answer": "Synthetic refusal", "reason": "Synthetic scope"})
    seal_run(store, refusal_catalog(), ["q.refusal"])
    path = store.path / "checkpoint.json"
    checkpoint = json.loads(path.read_text())
    counts = checkpoint["summary"]["selected_counts"]
    if mutation == "drop_nonzero":
        checkpoint["version"] = 1
        del counts["refused"]
    elif mutation == "unknown":
        counts["future_status"] = 0
    elif mutation == "boolean":
        counts["refused"] = True
    elif mutation == "float":
        counts["refused"] = 1.0
    elif mutation == "negative":
        counts["refused"] = -1
    elif mutation == "missing_current":
        del counts["refused"]
    else:
        checkpoint["version"] = 99
    path.write_text(json.dumps(checkpoint))
    with pytest.raises(RecordError):
        verify_archive(store.path)


def test_duplicate_checkpoint_keys_are_rejected_without_losing_counts(tmp_path):
    store = make_store(tmp_path)
    seal_run(store, refusal_catalog(), ["q.refusal"])
    path = store.path / "checkpoint.json"
    raw = path.read_text().replace('"refused":0', '"refused":42,"refused":0')
    assert '"refused":42' in raw
    path.write_text(raw)
    with pytest.raises(RecordError):
        verify_archive(store.path)


@pytest.mark.parametrize("field", ["call_ids", "reused_call_ids"])
def test_refusal_cannot_cite_missing_or_forbidden_call_evidence(tmp_path, field):
    store = make_store(tmp_path)
    answer = {"status": "refused", "answer": "Synthetic refusal", "reason": "Synthetic scope", field: ["call-1"]}
    with pytest.raises(RecordError):
        store.save_answer("q.refusal", answer)
    store.save_call("call-1", {"tool": "read", "arguments": {}, "result": [],
        "is_error": False, "started_at": "test", "finished_at": "test"})
    store.save_answer("q.refusal", answer)
    with pytest.raises(RecordError):
        store.summarize(refusal_catalog(), ["q.refusal"])


def test_refusal_does_not_require_primary_success_when_calls_are_allowed(tmp_path):
    store = make_store(tmp_path)
    catalog = [{"id": "q.refusal", "primary_tool": "read"}]
    store.save_answer("q.refusal", {"status": "refused", "answer": "Synthetic refusal", "reason": "Synthetic scope"})
    summary = seal_run(store, catalog, ["q.refusal"])
    assert summary["selected_counts"]["refused"] == 1
    assert summary["primary_tools"] == {"expected": 1, "called": 0, "answered": 0}


def test_blocked_clarification_and_error_remain_distinct(tmp_path):
    store = make_store(tmp_path)
    statuses = ["blocked", "needs_clarification", "tool_error", "refused"]
    store.save_call("failed", {"tool": "read", "arguments": {}, "result": "Synthetic failure",
        "is_error": True, "started_at": "test", "finished_at": "test"})
    for status in statuses:
        record: dict = {"status": status, "reason": "Synthetic reason"}
        if status == "refused":
            record["answer"] = "Synthetic refusal"
        elif status == "tool_error":
            record["call_ids"] = ["failed"]
        store.save_answer(status, record)
    catalog = [{"id": status, "primary_tool": "read"} for status in statuses + ["not_run", "unselected"]]
    result = seal_run(store, catalog, statuses + ["not_run"])
    assert result["selected_counts"] == {"answered": 0, "blocked": 1, "needs_clarification": 1,
        "tool_error": 1, "refused": 1, "not_run": 1}
    assert sum(result["selected_counts"].values()) == result["selected_total"] == 5
    assert result["unselected_not_run"] == 1
    assert result["primary_tools"] == {"expected": 1, "called": 1, "answered": 0}
    assert verify_archive(store.path) == result


def test_synthetic_catalog_152_modes_are_counted_without_fabricating_refusal_calls(tmp_path):
    store = make_store(tmp_path)
    catalog = []
    for index in range(38):
        tool = f"read_{index}"
        for mode in ("answer_a", "answer_b", "clarification", "refusal"):
            identifier = f"q{index}.{mode}"
            catalog.append({"id": identifier, "primary_tool": tool,
                "expected_tools": [tool] if mode.startswith("answer") else []})
            if mode.startswith("answer"):
                store.save_call(identifier, {"tool": tool, "arguments": {}, "result": [],
                    "is_error": False, "started_at": "test", "finished_at": "test"})
                record = {"status": "answered", "answer": "Synthetic answer", "call_ids": [identifier]}
            elif mode == "clarification":
                record = {"status": "needs_clarification", "reason": "Synthetic question"}
            else:
                record = {"status": "refused", "answer": "Synthetic refusal", "reason": "Synthetic scope"}
            store.save_answer(identifier, record)
    summary = seal_run(store, catalog, [row["id"] for row in catalog])
    assert summary["selected_counts"] == {"answered": 76, "needs_clarification": 38, "refused": 38,
        "tool_error": 0, "blocked": 0, "not_run": 0}
    assert sum(summary["selected_counts"].values()) == summary["selected_total"] == 152
    assert summary["calls"] == {"total": 76, "referenced": 76, "reused": 0}
    assert verify_archive(store.path) == summary


@pytest.mark.parametrize("version", [0, 3, True, 2.0, "2", None])
def test_invalid_summary_versions_fail(tmp_path, version):
    store = make_store(tmp_path)
    with pytest.raises(RecordError):
        store.summarize(refusal_catalog(), [], schema_version=version)

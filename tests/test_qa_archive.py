"""Archived runs remain independently checkable after the process exits."""
import json
import pytest
from tests.qa.records import RunStore, RecordError


def complete_run(tmp_path):
    store = RunStore.create(tmp_path.resolve() / "private", {"timestamp": "test", "model": "test", "execution_mode": "synthetic"})
    store.save_call("call-1", {"tool": "read", "arguments": {}, "result": {"count": 0}, "is_error": False, "started_at": "test", "finished_at": "test"})
    store.save_answer("read.basic", {"status": "answered", "answer": "합성 빈 결과", "call_ids": ["call-1"]})
    return store, [{"id": "read.basic", "primary_tool": "read", "expected_tools": ["read"]}]


def test_sealed_run_verifies_without_live_store_and_rejects_append(tmp_path):
    from tests.qa.records import seal_run, verify_archive
    store, catalog = complete_run(tmp_path)
    expected = seal_run(store, catalog, ["read.basic"])
    assert verify_archive(store.path) == expected
    with pytest.raises(RecordError):
        store.save_answer("read.other", {"status": "needs_clarification", "reason": "synthetic"})
    with pytest.raises(RecordError):
        store.save_call("call-2", {"tool": "read", "arguments": {}, "result": [], "is_error": False, "started_at": "test", "finished_at": "test"})


def test_archive_rejects_tampering_and_unsafe_ledger_ids(tmp_path):
    from tests.qa.records import seal_run, verify_archive
    store, catalog = complete_run(tmp_path)
    seal_run(store, catalog, ["read.basic"])
    call = store.path / "calls/call-1.json"
    original = call.read_bytes()
    call.write_text('{}', encoding='utf-8')
    with pytest.raises(RecordError): verify_archive(store.path)
    call.write_bytes(original)
    path = store.path / "checkpoint.json"
    checkpoint = json.loads(path.read_text(encoding='utf-8'))
    checkpoint['calls']['../outside'] = '0' * 64
    path.write_text(json.dumps(checkpoint), encoding='utf-8')
    with pytest.raises(RecordError): verify_archive(store.path)

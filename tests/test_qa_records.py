"""Offline synthetic tests; runnable with unittest without project imports."""
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
import uuid


class RunStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve() / "private"
        from qa.records import RunStore, RecordError
        self.RunStore = RunStore
        self.RecordError = RecordError
        self.manifest = {"timestamp": "2026-10-05T09:00:00+09:00", "model": "current-chat", "execution_mode": "current_chat"}

    def test_create_private_unique_runs_with_explicit_manifest(self):
        first = self.RunStore.create(self.base, self.manifest)
        second = self.RunStore.create(self.base, self.manifest)
        self.assertNotEqual(first.path, second.path)
        uuid.UUID(first.path.name)
        self.assertEqual(json.loads((first.path / "manifest.json").read_text()), self.manifest)
        if os.name == "posix":
            for path in (first.path, first.path / "calls", first.path / "answers"):
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE((first.path / "manifest.json").stat().st_mode), 0o600)
        for key in self.manifest:
            invalid = dict(self.manifest)
            del invalid[key]
            with self.assertRaises(self.RecordError):
                self.RunStore.create(self.base, invalid)
        self.assertEqual(len(list(self.base.iterdir())), 2)

    def call(self, **changes):
        record = {"tool": "get_alpha", "arguments": {}, "result": {"private": "synthetic"}, "is_error": False, "started_at": self.manifest["timestamp"], "finished_at": self.manifest["timestamp"]}
        record.update(changes)
        return record

    def test_calls_are_canonical_private_exclusive_and_bounded(self):
        import hashlib
        from qa.records import MAX_RECORD_BYTES
        store = self.RunStore.create(self.base, self.manifest)
        record = self.call()
        ref = store.save_call("call-1", record)
        path = store.path / "calls" / "call-1.json"
        expected = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        self.assertEqual(path.read_bytes(), expected)
        self.assertEqual(ref, {"call_id": "call-1", "sha256": hashlib.sha256(expected).hexdigest()})
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        with self.assertRaises(self.RecordError):
            store.save_call("call-1", self.call(result="different"))
        self.assertEqual(path.read_bytes(), expected)
        bad_records = [self.call(result=object()), self.call(result=float("nan")), self.call(result="x" * MAX_RECORD_BYTES), self.call(is_error="no"), self.call(arguments=[]), self.call(tool=""), self.call(result={1: "not-json-key"})]
        for invalid in bad_records:
            with self.subTest(kind=type(invalid["result"]).__name__):
                with self.assertRaises(self.RecordError) as error:
                    store.save_call("invalid", invalid)
                self.assertNotIn("synthetic", str(error.exception))
                self.assertFalse((store.path / "calls" / "invalid.json").exists())
        for invalid_id in ("../secret", "a/b", "a\\b", ".", "..", "", "CON", "nul", "com1", "id."):
            with self.subTest(identifier=invalid_id), self.assertRaises(self.RecordError):
                store.save_call(invalid_id, record)
        self.assertEqual(len(list((store.path / "calls").iterdir())), 1)

    def symlink(self, target, link, directory=False):
        try:
            link.symlink_to(target, target_is_directory=directory)
        except (OSError, NotImplementedError):
            self.skipTest("Symlink creation unavailable on this platform")

    def test_symlink_directories_and_files_are_rejected(self):
        outside = self.base.parent / "outside"
        outside.mkdir()
        self.symlink(outside, self.base, directory=True)
        with self.assertRaises(self.RecordError):
            self.RunStore.create(self.base / "nested", self.manifest)
        self.assertEqual(list(outside.iterdir()), [])
        self.base.unlink()
        store = self.RunStore.create(self.base, self.manifest)
        target = outside / "target.json"
        target.write_text("untouched")
        link = store.path / "calls" / "linked.json"
        self.symlink(target, link)
        with self.assertRaises(self.RecordError):
            store.save_call("linked", self.call())
        self.assertEqual(target.read_text(), "untouched")
        link.unlink()
        (store.path / "calls").rmdir()
        self.symlink(outside, store.path / "calls", directory=True)
        with self.assertRaises(self.RecordError):
            store.save_call("outside", self.call())
        self.assertFalse((outside / "outside.json").exists())

    def test_bad_manifest_and_non_directory_paths_are_generic(self):
        for invalid in (dict(self.manifest, private=object()), dict(self.manifest, private=float("nan"))):
            with self.assertRaises(self.RecordError):
                self.RunStore.create(self.base, invalid)
        self.assertFalse(self.base.exists())
        self.base.write_text("synthetic private path")
        with self.assertRaises(self.RecordError) as error:
            self.RunStore.create(self.base, self.manifest)
        self.assertNotIn(str(self.base), str(error.exception))

    def test_answer_evidence_is_generated_and_revalidated(self):
        store = self.RunStore.create(self.base, self.manifest)
        ref = store.save_call("call-1", self.call())
        answer = {"status": "answered", "answer": "Synthetic answer", "call_ids": ["call-1"]}
        self.assertIsNone(store.save_answer("get_alpha.basic", answer))
        path = store.path / "answers" / "get_alpha.basic.json"
        saved = json.loads(path.read_text())
        self.assertEqual(saved["evidence"], [dict(ref, reused=False)])
        self.assertNotIn("evidence", answer)
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        with self.assertRaises(self.RecordError):
            store.save_answer("get_alpha.basic", answer)
        store.save_answer("get_alpha.followup", {"status": "answered", "answer": "Reused result", "reused_call_ids": ["call-1"]})
        saved = json.loads((store.path / "answers" / "get_alpha.followup.json").read_text())
        self.assertEqual(saved["evidence"], [dict(ref, reused=True)])
        invalids = [dict(answer, call_ids=["missing"]), dict(answer, evidence=[dict(ref, sha256="0" * 64)]), dict(answer, status="not_run"), dict(answer, answer=" "), dict(answer, call_ids=[]), dict(answer, call_ids=["call-1", "call-1"]), dict(answer, reused_call_ids=["call-1"]), {"status": "blocked"}, {"status": "needs_clarification", "reason": " "}, {"status": "tool_error", "reason": "failed", "call_ids": ["call-1"]}]
        for invalid in invalids:
            with self.subTest(status=invalid.get("status")), self.assertRaises(self.RecordError):
                store.save_answer("invalid", invalid)
        self.assertFalse((store.path / "answers" / "invalid.json").exists())
        store.save_call("failed", self.call(is_error=True))
        store.save_answer("get_alpha.error", {"status": "tool_error", "reason": "Synthetic failure", "call_ids": ["failed"]})
        for status in ("blocked", "needs_clarification"):
            store.save_answer(status, {"status": status, "reason": "Synthetic reason"})
        (store.path / "calls" / "call-1.json").write_text("{}")
        with self.assertRaises(self.RecordError):
            store.save_answer("tampered", answer)

    def catalog(self):
        return [{"id": "get_alpha.basic", "primary_tool": "get_alpha", "expected_tools": ["get_alpha"]}, {"id": "get_beta.basic", "primary_tool": "get_beta", "expected_tools": ["get_beta"]}]

    def test_summary_counts_only_selected_statuses_and_actual_primary_tools(self):
        store = self.RunStore.create(self.base, self.manifest)
        catalog = self.catalog()
        selected = [catalog[0]["id"]]
        empty = store.summarize(catalog, selected)
        self.assertEqual(empty["selected_counts"]["not_run"], 1)
        store.save_call("call-1", self.call())
        store.save_answer(selected[0], {"status": "answered", "answer": "Synthetic private answer", "call_ids": ["call-1"]})
        self.assertEqual(store.summarize(catalog, selected), {
            "catalog_total": 2, "selected_total": 1, "unselected_not_run": 1,
            "selected_counts": {"answered": 1, "tool_error": 0, "blocked": 0, "needs_clarification": 0, "not_run": 0},
            "primary_tools": {"expected": 1, "called": 1, "answered": 1},
            "calls": {"total": 1, "referenced": 1, "reused": 0}})
        with self.assertRaises(self.RecordError):
            store.summarize(catalog, [])
        for bad_catalog, bad_selected in ((catalog + [catalog[0]], selected), (catalog, ["unknown"]), (catalog, selected * 2), ([dict(catalog[0], primary_tool="")], selected), ([dict(catalog[0], expected_tools=["get_beta"])], selected)):
            with self.subTest(), self.assertRaises(self.RecordError):
                store.summarize(bad_catalog, bad_selected)
        store.save_answer("unknown", {"status": "blocked", "reason": "Synthetic"})
        with self.assertRaises(self.RecordError):
            store.summarize(catalog, selected)

    def test_summary_rejects_wrong_tool_even_if_answer_claims_primary(self):
        store = self.RunStore.create(self.base, self.manifest)
        store.save_call("beta", self.call(tool="get_beta"))
        store.save_answer("get_alpha.basic", {"status": "answered", "answer": "Synthetic", "primary_tool": "get_alpha", "call_ids": ["beta"]})
        with self.assertRaises(self.RecordError):
            store.summarize(self.catalog(), ["get_alpha.basic"])

    def test_summary_verifies_hashes_missing_files_and_unregistered_calls(self):
        store = self.RunStore.create(self.base, self.manifest)
        store.save_call("alpha", self.call())
        store.save_answer("get_alpha.basic", {"status": "answered", "answer": "Synthetic", "call_ids": ["alpha"]})
        path = store.path / "answers" / "get_alpha.basic.json"
        original = path.read_bytes()
        tampered = json.loads(original)
        tampered["evidence"][0]["sha256"] = "0" * 64
        path.write_text(json.dumps(tampered))
        with self.assertRaises(self.RecordError):
            store.summarize(self.catalog(), ["get_alpha.basic"])
        path.write_bytes(original)
        call_path = store.path / "calls" / "alpha.json"
        call = call_path.read_bytes()
        call_path.unlink()
        with self.assertRaises(self.RecordError):
            store.summarize(self.catalog(), ["get_alpha.basic"])
        call_path.write_bytes(call)
        store.save_call("rogue", self.call(tool="not_registered"))
        with self.assertRaises(self.RecordError):
            store.summarize(self.catalog(), ["get_alpha.basic"])

    def test_summary_requires_explicit_evidence_reuse(self):
        catalog = [{"id": "q1", "primary_tool": "get_alpha"}, {"id": "q2", "primary_tool": "get_alpha"}]
        for explicit in (False, True):
            with self.subTest(explicit=explicit):
                store = self.RunStore.create(self.base, self.manifest)
                store.save_call("alpha", self.call())
                store.save_answer("q1", {"status": "answered", "answer": "Synthetic", "call_ids": ["alpha"]})
                field = "reused_call_ids" if explicit else "call_ids"
                store.save_answer("q2", {"status": "answered", "answer": "Synthetic", field: ["alpha"]})
                if explicit:
                    report = store.summarize(catalog, ["q1", "q2"])
                    self.assertEqual(report["calls"], {"total": 1, "referenced": 1, "reused": 1})
                    self.assertEqual(report["selected_counts"]["answered"], 2)
                else:
                    with self.assertRaises(self.RecordError):
                        store.summarize(catalog, ["q1", "q2"])

    def test_deleted_records_cannot_be_recreated_under_the_same_id(self):
        store = self.RunStore.create(self.base, self.manifest)
        store.save_call("alpha", self.call())
        (store.path / "calls" / "alpha.json").unlink()
        with self.assertRaises(self.RecordError):
            store.save_call("alpha", self.call(result="replacement"))
        store.save_answer("q", {"status": "blocked", "reason": "Synthetic"})
        (store.path / "answers" / "q.json").unlink()
        with self.assertRaises(self.RecordError):
            store.save_answer("q", {"status": "blocked", "reason": "replacement"})

    def test_manifest_integrity_is_checked_by_summary(self):
        store = self.RunStore.create(self.base, self.manifest)
        (store.path / "manifest.json").write_text("{}")
        with self.assertRaises(self.RecordError):
            store.summarize(self.catalog(), [])

    def test_summary_non_answer_states_do_not_claim_answered_coverage(self):
        for status in ("tool_error", "blocked", "needs_clarification"):
            with self.subTest(status=status):
                store = self.RunStore.create(self.base, self.manifest)
                answer: dict = {"status": status, "reason": "Synthetic failure"}
                if status == "tool_error":
                    store.save_call("failed", self.call(is_error=True))
                    answer["call_ids"] = ["failed"]
                store.save_answer("get_alpha.basic", answer)
                report = store.summarize(self.catalog(), ["get_alpha.basic", "get_beta.basic"])
                self.assertEqual(report["selected_counts"][status], 1)
                self.assertEqual(report["selected_counts"]["not_run"], 1)
                self.assertEqual(report["primary_tools"]["answered"], 0)
                self.assertEqual(report["primary_tools"]["called"], int(status == "tool_error"))

    def test_read_rejects_symlink_even_when_content_hash_matches(self):
        store = self.RunStore.create(self.base, self.manifest)
        store.save_call("alpha", self.call())
        call_path = store.path / "calls" / "alpha.json"
        outside = self.base.parent / "outside-call.json"
        outside.write_bytes(call_path.read_bytes())
        call_path.unlink()
        self.symlink(outside, call_path)
        with self.assertRaises(self.RecordError):
            store.save_answer("q", {"status": "answered", "answer": "Synthetic", "call_ids": ["alpha"]})
        with self.assertRaises(self.RecordError):
            store.summarize(self.catalog(), [])

    def test_external_unknown_answer_is_not_silently_ignored(self):
        store = self.RunStore.create(self.base, self.manifest)
        (store.path / "answers" / "unknown.json").write_text("{}")
        with self.assertRaises(self.RecordError):
            store.summarize(self.catalog(), [])

    def test_actual_call_coverage_does_not_require_an_answer(self):
        store = self.RunStore.create(self.base, self.manifest)
        store.save_call("alpha", self.call())
        report = store.summarize(self.catalog(), ["get_alpha.basic"])
        self.assertEqual(report["primary_tools"], {"expected": 1, "called": 1, "answered": 0})
        self.assertEqual(report["selected_counts"]["not_run"], 1)
        self.assertEqual(report["calls"], {"total": 1, "referenced": 0, "reused": 0})

    def test_summary_rejects_evidence_outside_question_call_graph(self):
        store = self.RunStore.create(self.base, self.manifest)
        store.save_call("alpha", self.call())
        store.save_call("beta", self.call(tool="get_beta"))
        store.save_answer("get_alpha.basic", {"status": "answered", "answer": "Synthetic", "call_ids": ["alpha", "beta"]})
        with self.assertRaises(self.RecordError):
            store.summarize(self.catalog(), ["get_alpha.basic"])
        catalog = self.catalog()
        catalog[0]["expected_tools"].append("get_beta")
        self.assertEqual(store.summarize(catalog, ["get_alpha.basic"])["selected_counts"]["answered"], 1)


if __name__ == "__main__":
    unittest.main()

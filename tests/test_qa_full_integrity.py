"""Full export checks use only temporary synthetic fixtures, never live archives."""
import hashlib
import json
import os
from pathlib import Path

import pytest

from tests.qa import records


def exported_archive(tmp_path):
    root = tmp_path.resolve() / "synthetic-export"
    root.mkdir()
    files = {
        "archive-index.json": b'{"synthetic":true}',
        "reports/report.md": b"Synthetic report\n",
        "snapshots/catalog.json": b"[]",
        "reviews/review.md": b"Synthetic review\n",
    }
    for relative, data in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    inventory = {"schema_version": 1, "algorithm": "sha256", "files": {
        relative: hashlib.sha256(data).hexdigest() for relative, data in files.items()
    }, "scope": "All exported regular files, excluding integrity.json itself"}
    write_inventory(root, inventory)
    return root, inventory


def write_inventory(root, inventory):
    (root / "integrity.json").write_text(json.dumps(inventory), encoding="utf-8")


def verify_full(root):
    assert callable(getattr(records, "verify_full_archive", None)), "Explicit full-export verifier is required"
    return records.verify_full_archive(root)


def test_full_inventory_covers_index_reports_snapshots_reviews_readonly(tmp_path):
    root, inventory = exported_archive(tmp_path)
    before = {p.relative_to(root).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
              for p in root.rglob("*") if p.is_file()}
    assert verify_full(root) == {"schema_version": 1, "algorithm": "sha256", "files_checked": 4}
    after = {p.relative_to(root).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
             for p in root.rglob("*") if p.is_file()}
    assert after == before
    assert "integrity.json" not in inventory["files"]


@pytest.mark.parametrize("relative", ["archive-index.json", "reports/report.md", "snapshots/catalog.json", "reviews/review.md"])
@pytest.mark.parametrize("change", ["tampered", "missing", "unlisted", "extra"])
def test_every_exported_artifact_requires_exact_hash_and_inventory_membership(tmp_path, relative, change):
    root, inventory = exported_archive(tmp_path)
    if change == "tampered":
        (root / relative).write_bytes(b"Changed synthetic content")
    elif change == "missing":
        (root / relative).unlink()
    elif change == "unlisted":
        del inventory["files"][relative]
        write_inventory(root, inventory)
    else:
        (root / (relative + ".extra")).write_bytes(b"Unlisted synthetic content")
    with pytest.raises(records.RecordError, match="^Full archive verification failed$"):
        verify_full(root)


def test_equal_file_count_does_not_hide_replaced_inventory_member(tmp_path):
    root, inventory = exported_archive(tmp_path)
    source = root / "reviews/review.md"
    source.rename(root / "reviews/replacement.md")
    with pytest.raises(records.RecordError):
        verify_full(root)


@pytest.mark.parametrize("field,value", [
    ("schema_version", 2), ("schema_version", True), ("schema_version", 1.0),
    ("algorithm", "md5"), ("algorithm", None), ("scope", ""), ("scope", " \n"),
    ("scope", []), ("files", []), ("files", None), ("files", "private-value"),
    ("extra_field", "not-in-schema"),
])
def test_malformed_inventory_schema_fails_generically(tmp_path, field, value):
    root, inventory = exported_archive(tmp_path)
    inventory[field] = value
    write_inventory(root, inventory)
    with pytest.raises(records.RecordError, match="^Full archive verification failed$"):
        verify_full(root)


@pytest.mark.parametrize("field", ["schema_version", "algorithm", "scope", "files"])
def test_missing_inventory_fields_fail(tmp_path, field):
    root, inventory = exported_archive(tmp_path)
    del inventory[field]
    write_inventory(root, inventory)
    with pytest.raises(records.RecordError):
        verify_full(root)


@pytest.mark.parametrize("raw", [b"[]", b"null", b"1", b"{", b"\xff", b"\"private-value\""])
def test_malformed_inventory_json_fails_generically(tmp_path, raw):
    root, _ = exported_archive(tmp_path)
    (root / "integrity.json").write_bytes(raw)
    with pytest.raises(records.RecordError, match="^Full archive verification failed$"):
        verify_full(root)


@pytest.mark.parametrize("kind", ["top_level", "file_entry", "nonfinite"])
def test_duplicate_json_keys_and_nonfinite_values_are_not_normalized_away(tmp_path, kind):
    root, inventory = exported_archive(tmp_path)
    raw = json.dumps(inventory)
    if kind == "top_level":
        raw = raw.replace('"schema_version": 1', '"schema_version": 99, "schema_version": 1')
    elif kind == "file_entry":
        digest = inventory["files"]["archive-index.json"]
        raw = raw.replace('"files": {', '"files": {"archive-index.json": "' + '0' * 64 + '", ')
        assert digest in raw
    else:
        raw = raw.replace('"schema_version": 1', '"schema_version": NaN')
    (root / "integrity.json").write_text(raw)
    with pytest.raises(records.RecordError):
        verify_full(root)


def test_missing_inventory_does_not_fall_back_to_core(tmp_path):
    root, _ = exported_archive(tmp_path)
    (root / "integrity.json").unlink()
    with pytest.raises(records.RecordError):
        verify_full(root)


def symlink(target, link, directory=False):
    try:
        link.symlink_to(target, target_is_directory=directory)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks unavailable")


@pytest.mark.parametrize("kind", ["inventory", "file", "directory", "root", "ancestor", "unlisted", "broken"])
def test_symlinks_are_rejected_even_when_hashes_match(tmp_path, kind):
    root, _ = exported_archive(tmp_path)
    if kind in ("inventory", "file"):
        path = root / ("integrity.json" if kind == "inventory" else "reviews/review.md")
        outside = tmp_path.resolve() / "outside-synthetic"
        path.rename(outside)
        symlink(outside, path)
    elif kind == "directory":
        outside = tmp_path.resolve() / "outside-directory"
        (root / "reviews").rename(outside)
        symlink(outside, root / "reviews", directory=True)
    elif kind in ("root", "ancestor"):
        link = tmp_path.resolve() / "alias"
        target = root if kind == "root" else root.parent
        symlink(target, link, directory=True)
        root = link if kind == "root" else link / root.name
    else:
        target = root / "reports" if kind == "unlisted" else root / "absent"
        symlink(target, root / "unlisted-link", directory=True)
    with pytest.raises(records.RecordError, match="^Full archive verification failed$"):
        verify_full(root)


@pytest.mark.parametrize("relative", ["../outside", "/absolute", "./archive-index.json", "reports/../archive-index.json", "reports//report.md", "", ".", "integrity.json", "C:/report", "reports\\report.md", "nul\u0000name"])
def test_inventory_paths_are_canonical_safe_relative_paths(tmp_path, relative):
    root, inventory = exported_archive(tmp_path)
    inventory["files"][relative] = "0" * 64
    write_inventory(root, inventory)
    with pytest.raises(records.RecordError):
        verify_full(root)


@pytest.mark.parametrize("name", ["back\\slash", "colon:name", "line\nbreak", "trailing.", "trailing ", "NUL"])
def test_unsafe_exported_names_cannot_be_legitimized_by_inventory(tmp_path, name):
    root, inventory = exported_archive(tmp_path)
    try:
        (root / name).write_bytes(b"synthetic")
    except OSError:
        pytest.skip("Host already rejects unsafe filename")
    inventory["files"][name] = hashlib.sha256(b"synthetic").hexdigest()
    write_inventory(root, inventory)
    with pytest.raises(records.RecordError):
        verify_full(root)


def test_dotdot_in_export_root_is_not_resolved_away(tmp_path):
    root, _ = exported_archive(tmp_path)
    with pytest.raises(records.RecordError):
        verify_full(root / "reports" / "..")


def test_special_unlisted_file_is_not_silently_ignored(tmp_path):
    if not hasattr(os, "mkfifo"):
        pytest.skip("FIFO unavailable")
    root, _ = exported_archive(tmp_path)
    os.mkfifo(root / "pipe")
    with pytest.raises(records.RecordError):
        verify_full(root)


def test_oversized_inventory_is_rejected(tmp_path):
    root, _ = exported_archive(tmp_path)
    with (root / "integrity.json").open("ab") as stream:
        stream.write(b" " * records.MAX_RECORD_BYTES)
    with pytest.raises(records.RecordError):
        verify_full(root)


@pytest.mark.parametrize("digest", ["0" * 63, "G" * 64, "A" * 64, 1, None, {}, []])
def test_invalid_digests_fail_safely(tmp_path, digest):
    root, inventory = exported_archive(tmp_path)
    inventory["files"]["archive-index.json"] = digest
    write_inventory(root, inventory)
    with pytest.raises(records.RecordError):
        verify_full(root)


def test_only_root_inventory_is_excluded_and_large_unicode_payloads_work(tmp_path):
    root, inventory = exported_archive(tmp_path)
    (root / "empty-directory").mkdir()
    data = b"x" * (records.MAX_RECORD_BYTES + 1)
    for relative in ("nested/integrity.json", "snapshots/합성 스냅샷.bin"):
        path = root / relative
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(data)
        inventory["files"][relative] = hashlib.sha256(data).hexdigest()
    write_inventory(root, inventory)
    assert verify_full(root)["files_checked"] == 6
    (root / "nested/integrity.json").write_bytes(b"tampered synthetic nested inventory")
    with pytest.raises(records.RecordError):
        verify_full(root)


def test_directory_inspection_errors_are_not_hidden(tmp_path, monkeypatch):
    root, _ = exported_archive(tmp_path)
    original = Path.iterdir
    def denied(path):
        if path == root / "reviews":
            raise PermissionError("Synthetic sensitive error")
        return original(path)
    monkeypatch.setattr(Path, "iterdir", denied)
    with pytest.raises(records.RecordError, match="^Full archive verification failed$"):
        verify_full(root)


def test_core_and_export_integrity_are_explicitly_separate(tmp_path):
    store = records.RunStore.create(tmp_path.resolve() / "synthetic", {
        "timestamp": "test", "model": "test", "execution_mode": "synthetic"})
    catalog = [{"id": "q", "primary_tool": "read", "expected_tools": []}]
    store.save_answer("q", {"status": "refused", "answer": "Synthetic refusal", "reason": "Synthetic scope"})
    summary = records.seal_run(store, catalog, ["q"])
    assert records.verify_archive(store.path) == summary
    with pytest.raises(records.RecordError):
        verify_full(store.path)
    report = store.path / "report.md"
    report.write_bytes(b"Synthetic report")
    files = {p.relative_to(store.path).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in store.path.rglob("*") if p.is_file()}
    write_inventory(store.path, {"schema_version": 1, "algorithm": "sha256", "scope": "Complete export", "files": files})
    assert verify_full(store.path)["files_checked"] == len(files)
    report.write_bytes(b"Changed synthetic report")
    assert records.verify_archive(store.path) == summary  # Core deliberately ignores exports.
    with pytest.raises(records.RecordError):
        verify_full(store.path)


def test_checksums_do_not_claim_origin_authentication(tmp_path):
    root, inventory = exported_archive(tmp_path)
    path = root / "reports/report.md"
    path.write_bytes(b"Owner changed this synthetic payload and receipt")
    inventory["files"]["reports/report.md"] = hashlib.sha256(path.read_bytes()).hexdigest()
    write_inventory(root, inventory)
    # Successful consistency verification cannot prove who created this data.
    assert verify_full(root)["files_checked"] == len(inventory["files"])

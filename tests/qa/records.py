"""Private append-only current-chat QA records (stdlib only).

All records are raw/private, NOT redacted. Each canonical UTF-8 JSON file is
limited to 4 MiB. Append-only means this API never overwrites: the OS owner can
still alter files. POSIX directories/files use 0700/0600; Windows mode metadata
is not proof of a private ACL. No server, credentials, dotenv, or network loads.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import uuid

MAX_RECORD_BYTES = 4 * 1024 * 1024
STATUSES = ("answered", "tool_error", "blocked", "needs_clarification")


class RecordError(ValueError):
    """Invalid record or unsafe storage operation; messages omit private data."""


def _identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value) or value.endswith("."):
        raise RecordError("Invalid identifier")
    if value.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        raise RecordError("Invalid identifier")
    return value


def _json_value(value):
    if type(value) is dict:
        return all(type(k) is str and _json_value(v) for k, v in value.items())
    if type(value) is list:
        return all(_json_value(v) for v in value)
    return value is None or type(value) in (str, int, float, bool)


def _encode(record):
    try:
        if type(record) is not dict or not _json_value(record):
            raise ValueError
        data = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        if len(data) > MAX_RECORD_BYTES:
            raise ValueError
        return data
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise RecordError("Invalid or oversized JSON record") from None


def _directory(path, create=False):
    """Check every ancestor without resolving away symlinks."""
    try:
        for part in reversed((path, *path.parents)):
            if create and not part.exists() and not part.is_symlink():
                part.mkdir(mode=0o700)
            info = part.lstat()
            if not stat.S_ISDIR(info.st_mode):
                raise RecordError("Unsafe directory")
    except OSError:
        raise RecordError("Unsafe directory") from None


def _write(path, data):
    _directory(path.parent)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    except OSError:
        raise RecordError("Cannot create record") from None
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
    except OSError:
        path.unlink(missing_ok=True)
        raise RecordError("Cannot write record") from None


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _read(path, digest):
    _directory(path.parent)
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_RECORD_BYTES:
            raise RecordError("Unsafe record")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as stream:
            data = stream.read(MAX_RECORD_BYTES + 1)
        if hashlib.sha256(data).hexdigest() != digest:
            raise RecordError("Record integrity failure")
        return json.loads(data)
    except (OSError, ValueError, UnicodeError):
        raise RecordError("Record integrity failure") from None


class RunStore:
    """Single-process append-only store: retain the object for the run lifetime.

    Use create(), not the constructor. No writable reopen API is provided: the
    in-memory hash ledger rejects externally added or modified records. seal_run
    stores a checkpoint for later read-only verify_archive checks. Hashes
    bind caller-supplied execution facts; they do not attest remote execution or
    factual correctness. Catalog validation is mandatory via summarize().
    """

    def __init__(self, path, manifest_digest):
        self._path = path
        self._manifest_digest = manifest_digest
        self._calls = {}
        self._answers = {}

    @property
    def path(self):
        return self._path

    @classmethod
    def create(cls, base_path, manifest):
        if not isinstance(manifest, dict) or any(
            not _text(manifest.get(key)) for key in ("timestamp", "model", "execution_mode")
        ):
            raise RecordError("Invalid manifest")
        data = _encode(manifest)
        try:
            base = Path(base_path).absolute()
            if ".." in base.parts:
                raise RecordError("Unsafe directory")
            _directory(base, create=True)
            path = base / str(uuid.uuid4())
            path.mkdir(mode=0o700)
            for name in ("calls", "answers"):
                (path / name).mkdir(mode=0o700)
            _write(path / "manifest.json", data)
        except (OSError, TypeError):
            raise RecordError("Cannot create run") from None
        return cls(path, hashlib.sha256(data).hexdigest())

    def save_call(self, call_id, record_dict):
        """Save caller-supplied execution facts; return {call_id, sha256}."""
        if (self.path / "checkpoint.json").exists() or (self.path / "checkpoint.json").is_symlink():
            raise RecordError("Run is sealed")
        _identifier(call_id)
        if call_id in self._calls:
            raise RecordError("Record already exists")
        if not isinstance(record_dict, dict) or not all(key in record_dict for key in ("tool", "arguments", "result", "is_error", "started_at", "finished_at")):
            raise RecordError("Invalid call")
        if not all(_text(record_dict[key]) for key in ("tool", "started_at", "finished_at")) or type(record_dict["is_error"]) is not bool or type(record_dict["arguments"]) is not dict:
            raise RecordError("Invalid call")
        data = _encode(record_dict)
        _write(self.path / "calls" / (call_id + ".json"), data)
        digest = hashlib.sha256(data).hexdigest()
        self._calls[call_id] = digest
        return {"call_id": call_id, "sha256": digest}

    def _evidence(self, record):
        direct = record.get("call_ids", [])
        reused = record.get("reused_call_ids", [])
        if type(direct) is not list or type(reused) is not list:
            raise RecordError("Invalid evidence")
        ids = [_identifier(value) for value in direct + reused]
        if len(set(ids)) != len(ids):
            raise RecordError("Invalid evidence")
        evidence, calls = [], []
        for call_id in ids:
            digest = self._calls.get(call_id)
            if digest is None:
                raise RecordError("Missing evidence")
            calls.append(_read(self.path / "calls" / (call_id + ".json"), digest))
            evidence.append({"call_id": call_id, "sha256": digest, "reused": call_id in reused})
        return evidence, calls

    def _answer(self, record):
        if type(record) is not dict or record.get("status") not in STATUSES:
            raise RecordError("Invalid answer status")
        evidence, calls = self._evidence(record)
        status = record["status"]
        if status == "answered":
            if not _text(record.get("answer")) or not any(not call["is_error"] for call in calls):
                raise RecordError("Answer requires successful evidence")
        elif not _text(record.get("reason")):
            raise RecordError("Answer requires reason")
        if status == "tool_error" and not any(call["is_error"] for call in calls):
            raise RecordError("Tool error requires failed evidence")
        return evidence, calls

    def save_answer(self, question_id, record_dict):
        """Save status/text/reason plus call_ids and optional reused_call_ids.

        Evidence hashes are generated here; caller-supplied evidence is rejected.
        Catalog/primary-tool validation occurs in summarize, not at write time.
        """
        if (self.path / "checkpoint.json").exists() or (self.path / "checkpoint.json").is_symlink():
            raise RecordError("Run is sealed")
        _identifier(question_id)
        if question_id in self._answers:
            raise RecordError("Record already exists")
        if type(record_dict) is not dict or "evidence" in record_dict:
            raise RecordError("Evidence must be generated")
        evidence, _ = self._answer(record_dict)
        data = _encode(dict(record_dict, evidence=evidence))
        _write(self.path / "answers" / (question_id + ".json"), data)
        self._answers[question_id] = hashlib.sha256(data).hexdigest()

    def summarize(self, catalog, selected_ids):
        """Validate the complete run and return counts, never private payloads.

        Catalog rows require unique id and primary_tool; optional expected_tools
        defaults to [primary_tool]. Their union is the allowed tool registry.
        Unknown or unselected answers fail, rather than silently disappearing.
        """
        _read(self.path / "manifest.json", self._manifest_digest)
        if type(catalog) is not list or type(selected_ids) is not list:
            raise RecordError("Invalid catalog or selection")
        questions, allowed_tools, registry = {}, {}, set()
        for row in catalog:
            if type(row) is not dict:
                raise RecordError("Invalid catalog")
            question_id = _identifier(row.get("id"))
            primary = _identifier(row.get("primary_tool"))
            expected = row.get("expected_tools", [primary])
            if type(expected) is not list:
                raise RecordError("Invalid tool registry")
            expected = [_identifier(tool) for tool in expected]
            if question_id in questions or len(set(expected)) != len(expected):
                raise RecordError("Invalid catalog")
            registry.add(primary)
            registry.update(expected)
            questions[question_id] = primary
            allowed_tools[question_id] = set(expected)
        selected = {_identifier(value) for value in selected_ids}
        if len(selected) != len(selected_ids) or not selected <= questions.keys():
            raise RecordError("Invalid selection")
        for name, saved in (("calls", self._calls), ("answers", self._answers)):
            directory = self.path / name
            _directory(directory)
            try:
                if {path.name for path in directory.iterdir()} != {key + ".json" for key in saved}:
                    raise RecordError("Unexpected or missing records")
            except OSError:
                raise RecordError("Cannot inspect records") from None
        if not self._answers.keys() <= selected:
            raise RecordError("Unknown or unselected answer")
        expected_primary = {questions[key] for key in selected}
        called = set()
        for call_id, digest in self._calls.items():
            call = _read(self.path / "calls" / (call_id + ".json"), digest)
            if call["tool"] not in registry:
                raise RecordError("Unregistered tool")
            if call["tool"] in expected_primary:
                called.add(call["tool"])
        counts = dict.fromkeys((*STATUSES, "not_run"), 0)
        counts["not_run"] = len(selected) - len(self._answers)
        answered, referenced, reused, direct = set(), set(), set(), set()
        for question_id, digest in self._answers.items():
            record = _read(self.path / "answers" / (question_id + ".json"), digest)
            evidence, calls = self._answer(record)
            if any(call["tool"] not in allowed_tools[question_id] for call in calls):
                raise RecordError("Unexpected question tool evidence")
            if record.get("evidence") != evidence:
                raise RecordError("Evidence integrity failure")
            for ref in evidence:
                call_id = ref["call_id"]
                referenced.add(call_id)
                if ref["reused"]:
                    reused.add(call_id)
                elif call_id in direct:
                    raise RecordError("Evidence reuse must be explicit")
                else:
                    direct.add(call_id)
            primary = questions[question_id]
            primary_calls = [call for call in calls if call["tool"] == primary]

            if record["status"] == "answered":
                if primary in allowed_tools[question_id] and not any(not call["is_error"] for call in primary_calls):
                    raise RecordError("Answer lacks primary tool evidence")
                if any(not call["is_error"] for call in primary_calls):
                    answered.add(primary)
            counts[record["status"]] += 1
        return {
            "catalog_total": len(questions), "selected_total": len(selected),
            "unselected_not_run": len(questions) - len(selected),
            "selected_counts": counts,
            "primary_tools": {"expected": len(expected_primary), "called": len(called), "answered": len(answered)},
            "calls": {"total": len(self._calls), "referenced": len(referenced), "reused": len(reused)},
        }


def seal_run(store, catalog, selected_ids):
    """Close an append-only run with one exclusive, private checkpoint file."""
    summary = store.summarize(catalog, selected_ids)
    checkpoint = {
        "version": 1, "catalog": catalog, "selected_ids": selected_ids,
        "manifest_sha256": store._manifest_digest, "calls": dict(store._calls),
        "answers": dict(store._answers), "summary": summary,
    }
    _write(store.path / "checkpoint.json", _encode(checkpoint))
    return summary


def verify_archive(path):
    """Read-only integrity/coverage check after the original process exits.

    The local checkpoint is a trusted-owner receipt, not a signature or proof
    that remote calls happened. Editing both a record and receipt defeats this
    checksum check. Existing secret/ACL and single-process limits still apply.
    """
    try:
        path = Path(path).absolute()
        if ".." in path.parts:
            raise RecordError("Unsafe archive")
        _directory(path)
        receipt = path / "checkpoint.json"
        info = receipt.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_RECORD_BYTES:
            raise RecordError("Invalid checkpoint")
        fd = os.open(receipt, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as stream:
            data = stream.read(MAX_RECORD_BYTES + 1)
        if len(data) > MAX_RECORD_BYTES:
            raise RecordError("Invalid checkpoint")
        checkpoint = json.loads(data)
        fields = {"version", "catalog", "selected_ids", "manifest_sha256", "calls", "answers", "summary"}
        if type(checkpoint) is not dict or set(checkpoint) != fields or type(checkpoint["version"]) is not int or checkpoint["version"] != 1:
            raise RecordError("Invalid checkpoint")
        digest = checkpoint["manifest_sha256"]
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise RecordError("Invalid checkpoint")
        for name in ("calls", "answers"):
            ledger = checkpoint[name]
            if type(ledger) is not dict:
                raise RecordError("Invalid checkpoint")
            for identifier, sha in ledger.items():
                _identifier(identifier)
                if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
                    raise RecordError("Invalid checkpoint")
        store = RunStore(path, digest)
        store._calls = checkpoint["calls"]
        store._answers = checkpoint["answers"]
        summary = store.summarize(checkpoint["catalog"], checkpoint["selected_ids"])
        if summary != checkpoint["summary"]:
            raise RecordError("Archive summary mismatch")
        return summary
    except (OSError, TypeError, ValueError, RecursionError):
        raise RecordError("Archive verification failed") from None

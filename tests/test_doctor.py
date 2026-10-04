"""Offline diagnostics contracts; only synthetic credentials and state."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.fixture(autouse=True)
def isolated_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for key in ("YONSEI_ID", "YONSEI_PASSWORD", "ID", "password", "PASSWORD"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.setenv("RUN_LIVE_PORTAL", "0")
    monkeypatch.setenv("RUN_LIVE_LLM", "0")


def run_python(code, tmp_path):
    env = {key: os.environ[key] for key in ("SystemRoot", "WINDIR") if key in os.environ}
    env.update(PYTHON_DOTENV_DISABLED="1", RUN_LIVE_PORTAL="0", RUN_LIVE_LLM="0",
               HOME=str(tmp_path), USERPROFILE=str(tmp_path), PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run([sys.executable, "-B", "-c", code], cwd=tmp_path,
                          env=env, capture_output=True, text=True, encoding="utf-8", timeout=20)


def test_entrypoint_import_is_lazy_and_default_still_runs_stdio(tmp_path):
    result = run_python('''
import sys, types

def audit(event, args):
    if event == "import" and args[0] in {"yonsei_portal_mcp.config", "yonsei_portal_mcp.server"}:
        raise AssertionError("eager server import")
sys.addaudithook(audit)
from yonsei_portal_mcp.__main__ import main
stub = types.ModuleType("yonsei_portal_mcp.server")
stub.mcp = types.SimpleNamespace(run=lambda: print("STDIO"))
sys.modules[stub.__name__] = stub
main([])
''', tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "STDIO"


def test_configuration_reports_only_presence_and_explicit_sources(tmp_path):
    from yonsei_portal_mcp.doctor import inspect_configuration

    fixture = tmp_path / ".env"
    fixture.write_text('YONSEI_ID="fixture-student"\nYONSEI_PASSWORD="fixture-password"\n', encoding="utf-8")
    automatic = inspect_configuration(environ={}, cwd=tmp_path)
    assert automatic["dotenv"] == {"source": "cwd", "exists": True, "inspected": False}
    assert automatic["credentials"]["YONSEI_ID"] == {"present": False, "source": "missing"}
    assert automatic["authenticated_features"] == "unconfigured"

    explicit = inspect_configuration(env_file=fixture, environ={"YONSEI_ID": "environment-secret"}, cwd=tmp_path)
    assert explicit["dotenv"] == {"source": "explicit", "exists": True, "inspected": True}
    assert explicit["credentials"]["YONSEI_ID"] == {"present": True, "source": "environment:YONSEI_ID"}
    assert explicit["credentials"]["YONSEI_PASSWORD"] == {"present": True, "source": "env_file:YONSEI_PASSWORD"}
    assert explicit["authenticated_features"] == "configured_not_verified"
    encoded = json.dumps(explicit)
    assert "fixture-student" not in encoded and "fixture-password" not in encoded
    assert "environment-secret" not in encoded and "length" not in encoded


def test_real_stdio_handshake_is_isolated_and_never_reads_secrets(tmp_path):
    # The hook runs inside BOTH the doctor process and its actual server child.
    # Output pattern checks alone would not demonstrate isolation.
    hook = '''
import os, subprocess, sys
from pathlib import Path
marker = Path(__file__).with_name("audit-loaded")
with marker.open("a") as stream:
    stream.write("loaded\\n")
def audit(event, args):
    if event in {"socket.connect", "socket.getaddrinfo"}:
        raise AssertionError("network forbidden")
    if event == "open" and isinstance(args[0], (str, bytes)):
        path = os.fsdecode(args[0]).replace("\\\\", "/")
        if path.endswith("/.env") or "/.session/" in path:
            raise AssertionError("secret read forbidden")
    if event == "subprocess.Popen":
        _, command, cwd, env = args
        expected = [sys.executable, "-B", "-m", "yonsei_portal_mcp"]
        # Windows audits the serialized command line; POSIX audits argv.
        assert command == (subprocess.list2cmdline(expected) if isinstance(command, str) else expected)
        assert "doctor" not in command
        assert env["PYTHON_DOTENV_DISABLED"] == "1"
        assert env["RUN_LIVE_PORTAL"] == env["RUN_LIVE_LLM"] == "0"
        assert not any(key in env for key in ("YONSEI_ID", "YONSEI_PASSWORD", "OPENAI_API_KEY", "ID", "PASSWORD"))
        assert Path(cwd).resolve() != Path.cwd().resolve()
        assert Path(env["HOME"]) == Path(cwd)
        assert Path(env["YONSEI_STORAGE_STATE"]).is_relative_to(Path(cwd))
sys.addaudithook(audit)
'''
    (tmp_path / "sitecustomize.py").write_text(hook, encoding="utf-8")
    (tmp_path / ".env").write_text("YONSEI_PASSWORD=NEVER_READ_SYNTHETIC\n", encoding="utf-8")
    code = '''
import os, sys
from pathlib import Path
import sitecustomize
from yonsei_portal_mcp import doctor
os.environ.update(YONSEI_ID="student-secret", YONSEI_PASSWORD="password-secret", OPENAI_API_KEY="llm-secret")
original = doctor.child_environment
def instrumented(root):
    env = original(root)
    env["PYTHONPATH"] = str(Path.cwd())
    return env
doctor.child_environment = instrumented
import json
print(json.dumps(doctor.probe_stdio(timeout=10)))
'''
    result = run_python(code, tmp_path)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "ok", report
    assert report["tool_count"] > 0
    assert report["protocol_version"]
    assert (tmp_path / "audit-loaded").read_text().count("loaded") == 2


@pytest.mark.parametrize("script,code", [
    ("import time; time.sleep(30)", "timeout"),
    ('print("secret-invalid-json", flush=True)', "protocol_error"),
])
def test_stdio_failures_are_bounded_reaped_and_sanitized(tmp_path, monkeypatch, script, code):
    from yonsei_portal_mcp import doctor
    import time

    children = []
    real_popen = subprocess.Popen
    def record(*args, **kwargs):
        child = real_popen(*args, **kwargs)
        children.append(child)
        return child
    monkeypatch.setattr(doctor.subprocess, "Popen", record)
    start = time.monotonic()
    report = doctor._stdio_exchange([sys.executable, "-B", "-c", script],
                                   doctor.child_environment(tmp_path), tmp_path, timeout=0.3)
    assert report == {"status": "error", "code": code}
    assert time.monotonic() - start < 5
    assert children and children[0].poll() is not None
    assert "secret" not in json.dumps(report)


def test_installation_versions_and_missing_dependency(monkeypatch):
    from yonsei_portal_mcp import doctor
    from importlib import metadata

    versions = doctor.inspect_installation()
    assert versions["status"] == "ok"
    assert versions["packages"]["yonsei-portal-mcp"]
    assert versions["packages"]["mcp"]
    assert versions["packages"]["anyio"]
    original = metadata.version
    def missing(name):
        if name == "mcp":
            raise metadata.PackageNotFoundError(name)
        return original(name)
    monkeypatch.setattr(metadata, "version", missing)
    missing_report = doctor.inspect_installation()
    assert missing_report["status"] == "error"
    assert missing_report["packages"]["mcp"] is None


def test_browser_worker_never_launches_by_default_and_optional_launch_is_ephemeral(tmp_path, monkeypatch):
    from yonsei_portal_mcp import doctor
    from contextlib import nullcontext
    from types import SimpleNamespace

    executable = tmp_path / "chromium"
    executable.write_text("synthetic executable", encoding="utf-8")
    executable.chmod(0o700)
    calls = []
    context = SimpleNamespace(
        route=lambda pattern, action: calls.append(("route", pattern)),
        new_page=lambda: calls.append(("page", "about:blank")),
        close=lambda: calls.append(("context_close",)),
    )
    browser = SimpleNamespace(
        new_context=lambda **kw: (calls.append(("context", kw)) or context),
        close=lambda: calls.append(("browser_close",)),
    )
    chromium = SimpleNamespace(executable_path=str(executable),
        launch=lambda **kw: (calls.append(("launch", kw)) or browser))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", SimpleNamespace(
        sync_playwright=lambda: nullcontext(SimpleNamespace(chromium=chromium))))
    assert doctor._browser_worker(False, 2) == {"status": "ok", "available": True, "launched": False}
    assert not calls
    assert doctor._browser_worker(True, 2) == {"status": "ok", "available": True, "launched": True}
    assert calls[0][0] == "launch" and calls[0][1]["headless"] is True
    assert calls[1] == ("context", {"offline": True, "service_workers": "block"})
    assert calls[2] == ("route", "**/*")
    assert calls[-2:] == [("context_close",), ("browser_close",)]
    executable.unlink()
    assert doctor._browser_worker(False, 2) == {"status": "warning", "available": False, "launched": False, "code": "chromium_missing"}


def test_browser_probe_has_clean_environment_and_bounded_errors(tmp_path, monkeypatch):
    from yonsei_portal_mcp import doctor

    monkeypatch.setenv("YONSEI_PASSWORD", "SYNTHETIC_SECRET")
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path / "browsers"))
    def timeout(command, **kwargs):
        assert "SYNTHETIC_SECRET" not in json.dumps(kwargs["env"])
        assert kwargs["env"]["PLAYWRIGHT_BROWSERS_PATH"] == str(tmp_path / "browsers")
        assert kwargs["cwd"] != Path.cwd()
        assert kwargs["timeout"] <= 5
        raise subprocess.TimeoutExpired(command, kwargs["timeout"], output="SECRET")
    monkeypatch.setattr(doctor.subprocess, "run", timeout)
    assert doctor.probe_browser(launch=True, timeout=1) == {
        "status": "error", "available": False, "launched": False, "code": "browser_timeout"}


def test_doctor_json_command_is_public_only_and_import_safe(tmp_path):
    result = run_python('''
import sys, os

def audit(event, args):
    if event == "import" and args[0] in {"yonsei_portal_mcp.config", "yonsei_portal_mcp.server"}:
        raise AssertionError("eager server import")
    if event in {"socket.connect", "socket.getaddrinfo"}:
        raise AssertionError("network forbidden")
    if event == "open" and isinstance(args[0], (str, bytes)):
        path = os.fsdecode(args[0]).replace("\\\\", "/")
        if path.endswith("/.env") or "/.session/" in path:
            raise AssertionError("secret read forbidden")
sys.addaudithook(audit)
from yonsei_portal_mcp.__main__ import main
raise SystemExit(main(["doctor", "--json", "--timeout", "5"]))
''', tmp_path)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["exit_code"] == 0
    assert report["public_features"] == "local_ready_not_live_verified"
    assert report["checks"]["configuration"]["authenticated_features"] == "unconfigured"
    assert report["checks"]["stdio"]["tool_count"] > 0
    assert report["checks"]["chromium"]["launched"] is False
    assert not result.stderr


@pytest.mark.parametrize("args,stdio,installation,expected", [
    ([], "ok", "ok", 0),
    (["--browser"], "ok", "ok", 1),
    ([], "error", "ok", 1),
    ([], "ok", "error", 1),
    (["--env-file", "missing-secret-path"], "ok", "ok", 2),
])
def test_cli_exit_codes_are_meaningful(args, stdio, installation, expected, monkeypatch, capsys):
    from yonsei_portal_mcp import doctor
    monkeypatch.setattr(doctor, "inspect_installation", lambda: {"status": installation, "python": "3.11", "packages": {"mcp": "1.30.0"}})
    monkeypatch.setattr(doctor, "probe_stdio", lambda **kw: {"status": stdio, "tool_count": 1, "code": "timeout"})
    monkeypatch.setattr(doctor, "probe_browser", lambda **kw: {"status": "warning", "available": False, "launched": False, "code": "chromium_missing"})
    assert doctor.main(["--json", *args]) == expected
    output = capsys.readouterr()
    report = json.loads(output.out)
    assert report["exit_code"] == expected
    assert "missing-secret-path" not in output.out + output.err
    assert doctor.main(args) == expected
    human = capsys.readouterr().out
    assert "공개 기능" in human
    assert "로그인" in human
    assert "mcp" in human
    assert "missing-secret-path" not in human


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "121", "SYNTHETIC_SECRET"])
def test_invalid_timeout_is_rejected_without_echoing_values(value, capsys):
    from yonsei_portal_mcp import doctor
    with pytest.raises(SystemExit) as exc:
        doctor.main(["--timeout", value])
    assert exc.value.code == 2
    assert "SYNTHETIC_SECRET" not in capsys.readouterr().err


def test_child_disables_legacy_dotenv_without_changing_normal_stdio(tmp_path):
    result = run_python('''
import os, sys, types
from yonsei_portal_mcp.__main__ import main
os.environ["_YONSEI_DOCTOR_CHILD"] = "1"
dotenv = types.ModuleType("dotenv")
def unsafe_load(*args, **kwargs):
    raise AssertionError("legacy dotenv attempted a read")
dotenv.load_dotenv = unsafe_load
sys.modules["dotenv"] = dotenv
server = types.ModuleType("yonsei_portal_mcp.server")
server.mcp = types.SimpleNamespace(run=lambda: print(dotenv.load_dotenv()))
sys.modules[server.__name__] = server
main([])
''', tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False"
    from yonsei_portal_mcp.doctor import child_environment
    assert child_environment(tmp_path)["_YONSEI_DOCTOR_CHILD"] == "1"


@pytest.mark.parametrize("version", ["SYNTHETIC_SECRET", "2024-11-05"])
def test_stdio_rejects_invalid_handshake_without_reflecting_payload(tmp_path, version):
    from yonsei_portal_mcp import doctor
    script = '''
import json, sys
for line in sys.stdin:
    message = json.loads(line)
    if message.get("id") == 1:
        print(json.dumps({"jsonrpc":"2.0", "id":1, "result":{"protocolVersion":"SYNTHETIC_SECRET"}}), flush=True)
    if message.get("id") == 2:
        print(json.dumps({"jsonrpc":"2.0", "id":2, "result":{"tools":[{"bad":"tool"}]}}), flush=True)
'''.replace("SYNTHETIC_SECRET", version)
    report = doctor._stdio_exchange([sys.executable, "-B", "-c", script],
                                   doctor.child_environment(tmp_path), tmp_path, timeout=1)
    assert report == {"status": "error", "code": "protocol_error"}


def test_help_supports_utf8_when_redirected_and_does_not_import_server(tmp_path):
    result = run_python('''
import sys
sys.stdout.reconfigure(encoding="ascii")
sys.stderr.reconfigure(encoding="ascii")
def audit(event, args):
    if event == "import" and args[0] == "yonsei_portal_mcp.server":
        raise AssertionError("server imported for help")
sys.addaudithook(audit)
from yonsei_portal_mcp.__main__ import main
raise SystemExit(main(["doctor", "--help"]))
''', tmp_path)
    assert result.returncode == 0, result.stderr
    assert "로그인" in result.stdout


def test_stdio_temp_directory_failure_is_sanitized(monkeypatch):
    from yonsei_portal_mcp import doctor
    def denied(*args, **kwargs):
        raise PermissionError("SYNTHETIC_SECRET_PATH")
    monkeypatch.setattr(doctor.tempfile, "TemporaryDirectory", denied)
    assert doctor.probe_stdio() == {"status": "error", "code": "stdio_unavailable"}

"""Offline dotenv contracts; all configuration files are synthetic."""
from __future__ import annotations

import importlib
import importlib.util
import os
from pathlib import Path

import dotenv
import pytest


def _loader():
    name = f"{__package__}.env"
    assert importlib.util.find_spec(name) is not None, "shared harness env loader is missing"
    return importlib.import_module(name)


@pytest.fixture
def synthetic_env(monkeypatch, tmp_path):
    root = tmp_path / "repo"
    (root / "tests" / "llm").mkdir(parents=True)
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    monkeypatch.setattr(os, "environ", {})
    monkeypatch.setattr(dotenv, "load_dotenv", dotenv.main.load_dotenv)
    monkeypatch.setattr(dotenv.main, "find_dotenv", lambda *a, **kw: str(root / ".env"))
    module = _loader()
    monkeypatch.setattr(module, "__file__", str(root / "tests" / "llm" / "env.py"))
    return module, root


def test_base_dotenv_keeps_legacy_discovery_and_process_precedence(synthetic_env):
    module, root = synthetic_env
    (root / ".env").write_text("LLM_PROVIDER=legacy\nYONSEI_ID=synthetic-id\n", encoding="utf-8")
    os.environ["LLM_PROVIDER"] = "process"
    module.load_harness_env()
    assert os.environ["LLM_PROVIDER"] == "process"
    assert os.environ["YONSEI_ID"] == "synthetic-id"


@pytest.mark.parametrize("process_optin,base_optin,loaded", [
    (None, "1", True), ("1", "0", True), ("0", "1", False),
    (None, None, False), ("true", "1", False), ("", "1", False),
])
def test_llm_file_requires_exact_live_optin_after_base(synthetic_env, monkeypatch, process_optin, base_optin, loaded):
    module, root = synthetic_env
    (root / ".env").write_text(
        f"RUN_LIVE_LLM={base_optin}\n" if base_optin is not None else "", encoding="utf-8",
    )
    (root / ".env.llm").write_text("OPENAI_API_KEY=synthetic-key\nRUN_LIVE_LLM=1\n", encoding="utf-8")
    if process_optin is not None:
        os.environ["RUN_LIVE_LLM"] = process_optin
    real_values = dotenv.dotenv_values
    reads = []

    def guarded_values(path, **kwargs):
        assert loaded, "LLM file read without live opt-in"
        reads.append(Path(path))
        return real_values(path, **kwargs)

    monkeypatch.setattr(dotenv, "dotenv_values", guarded_values)
    module.load_harness_env()
    assert (os.environ.get("OPENAI_API_KEY") == "synthetic-key") is loaded
    assert reads == ([root / ".env.llm"] if loaded else [])


ALLOWED_KEYS = {
    "LLM_PROVIDER", "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_DEPLOYMENT",
    "AZURE_OPENAI_API_VERSION", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_APIM_SUBSCRIPTION_KEY",
    "OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_BASE_URL",
    "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL",
    "GEMINI_API_KEY", "GEMINI_MODEL", "GEMINI_BASE_URL",
}


def test_llm_file_only_loads_provider_allowlist(synthetic_env):
    module, root = synthetic_env
    blocked = {
        "YONSEI_ID", "YONSEI_PASSWORD", "ID", "PASSWORD", "BROWSER_PATH",
        "PLAYWRIGHT_BROWSERS_PATH", "STORAGE_STATE_PATH", "HEADED", "HOME",
        "RUN_LIVE_PORTAL", "RUN_LIVE_LLM", "PYTHON_DOTENV_DISABLED", "UNKNOWN_LLM_KEY",
    }
    (root / ".env.llm").write_text(
        "\n".join(f"{key}=synthetic-value" for key in sorted(ALLOWED_KEYS | blocked)), encoding="utf-8",
    )
    os.environ["RUN_LIVE_LLM"] = "1"
    module.load_harness_env()
    assert {key for key in blocked if key in os.environ} == {"RUN_LIVE_LLM"}
    assert os.environ["RUN_LIVE_LLM"] == "1"
    assert all(os.environ.get(key) == "synthetic-value" for key in ALLOWED_KEYS)


def test_llm_values_never_interpolate_inherited_or_file_secrets(synthetic_env):
    module, root = synthetic_env
    os.environ.update(RUN_LIVE_LLM="1", YONSEI_PASSWORD="synthetic-inherited-secret")
    (root / ".env.llm").write_text(
        "LOCAL_SECRET=synthetic-local-secret\n"
        "OPENAI_API_KEY=${YONSEI_PASSWORD}\nOPENAI_MODEL=${LOCAL_SECRET}\n"
        "GEMINI_MODEL=${MISSING:-synthetic-default}\n", encoding="utf-8",
    )
    module.load_harness_env()
    assert os.environ["OPENAI_API_KEY"] == "${YONSEI_PASSWORD}"
    assert os.environ["OPENAI_MODEL"] == "${LOCAL_SECRET}"
    assert os.environ["GEMINI_MODEL"] == "${MISSING:-synthetic-default}"


@pytest.mark.parametrize("target", ["load_dotenv", "dotenv_values"])
def test_loading_errors_never_expose_raw_details(synthetic_env, monkeypatch, capsys, target):
    import traceback

    module, _ = synthetic_env
    os.environ["RUN_LIVE_LLM"] = "1"

    def broken(*args, **kwargs):
        raise OSError("synthetic-private-key-or-path")

    monkeypatch.setattr(dotenv, target, broken)
    with pytest.raises(RuntimeError, match="details suppressed") as caught:
        module.load_harness_env()
    assert "synthetic-private-key-or-path" not in "".join(traceback.format_exception(caught.value))
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("entrypoint", ["conftest", "demo", "scenarios", "dump_tools"])
def test_every_harness_entrypoint_loads_split_configuration(synthetic_env, entrypoint):
    _, root = synthetic_env
    (root / ".env").write_text("RUN_LIVE_LLM=1\n", encoding="utf-8")
    (root / ".env.llm").write_text("LLM_PROVIDER=gemini\nGEMINI_API_KEY=synthetic-key\n", encoding="utf-8")
    module = importlib.import_module(f"{__package__}.{entrypoint}")
    importlib.reload(module)
    assert os.environ.get("LLM_PROVIDER") == "gemini"
    assert os.environ.get("GEMINI_API_KEY") == "synthetic-key"


def test_base_can_disable_llm_file_before_it_is_accessed(synthetic_env, monkeypatch):
    module, root = synthetic_env
    (root / ".env").write_text("RUN_LIVE_LLM=1\nPYTHON_DOTENV_DISABLED=yes\n", encoding="utf-8")

    def forbidden(*args, **kwargs):
        pytest.fail("base disabled flag must prevent LLM file access")

    monkeypatch.setattr(dotenv, "dotenv_values", forbidden)
    module.load_harness_env()


@pytest.mark.parametrize("process_value", [None, "process", ""])
@pytest.mark.parametrize("base_value", [None, "legacy", ""])
def test_precedence_process_then_legacy_then_llm(synthetic_env, process_value, base_value, capsys):
    module, root = synthetic_env
    (root / ".env").write_text(
        "RUN_LIVE_LLM=1\n" + (f"OPENAI_MODEL={base_value}\n" if base_value is not None else ""),
        encoding="utf-8",
    )
    (root / ".env.llm").write_text("OPENAI_MODEL=fallback\n", encoding="utf-8")
    if process_value is not None:
        os.environ["OPENAI_MODEL"] = process_value
    module.load_harness_env()
    expected = process_value if process_value is not None else base_value
    assert os.environ["OPENAI_MODEL"] == (expected if expected is not None else "fallback")
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("root_file_exists", [False, True])
def test_llm_path_never_scans_cwd_or_parents(synthetic_env, root_file_exists):
    module, root = synthetic_env
    os.environ["RUN_LIVE_LLM"] = "1"
    for directory in (Path.cwd(), root.parent):
        (directory / ".env.llm").write_text("OPENAI_MODEL=wrong-location\n", encoding="utf-8")
    if root_file_exists:
        (root / ".env.llm").write_text("OPENAI_MODEL=repository-root\n", encoding="utf-8")
    module.load_harness_env()
    assert os.environ.get("OPENAI_MODEL") == ("repository-root" if root_file_exists else None)


def test_optional_missing_bare_and_empty_values(synthetic_env):
    module, root = synthetic_env
    os.environ["RUN_LIVE_LLM"] = "1"
    module.load_harness_env()  # Both files absent is harmless.
    (root / ".env.llm").write_text("OPENAI_MODEL\nOPENAI_API_KEY=\n", encoding="utf-8")
    module.load_harness_env()
    assert "OPENAI_MODEL" not in os.environ
    assert os.environ["OPENAI_API_KEY"] == ""


@pytest.mark.parametrize("entrypoint", ["conftest", "demo", "scenarios", "dump_tools"])
def test_disabled_entrypoints_never_invoke_dotenv(synthetic_env, monkeypatch, entrypoint):
    os.environ.update(PYTHON_DOTENV_DISABLED="TRUE", RUN_LIVE_LLM="1")

    def forbidden(*args, **kwargs):
        pytest.fail("disabled entrypoint accessed dotenv")

    monkeypatch.setattr(dotenv, "load_dotenv", forbidden)
    monkeypatch.setattr(dotenv, "dotenv_values", forbidden)
    module = importlib.import_module(f"{__package__}.{entrypoint}")
    importlib.reload(module)


@pytest.mark.parametrize("entrypoint", ["demo", "scenarios"])
@pytest.mark.parametrize("provider", ["azure-openai", "openai", "anthropic", "gemini"])
@pytest.mark.parametrize("explicit", [False, True])
def test_cli_provider_overrides_split_file_default(synthetic_env, monkeypatch, entrypoint, provider, explicit):
    import sys

    _, root = synthetic_env
    (root / ".env").write_text("RUN_LIVE_LLM=1\n", encoding="utf-8")
    (root / ".env.llm").write_text(f"LLM_PROVIDER={provider}\n", encoding="utf-8")
    module = importlib.import_module(f"{__package__}.{entrypoint}")
    importlib.reload(module)
    calls = []

    def unavailable(name):
        calls.append(name)
        raise module.ProviderUnavailable("synthetic no-network provider")

    monkeypatch.setattr(module, "make_provider", unavailable)
    monkeypatch.setattr(sys, "argv", [entrypoint] + (["--provider", "openai"] if explicit else []))
    with pytest.raises(SystemExit) as caught:
        module.main()
    assert caught.value.code == (2 if entrypoint == "demo" else 99)
    assert calls == ["openai" if explicit else provider]


def test_ordinary_mcp_startup_reads_only_base_dotenv(tmp_path):
    """Run real installed-package startup with only the serving loop mocked."""
    import subprocess
    import sys
    import textwrap

    repo = Path(__file__).resolve().parents[2]
    (tmp_path / ".env").write_text("YONSEI_ID=synthetic-base\n", encoding="utf-8")
    (tmp_path / ".env.llm").write_text(
        "YONSEI_ID=forbidden-llm\nOPENAI_API_KEY=forbidden-llm\n", encoding="utf-8",
    )
    code = textwrap.dedent('''
        import os, sys
        from pathlib import Path
        base = Path.cwd() / ".env"
        reads = []
        def audit(event, args):
            if event in {"socket.connect", "socket.getaddrinfo", "subprocess.Popen"}:
                raise AssertionError("unexpected external access")
            if event == "open" and isinstance(args[0], (str, bytes)):
                path = Path(os.fsdecode(args[0])).absolute()
                if path.name == ".env.llm":
                    raise AssertionError("ordinary MCP read LLM file")
                if path.name == ".env":
                    assert path == base, "non-synthetic dotenv access"
                    reads.append(str(path))
                if path.name in {"id_rsa", "id_ed25519"} or path.suffix in {".key", ".p12"}:
                    raise AssertionError("private key access")
                if "cookie" in path.name.lower() or path.name == "storage_state.json":
                    if path.suffix not in {".py", ".pyc"}:
                        raise AssertionError("session access")
        sys.addaudithook(audit)
        import dotenv.main
        dotenv.main.find_dotenv = lambda *a, **kw: str(base)
        from yonsei_portal_mcp import server
        calls = []
        server.mcp.run = lambda: calls.append("stdio")
        from yonsei_portal_mcp.__main__ import main
        assert main([]) == 0
        assert calls == ["stdio"]
        assert reads
        assert os.environ.get("YONSEI_ID") == "synthetic-base"
        assert "OPENAI_API_KEY" not in os.environ
        assert not any(name.startswith(("tests.llm", "llm.")) for name in sys.modules)
        print("base-only startup verified")
    ''')
    child_env = {
        "PATH": os.defpath, "PYTHONPATH": str(repo / "src"),
        "HOME": str(tmp_path), "USERPROFILE": str(tmp_path),
        "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1",
        "RUN_LIVE_LLM": "0", "RUN_LIVE_PORTAL": "0",
    }
    if "SystemRoot" in os.environ:
        child_env["SystemRoot"] = os.environ["SystemRoot"]
    completed = subprocess.run(
        [sys.executable, "-c", code], cwd=tmp_path, env=child_env,
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "base-only startup verified"


@pytest.mark.parametrize("disabled", ["1", "true", "TRUE", "t", "T", "yes", "YES", "y", "Y"])
def test_disabled_returns_before_any_file_access_even_with_old_dotenv(synthetic_env, monkeypatch, disabled):
    module, _ = synthetic_env
    os.environ.update(PYTHON_DOTENV_DISABLED=disabled, RUN_LIVE_LLM="1")

    def forbidden(*args, **kwargs):
        pytest.fail("disabled loader attempted dotenv or filesystem access")

    monkeypatch.setattr(dotenv, "load_dotenv", forbidden)
    monkeypatch.setattr(dotenv, "dotenv_values", forbidden)
    monkeypatch.setattr(Path, "resolve", forbidden)
    monkeypatch.setattr("builtins.open", forbidden)
    module.load_harness_env()

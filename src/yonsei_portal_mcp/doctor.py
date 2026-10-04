"""Offline installation diagnostics, deliberately independent of server/config.

Only an explicitly selected env file is read. No credentials, paths, raw
exceptions, server stderr or cookie content are included in diagnostic output.
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Mapping


_CREDENTIALS = {
    "YONSEI_ID": ("YONSEI_ID", "ID"),
    "YONSEI_PASSWORD": ("YONSEI_PASSWORD", "password", "PASSWORD"),
}


def inspect_configuration(
    env_file: Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> dict:
    """Report presence only; do not mutate os.environ or search parent folders.

    Explicit files are inspected without variable interpolation. This is not a
    login check and does not claim to reproduce implicit dotenv discovery.
    """
    environ = os.environ if environ is None else environ
    candidate = Path(env_file) if env_file is not None else (cwd or Path.cwd()) / ".env"
    exists = candidate.is_file()
    values: dict[str, str] = {}
    if env_file is not None:
        from dotenv.parser import parse_stream

        with candidate.open(encoding="utf-8") as stream:
            for binding in parse_stream(stream):
                if binding.error:
                    raise ValueError("env_file_invalid")
                if binding.key is not None and binding.key in {key for aliases in _CREDENTIALS.values() for key in aliases}:
                    values[binding.key] = binding.value or ""
    credentials = {}
    for name, aliases in _CREDENTIALS.items():
        present, source = False, "missing"
        for alias in aliases:
            value = environ.get(alias, values.get(alias, ""))
            # Match config's alias ordering: whitespace is truthy before strip.
            if value:
                present = bool(value.strip())
                source = ("environment:" if alias in environ else "env_file:") + alias
                break
        credentials[name] = {"present": present, "source": source}
    return {
        "dotenv": {"source": "explicit" if env_file is not None else "cwd",
                   "exists": exists, "inspected": env_file is not None},
        "credentials": credentials,
        "authenticated_features": (
            "configured_not_verified" if all(item["present"] for item in credentials.values())
            else "unconfigured"
        ),
    }


def inspect_installation() -> dict:
    from importlib import metadata
    import platform

    packages = {}
    for name in ("yonsei-portal-mcp", "mcp", "anyio", "jsonschema", "playwright",
                 "python-dotenv", "httpx", "certifi", "beautifulsoup4"):
        try:
            packages[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            packages[name] = None
    return {"status": "ok" if all(packages.values()) and sys.version_info >= (3, 10) else "error",
            "python": platform.python_version(), "packages": packages}


def child_environment(root: Path) -> dict[str, str]:
    """An allowlist, never a copy of credentials, proxies or Python overrides."""
    env = {key: os.environ[key] for key in ("SystemRoot", "WINDIR") if key in os.environ}
    env.update({
        "PATH": os.defpath,
        "HOME": str(root), "USERPROFILE": str(root),
        "APPDATA": str(root), "LOCALAPPDATA": str(root),
        "XDG_CONFIG_HOME": str(root), "XDG_CACHE_HOME": str(root),
        "TMPDIR": str(root), "TMP": str(root), "TEMP": str(root),
        "PYTHON_DOTENV_DISABLED": "1", "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "PYTHONNOUSERSITE": "1",
        "RUN_LIVE_PORTAL": "0", "RUN_LIVE_LLM": "0", "_YONSEI_DOCTOR_CHILD": "1",
        "YONSEI_STORAGE_STATE": str(root / "state" / "unused.json"),
    })
    return env


def _stdio_exchange(command: list[str], env: dict[str, str], cwd: Path, timeout: float) -> dict:
    """Minimal JSONL MCP client: initialize + tools/list, never tools/call.

    A pipe-reader thread (rather than POSIX-only select) works on Windows too.
    Raw server output/errors are never forwarded. The owned child is reaped.
    """
    child = None
    reader = None
    messages: queue.Queue = queue.Queue(maxsize=64)
    deadline = time.monotonic() + timeout
    try:
        child = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        assert child.stdout is not None and child.stdin is not None
        output = child.stdout
        input_stream = child.stdin

        def read_lines():
            try:
                while True:
                    line = output.readline(2 * 1024 * 1024 + 1)
                    messages.put_nowait(line)
                    if not line or len(line) > 2 * 1024 * 1024:
                        return
            except (OSError, ValueError, queue.Full):
                return

        reader = threading.Thread(target=read_lines, daemon=True)
        reader.start()

        def send(message):
            input_stream.write((json.dumps(message) + "\n").encode("utf-8"))
            input_stream.flush()

        def receive(request_id):
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise queue.Empty
                line = messages.get(timeout=remaining)
                if not line or len(line) > 2 * 1024 * 1024:
                    raise ValueError("invalid_response")
                message = json.loads(line)
                if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
                    raise ValueError("invalid_response")
                if message.get("id") == request_id:
                    result = message.get("result")
                    if not isinstance(result, dict) or "error" in message:
                        raise ValueError("invalid_response")
                    return result

        send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "yonsei-portal-doctor", "version": "1"},
        }})
        initialized = receive(1)
        if initialized.get("protocolVersion") != "2024-11-05":
            raise ValueError("unsupported_protocol")
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        listed = receive(2)
        if not isinstance(listed.get("tools"), list) or not listed["tools"]:
            raise ValueError("invalid_tools")
        for tool in listed["tools"]:
            if (not isinstance(tool, dict) or not isinstance(tool.get("name"), str)
                    or not tool["name"] or not isinstance(tool.get("inputSchema"), dict)):
                raise ValueError("invalid_tools")
        return {"status": "ok", "tool_count": len(listed["tools"]),
                "protocol_version": initialized.get("protocolVersion")}
    except queue.Empty:
        return {"status": "error", "code": "timeout"}
    except (OSError, ValueError, TypeError):
        return {"status": "error", "code": "protocol_error"}
    finally:
        if child is not None:
            if child.stdin is not None:
                try:
                    child.stdin.close()
                except OSError:
                    pass
            # Give the server a bounded opportunity to perform lifespan cleanup.
            try:
                child.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
            if reader is not None:
                reader.join(timeout=0.5)
            if child.stdout is not None:
                child.stdout.close()


def _browser_worker(launch: bool, timeout: float) -> dict:
    """Executed only in a sanitized subprocess; never use a persistent profile."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        executable = Path(playwright.chromium.executable_path)
        available = executable.is_file() and (os.name == "nt" or os.access(executable, os.X_OK))
        if not available:
            return {"status": "warning", "available": False, "launched": False,
                    "code": "chromium_missing"}
        if launch:
            browser = playwright.chromium.launch(
                executable_path=str(executable), headless=True, timeout=timeout * 1000,
                args=["--disable-background-networking", "--disable-component-update",
                      "--host-resolver-rules=MAP * ~NOTFOUND"],
            )
            try:
                context = browser.new_context(offline=True, service_workers="block")
                try:
                    context.route("**/*", lambda route: route.abort())
                    context.new_page()  # about:blank only; no goto or cookie access.
                finally:
                    context.close()
            finally:
                browser.close()
        return {"status": "ok", "available": True, "launched": launch}


def probe_browser(launch: bool = False, timeout: float = 10.0) -> dict:
    # Keep only the browser binary location, not the user's profile or secrets.
    cache = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if not cache:
        if sys.platform == "darwin":
            cache = str(Path.home() / "Library" / "Caches" / "ms-playwright")
        elif sys.platform == "win32":
            cache = str(Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "ms-playwright")
        else:
            cache = str(Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "ms-playwright")
    if cache != "0":
        cache = str(Path(cache).resolve())
    error = {"status": "error", "available": False, "launched": False}
    script = ("import json; from yonsei_portal_mcp.doctor import _browser_worker; "
              f"print(json.dumps(_browser_worker({launch!r}, {timeout!r})))")
    try:
        with tempfile.TemporaryDirectory(prefix="yonsei-browser-doctor-") as folder:
            root = Path(folder)
            env = child_environment(root)
            env["PLAYWRIGHT_BROWSERS_PATH"] = cache
            result = subprocess.run([sys.executable, "-B", "-c", script], env=env, cwd=root,
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                    timeout=timeout + 3, check=False)
        if result.returncode != 0:
            return {**error, "code": "browser_failed"}
        return json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        return {**error, "code": "browser_timeout"}
    except (OSError, ValueError):
        return {**error, "code": "browser_failed"}


def probe_stdio(timeout: float = 10.0) -> dict:
    try:
        with tempfile.TemporaryDirectory(prefix="yonsei-doctor-") as folder:
            root = Path(folder)
            return _stdio_exchange([sys.executable, "-B", "-m", "yonsei_portal_mcp"],
                                   child_environment(root), root, timeout)
    except OSError:
        return {"status": "error", "code": "stdio_unavailable"}


def _print_human(report: dict) -> None:
    checks = report["checks"]
    installation = checks["installation"]
    print("yonsei-portal-mcp doctor — 로컬 설치·연결 진단")
    print("Python:", installation["python"])
    print("패키지:", ", ".join(f"{name}={version or '미설치'}"
                            for name, version in installation["packages"].items()))
    config = checks["configuration"]
    if config.get("status") == "error":
        print("설정: 지정한 .env 파일을 확인할 수 없습니다.")
    else:
        dotenv = config["dotenv"]
        source = "명시한 --env-file" if dotenv["source"] == "explicit" else "현재 작업 폴더의 .env만 확인"
        print(f"설정 출처: {source}; 존재={dotenv['exists']}; 내용 검사={dotenv['inspected']}")
        print("자동 .env 로딩: 진단에서는 사용하지 않음; 상위 폴더 탐색·변수 치환 없음")
        for name, item in config["credentials"].items():
            print(f"{name}: 존재={item['present']}; 출처={item['source']}")
        auth = "설정됨(인증 미검증)" if config["authenticated_features"] == "configured_not_verified" else "미설정(선택 기능)"
        print(f"인증 기능: {auth}")
    chromium = checks["chromium"]
    print(f"Chromium: 실행 파일={chromium['available']}; 시작 확인={chromium['launched']}")
    if not chromium["available"]:
        print("브라우저 기능이 필요하면: python -m playwright install chromium")
    stdio = checks["stdio"]
    if stdio["status"] == "ok":
        print(f"MCP stdio: initialize → tools/list 성공; 도구={stdio['tool_count']}")
    else:
        print("MCP stdio: 연결 실패 또는 제한 시간 초과; 설치 환경을 확인하세요.")
    public = "로컬 준비 확인(외부 조회 미검증)" if report["public_features"] == "local_ready_not_live_verified" else "로컬 준비 확인 실패"
    print(f"공개 기능: {public}")
    print("범위: 로그인·쿠키 읽기·포털·외부 LLM 호출 미실행. 진단은 보안 감사가 아닙니다.")
    print(f"종료 코드: {report['exit_code']}")


def main(argv: list[str] | None = None) -> int:
    """0: local public readiness; 1: required probe failure; 2: bad input/config.

    Credentials and Chromium are optional by default. --browser makes browser
    launch mandatory. No invocation verifies live portal/account availability.
    """
    import argparse
    import math

    # Windows redirected streams may otherwise use an ANSI code page. This is
    # doctor-only: never reconfigure the no-argument MCP stdio transport.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")

    class SafeParser(argparse.ArgumentParser):
        def error(self, message):
            self.exit(2, "인수가 올바르지 않습니다. doctor --help를 확인하세요.\n")

    parser = SafeParser(prog="yonsei-portal-mcp doctor", description="로그인 없이 로컬 설치·MCP stdio 연결을 확인합니다.", allow_abbrev=False)
    parser._optionals.title = "옵션"
    parser.add_argument("--json", action="store_true", help="기계 판독용 JSON 출력")
    parser.add_argument("--env-file", type=Path, help="명시한 .env만 내용 검사(값 출력·환경 변경·변수 치환 없음)")
    parser.add_argument("--browser", action="store_true", help="격리 Chromium에서 about:blank 시작 확인(로그인 없음)")
    parser.add_argument("--timeout", type=float, default=10.0, help="각 연결 검사 제한 시간(초, 기본 10, 최대 120)")
    args = parser.parse_args(argv)
    if not math.isfinite(args.timeout) or not 0 < args.timeout <= 120:
        parser.error("invalid_timeout")
    installation = inspect_installation()
    code = 0
    try:
        config = inspect_configuration(args.env_file)
    except (OSError, ValueError, ImportError):
        config = {"status": "error", "code": "env_file_unavailable"}
        code = 2
    chromium = probe_browser(launch=args.browser, timeout=args.timeout)
    stdio = probe_stdio(timeout=args.timeout)
    local_ready = installation["status"] == "ok" and stdio["status"] == "ok"
    if not code and (not local_ready or (args.browser and not chromium["launched"])):
        code = 1
    report = {
        "schema_version": 1,
        "exit_code": code,
        "public_features": "local_ready_not_live_verified" if local_ready else "unavailable",
        "checks": {"installation": installation, "configuration": config,
                   "chromium": chromium, "stdio": stdio},
        "scope": "local_only_no_login_no_cookies_no_portal_no_llm",
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    else:
        _print_human(report)
    return code

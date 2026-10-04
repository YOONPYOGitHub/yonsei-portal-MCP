"""Offline security regressions: synthetic credentials and temporary state only."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from contextlib import asynccontextmanager
import json
import os
import stat
from types import SimpleNamespace

import pytest

from yonsei_portal_mcp import session as sessions
from yonsei_portal_mcp.config import Settings
from yonsei_portal_mcp.errors import AuthFailedError, ScrapeFailedError, SessionExpiredError, UpstreamTimeoutError


def settings(tmp_path):
    return Settings("synthetic-student-id", "synthetic-password", False, tmp_path / "state.json")


def test_missing_cookie_does_not_require_posix_nonblock_flag(tmp_path, monkeypatch):
    from yonsei_portal_mcp.security import read_session_state
    monkeypatch.delattr(os, "O_NONBLOCK", raising=False)
    assert read_session_state(tmp_path / "missing.json") is None


def test_settings_repr_excludes_both_credentials(tmp_path):
    value = settings(tmp_path)
    assert value.yonsei_id not in repr(value)
    assert value.yonsei_password not in repr(value)


@pytest.mark.asyncio
@pytest.mark.parametrize("session_type,host", [
    (sessions.LearnUsSession, "ys.learnus.org"),
    (sessions.LibrarySession, "library.yonsei.ac.kr"),
    (sessions.ErpSession, "underwood1.yonsei.ac.kr"),
])
@pytest.mark.parametrize("template", [
    "https://{host}.attacker.invalid/", "https://attacker.invalid/?next={host}",
    "http://{host}/", "https://{host}:444/", "https://{host}@attacker.invalid/",
])
async def test_authentication_rejects_non_school_origins(tmp_path, session_type, host, template):
    page = MagicMock()
    page.url = template.format(host=host)
    page.locator.return_value.count = AsyncMock(return_value=1)
    if session_type is sessions.ErpSession:
        page.locator.return_value.count = AsyncMock(return_value=0)
    page.get_by_text.return_value.count = AsyncMock(return_value=1)
    assert not await session_type(settings(tmp_path))._is_authenticated(page)


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [ValueError("invalid input"), ScrapeFailedError("parse error"), KeyError("missing field"), TypeError("parse type"), RuntimeError("unknown failure")])
async def test_non_auth_errors_never_invalidate_or_retry(tmp_path, monkeypatch, error):
    session = sessions.LearnUsSession(settings(tmp_path))
    @asynccontextmanager
    async def page():
        yield object()
    monkeypatch.setattr(session, "_page_unlocked", page)
    invalidate = AsyncMock()
    monkeypatch.setattr(session, "_invalidate_session", invalidate)
    action = AsyncMock(side_effect=error)
    expected = ValueError if isinstance(error, ValueError) else ScrapeFailedError
    with pytest.raises(expected):
        await session.run(action)
    invalidate.assert_not_awaited()
    action.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [SessionExpiredError("expired"), UpstreamTimeoutError("timeout"), sessions.PlaywrightTimeoutError("timeout"), ConnectionError("disconnected")])
async def test_transient_failures_have_exactly_one_retry(tmp_path, monkeypatch, error):
    session = sessions.LearnUsSession(settings(tmp_path))
    @asynccontextmanager
    async def page():
        yield object()
    monkeypatch.setattr(session, "_page_unlocked", page)
    invalidate = AsyncMock()
    monkeypatch.setattr(session, "_invalidate_session", invalidate)
    action = AsyncMock(side_effect=error)
    with pytest.raises((SessionExpiredError, UpstreamTimeoutError)):
        await session.run(action)
    invalidate.assert_awaited_once()
    assert action.await_count == 2


def test_account_directories_private_without_chmod_of_storage_parent(tmp_path):
    tmp_path.chmod(0o755)
    session = sessions.LearnUsSession(settings(tmp_path))
    assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o755
    assert stat.S_IMODE(session._storage_state_path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(session._storage_state_path.parent.parent.stat().st_mode) == 0o700


@pytest.mark.asyncio
async def test_cookie_save_is_atomic_and_private(tmp_path, monkeypatch):
    session = sessions.LearnUsSession(settings(tmp_path))
    path = session._storage_state_path
    old = {"cookies": [], "origins": []}
    new = {"cookies": [], "origins": [{"origin": "https://ys.learnus.org", "localStorage": []}]}
    path.write_text(json.dumps(old))
    path.chmod(0o600)
    async def storage_state(**kwargs):
        if "path" in kwargs:  # Simulate the old Playwright direct-write API.
            from pathlib import Path
            target = Path(kwargs["path"])
            target.write_text(json.dumps(new))
        return new
    session._context = SimpleNamespace(storage_state=storage_state)
    replaced = []
    original = os.replace
    def replace(source, destination):
        assert path.read_text() == json.dumps(old)
        assert stat.S_IMODE(os.stat(source).st_mode) == 0o600
        replaced.append(destination)
        return original(source, destination)
    monkeypatch.setattr(os, "replace", replace)
    await session._save_storage_state()
    assert replaced == [path]
    assert json.loads(path.read_text()) == new
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.asyncio
async def test_cookie_save_refuses_symlink_target(tmp_path):
    session = sessions.LearnUsSession(settings(tmp_path))
    victim = tmp_path / "unrelated.json"
    victim.write_text("do not touch")
    session._storage_state_path.symlink_to(victim)
    async def storage_state(**kwargs):
        if "path" in kwargs:
            from pathlib import Path
            Path(kwargs["path"]).write_text("overwritten")
        return {"cookies": [], "origins": []}
    session._context = SimpleNamespace(storage_state=storage_state)
    with pytest.raises(ValueError, match="[Ss]ession"):
        await session._save_storage_state()
    assert victim.read_text() == "do not touch"


def test_cookie_directory_symlink_is_rejected(tmp_path):
    import hashlib
    account = hashlib.sha256(settings(tmp_path).yonsei_id.encode()).hexdigest()
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / account).symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="[Ss]ession"):
        sessions.LearnUsSession(settings(tmp_path))
    assert not (outside / "learnus").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("contents", ["not JSON", '{"cookies": "bad", "origins": []}', '{"cookies": [{}], "origins": []}'])
async def test_start_discards_malformed_state_with_warning(tmp_path, monkeypatch, contents):
    session = sessions.LearnUsSession(settings(tmp_path))
    session._storage_state_path.write_text(contents)
    session._storage_state_path.chmod(0o600)
    browser = SimpleNamespace(new_context=AsyncMock(return_value=object()))
    driver = SimpleNamespace(chromium=SimpleNamespace(launch=AsyncMock(return_value=browser)))
    monkeypatch.setattr(sessions, "async_playwright", lambda: SimpleNamespace(start=AsyncMock(return_value=driver)))
    with pytest.warns(UserWarning, match="[Ss]ession"):
        await session.start()
    assert "storage_state" not in browser.new_context.call_args.kwargs


@pytest.mark.asyncio
async def test_start_refuses_public_cookie_file(tmp_path, monkeypatch):
    session = sessions.LearnUsSession(settings(tmp_path))
    session._storage_state_path.write_text('{"cookies": [], "origins": []}')
    session._storage_state_path.chmod(0o644)
    browser = SimpleNamespace(new_context=AsyncMock(return_value=object()), close=AsyncMock())
    driver = SimpleNamespace(chromium=SimpleNamespace(launch=AsyncMock(return_value=browser)), stop=AsyncMock())
    monkeypatch.setattr(sessions, "async_playwright", lambda: SimpleNamespace(start=AsyncMock(return_value=driver)))
    with pytest.raises(ValueError, match="[Ss]ession"):
        await session.start()
    browser.new_context.assert_not_awaited()


def login_page(origin, action):
    """Browser I/O double; security decisions still execute in production code."""
    page = MagicMock()
    page.url = origin + "/login"
    for name in ("goto", "wait_for_timeout", "wait_for_selector", "wait_for_url", "check", "click", "fill"):
        setattr(page, name, AsyncMock())
    page.locator.return_value.first.count = AsyncMock(return_value=1)
    page.locator.return_value.or_.return_value.first.wait_for = AsyncMock()
    page.get_by_text.return_value.first.wait_for = AsyncMock()
    page.inner_text = AsyncMock(return_value="")
    page.evaluate = AsyncMock(return_value={"url": page.url, "action": action, "overrides": [], "sameForm": True})
    return page


@pytest.mark.asyncio
@pytest.mark.parametrize("session_type,origin", [
    (sessions.LearnUsSession, "https://infra.yonsei.ac.kr"),
    (sessions.LibrarySession, "https://library.yonsei.ac.kr"),
    (sessions.ErpSession, "https://infra.yonsei.ac.kr"),
])
@pytest.mark.parametrize("unsafe", ["page", "action", "override", "different-form"])
async def test_login_rejects_external_destinations_before_any_fill(tmp_path, monkeypatch, session_type, origin, unsafe):
    session = session_type(settings(tmp_path))
    page = login_page(origin, origin + "/authenticate")
    snapshot = page.evaluate.return_value
    if unsafe == "page":
        page.url = snapshot["url"] = origin + ".attacker.invalid/login"
    elif unsafe == "action":
        snapshot["action"] = "https://attacker.invalid/collect"
    elif unsafe == "override":
        snapshot["overrides"] = ["https://attacker.invalid/collect"]
    else:
        snapshot["sameForm"] = False
    monkeypatch.setattr(session, "_is_authenticated", AsyncMock(return_value=False))
    with pytest.raises(AuthFailedError):
        await session._login(page)
    page.fill.assert_not_awaited()
    page.click.assert_not_awaited()
    assert not any(call.args[0] == "fSubmitSSOLoginForm()" for call in page.evaluate.call_args_list)


@pytest.mark.asyncio
@pytest.mark.parametrize("session_type,origin", [
    (sessions.LearnUsSession, "https://infra.yonsei.ac.kr"),
    (sessions.LibrarySession, "https://library.yonsei.ac.kr"),
    (sessions.ErpSession, "https://infra.yonsei.ac.kr"),
])
async def test_normal_login_checks_each_fill_and_submit(tmp_path, monkeypatch, session_type, origin):
    session = session_type(settings(tmp_path))
    page = login_page(origin, origin + "/authenticate")
    checks = [False, False, True, True] if session_type is sessions.ErpSession else [False, True, True]
    monkeypatch.setattr(session, "_is_authenticated", AsyncMock(side_effect=checks))
    save = AsyncMock()
    monkeypatch.setattr(session, "_save_storage_state", save)
    await session._login(page)
    assert page.fill.await_count == 2
    save.assert_awaited_once()
    inspections = [call for call in page.evaluate.call_args_list if len(call.args) == 2]
    assert len(inspections) == 3
    for call in page.wait_for_url.call_args_list:
        predicate = call.args[0]
        assert callable(predicate), "Redirect waits must compare exact origins, not globs"
        target = "https://ys.learnus.org/" if session_type is sessions.LearnUsSession else "https://underwood1.yonsei.ac.kr/"
        assert predicate(target)
        assert not predicate(target.replace(".org/", ".org.attacker.invalid/").replace(".kr/", ".kr.attacker.invalid/"))


@pytest.mark.asyncio
@pytest.mark.parametrize("session_type,origin", [
    (sessions.LearnUsSession, "https://infra.yonsei.ac.kr"),
    (sessions.LibrarySession, "https://library.yonsei.ac.kr"),
    (sessions.ErpSession, "https://infra.yonsei.ac.kr"),
])
@pytest.mark.parametrize("change_after", [1, 2])
async def test_destination_rechecked_after_each_fill(tmp_path, monkeypatch, session_type, origin, change_after):
    session = session_type(settings(tmp_path))
    page = login_page(origin, origin + "/authenticate")
    monkeypatch.setattr(session, "_is_authenticated", AsyncMock(return_value=False))
    async def fill(*args):
        if page.fill.await_count == change_after:
            page.evaluate.return_value["action"] = "https://attacker.invalid/collect"
    page.fill.side_effect = fill
    with pytest.raises(AuthFailedError):
        await session._login(page)
    assert page.fill.await_count == change_after
    page.click.assert_not_awaited()
    assert not any(call.args[0] == "fSubmitSSOLoginForm()" for call in page.evaluate.call_args_list)


@pytest.mark.asyncio
@pytest.mark.parametrize("markup,allowed", [
    ('<form action="/authenticate"><input id="loginId"><input id="loginPasswd"></form>', True),
    ('<base href="https://attacker.invalid/"><form action="authenticate"><input id="loginId"><input id="loginPasswd"></form>', False),
    ('<form action="/authenticate"><input id="loginId"><input id="loginPasswd"><button formaction="https://attacker.invalid/">Go</button></form>', False),
    ('<form id="a" action="/authenticate"><input id="loginId"><input id="loginPasswd" form="b"></form><form id="b" action="https://attacker.invalid/"></form>', False),
])
async def test_real_dom_form_validation_without_network(markup, allowed):
    from playwright.async_api import async_playwright
    from yonsei_portal_mcp.security import require_credential_form
    async with async_playwright() as driver:
        browser = await driver.chromium.launch()
        try:
            context = await browser.new_context(service_workers="block")
            await context.route("**/*", lambda route: route.abort())
            await context.route("https://infra.yonsei.ac.kr/login", lambda route: route.fulfill(body=markup, content_type="text/html"))
            page = await context.new_page()
            await page.goto("https://infra.yonsei.ac.kr/login")
            if allowed:
                await require_credential_form(page, "https://infra.yonsei.ac.kr", "#loginId", "#loginPasswd")
                await page.fill("#loginId", "synthetic")
                assert await page.input_value("#loginId") == "synthetic"
            else:
                with pytest.raises(AuthFailedError):
                    await require_credential_form(page, "https://infra.yonsei.ac.kr", "#loginId", "#loginPasswd")
                assert await page.input_value("#loginId") == ""
                assert await page.input_value("#loginPasswd") == ""
        finally:
            await browser.close()


@pytest.mark.parametrize("url", [
    "https://ys.learnus.org:0/", " https://ys.learnus.org/", "https://ys.learnus.org/\n",
    "https://ys.learnus.org:bad/", "https://ys.learnus.org./", "https://user@ys.learnus.org/",
    123,
])
def test_origin_validator_rejects_ambiguous_urls(url):
    from yonsei_portal_mcp.security import is_https_origin
    assert not is_https_origin(url, "https://ys.learnus.org/")


def test_load_settings_creates_only_private_new_parent(tmp_path, monkeypatch):
    from yonsei_portal_mcp.config import load_settings
    parent = tmp_path / "new-storage"
    monkeypatch.setenv("YONSEI_STORAGE_STATE", str(parent / "state.json"))
    monkeypatch.setenv("YONSEI_ID", "synthetic")
    monkeypatch.setenv("YONSEI_PASSWORD", "synthetic")
    load_settings()
    assert stat.S_IMODE(parent.stat().st_mode) == 0o700
    parent.chmod(0o755)
    load_settings()
    assert stat.S_IMODE(parent.stat().st_mode) == 0o755


@pytest.mark.parametrize("same_site", [[], {}, "unrecognized"])
def test_malformed_cookie_fields_do_not_crash_state_validation(tmp_path, same_site):
    from yonsei_portal_mcp.security import read_session_state
    path = tmp_path / "state.json"
    cookie = dict(name="a", value="b", domain="ys.learnus.org", path="/", expires=-1, httpOnly=True, secure=True, sameSite=same_site)
    path.write_text(json.dumps({"cookies": [cookie], "origins": []}))
    path.chmod(0o600)
    with pytest.warns(UserWarning, match="session"):
        assert read_session_state(path) is None


@pytest.mark.asyncio
async def test_private_state_is_loaded_as_validated_data_not_path(tmp_path, monkeypatch):
    session = sessions.LearnUsSession(settings(tmp_path))
    data = {"cookies": [], "origins": []}
    session._storage_state_path.write_text(json.dumps(data))
    session._storage_state_path.chmod(0o600)
    browser = SimpleNamespace(new_context=AsyncMock(return_value=object()))
    driver = SimpleNamespace(chromium=SimpleNamespace(launch=AsyncMock(return_value=browser)))
    monkeypatch.setattr(sessions, "async_playwright", lambda: SimpleNamespace(start=AsyncMock(return_value=driver)))
    await session.start()
    browser.new_context.assert_awaited_once_with(storage_state=data)


def test_failed_atomic_replace_keeps_old_file_and_cleans_temp(tmp_path, monkeypatch):
    from yonsei_portal_mcp.security import write_session_state
    path = tmp_path / "state.json"
    path.write_text("old")
    path.chmod(0o600)
    def fail(*args):
        raise OSError("synthetic failure")
    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError):
        write_session_state(path, {"cookies": [], "origins": []})
    assert path.read_text() == "old"
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.asyncio
@pytest.mark.parametrize("message,retries", [
    ("Page.goto: net::ERR_CONNECTION_RESET at https://synthetic.invalid", 2),
    ("Page.goto: net::ERR_TIMED_OUT", 2),
    ("Locator.text_content: strict mode violation", 1),
    ("Page.goto: net::ERR_CERT_AUTHORITY_INVALID", 1),
])
async def test_playwright_network_errors_are_narrowly_classified(tmp_path, monkeypatch, message, retries):
    from playwright.async_api import Error
    session = sessions.LearnUsSession(settings(tmp_path))
    @asynccontextmanager
    async def page():
        yield object()
    monkeypatch.setattr(session, "_page_unlocked", page)
    invalidate = AsyncMock()
    monkeypatch.setattr(session, "_invalidate_session", invalidate)
    action = AsyncMock(side_effect=Error(message))
    expected = SessionExpiredError if retries == 2 else ScrapeFailedError
    with pytest.raises(expected) as caught:
        await session.run(action)
    assert message not in str(caught.value)
    assert action.await_count == retries
    assert invalidate.await_count == retries - 1


@pytest.mark.asyncio
async def test_invalidation_rejects_replaced_symlink_directory_but_closes_resources(tmp_path):
    session = sessions.LearnUsSession(settings(tmp_path))
    path = session._storage_state_path
    outside = tmp_path / "outside"
    outside.mkdir()
    victim = outside / path.name
    victim.write_text("do not delete")
    path.parent.rmdir()
    path.parent.symlink_to(outside, target_is_directory=True)
    close = AsyncMock()
    session._context = SimpleNamespace(close=close)
    with pytest.raises(ValueError, match="Session"):
        await session._invalidate_session()
    assert victim.read_text() == "do not delete"
    close.assert_awaited_once()


@pytest.mark.asyncio
async def test_start_refuses_symlink_file_without_opening_browser(tmp_path, monkeypatch):
    session = sessions.LearnUsSession(settings(tmp_path))
    target = tmp_path / "unrelated.json"
    target.write_text('{"cookies": [], "origins": []}')
    target.chmod(0o600)
    session._storage_state_path.symlink_to(target)
    start = MagicMock()
    monkeypatch.setattr(sessions, "async_playwright", start)
    with pytest.raises(ValueError, match="Session"):
        await session.start()
    start.assert_not_called()
    assert target.read_text() == '{"cookies": [], "origins": []}'


def test_existing_account_directories_are_tightened_not_storage_parent(tmp_path):
    value = settings(tmp_path)
    session = sessions.LearnUsSession(value)
    for path in (tmp_path, session._storage_state_path.parent, session._storage_state_path.parent.parent):
        path.chmod(0o755)
    sessions.LearnUsSession(value)
    assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o755
    assert stat.S_IMODE(session._storage_state_path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(session._storage_state_path.parent.parent.stat().st_mode) == 0o700


@pytest.mark.asyncio
@pytest.mark.parametrize("session_type,url", [
    (sessions.LearnUsSession, "https://ys.learnus.org:443/my/"),
    (sessions.LibrarySession, "https://library.yonsei.ac.kr/my/"),
    (sessions.ErpSession, "https://underwood1.yonsei.ac.kr/main.do"),
])
async def test_authenticated_school_pages_still_accepted(tmp_path, session_type, url):
    page = MagicMock()
    page.url = url
    page.locator.return_value.count = AsyncMock(return_value=0 if session_type is sessions.ErpSession else 1)
    page.get_by_text.return_value.count = AsyncMock(return_value=1)
    assert await session_type(settings(tmp_path))._is_authenticated(page)


@pytest.mark.asyncio
async def test_expired_session_recovers_with_one_retry(tmp_path, monkeypatch):
    session = sessions.LearnUsSession(settings(tmp_path))
    @asynccontextmanager
    async def page():
        yield object()
    monkeypatch.setattr(session, "_page_unlocked", page)
    invalidate = AsyncMock()
    monkeypatch.setattr(session, "_invalidate_session", invalidate)
    action = AsyncMock(side_effect=[SessionExpiredError("expired"), "success"])
    assert await session.run(action) == "success"
    invalidate.assert_awaited_once()
    assert action.await_count == 2

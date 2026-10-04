from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from yonsei_portal_mcp import session as sessions
from yonsei_portal_mcp.config import Settings
from yonsei_portal_mcp.errors import AuthRequiredError, SessionExpiredError


@pytest.mark.parametrize("session_type", [sessions.LearnUsSession, sessions.LibrarySession, sessions.ErpSession])
def test_cookie_paths_are_bound_to_account(tmp_path, session_type):
    first = Settings("account-a", "password-a", False, tmp_path / "state.json")
    second = Settings("account-b", "password-b", False, tmp_path / "state.json")
    first_session, second_session = session_type(first), session_type(second)
    assert first_session._storage_state_path != second_session._storage_state_path
    assert first_session._storage_state_path != first.storage_state_path
    assert "account-a" not in str(first_session._storage_state_path)
    assert session_type(first)._storage_state_path == first_session._storage_state_path


@pytest.mark.parametrize("filename", ["state.json", "library.json", "erp.json"])
def test_cookie_paths_do_not_collide_between_systems(tmp_path, filename):
    settings = Settings("account-a", "password-a", False, tmp_path / filename)
    paths = {
        session_type(settings)._storage_state_path
        for session_type in (sessions.LearnUsSession, sessions.LibrarySession, sessions.ErpSession)
    }
    assert len(paths) == 3


@pytest.mark.parametrize("changed", ["yonsei_id", "yonsei_password", "storage_state_path"])
def test_changed_credentials_rejected_before_cache_or_session_reuse(monkeypatch, tmp_path, changed):
    from dataclasses import replace
    from yonsei_portal_mcp import server

    original = Settings("account-a", "password-a", False, tmp_path / "state.json")
    value = tmp_path / "other.json" if changed == "storage_state_path" else "changed"
    updated = replace(original, **{changed: value})
    monkeypatch.setattr(sessions, "_session", sessions.LearnUsSession(original))
    monkeypatch.setattr(sessions, "_library_session", None)
    monkeypatch.setattr(sessions, "_erp_session", None)
    monkeypatch.setattr(sessions, "load_settings", lambda: updated)
    monkeypatch.setattr(server, "load_settings", lambda: updated)
    with pytest.raises(AuthRequiredError):
        server._account()
    with pytest.raises(AuthRequiredError):
        sessions.get_session()


@pytest.fixture
def browser_session(tmp_path):
    settings = Settings("test-id", "test-password", False, tmp_path / "state.json")
    return sessions.BrowserSession(settings, settings.storage_state_path)


@pytest.mark.asyncio
async def test_erp_waits_for_late_authenticated_shell_without_resubmitting_credentials(tmp_path, monkeypatch):
    settings = Settings("test-id", "test-password", False, tmp_path / "state.json")
    session = sessions.ErpSession(settings)
    monkeypatch.setattr(session, "_is_authenticated", AsyncMock(side_effect=[False, True]))
    page = MagicMock()
    page.goto = AsyncMock()
    page.wait_for_timeout = AsyncMock()
    page.wait_for_selector = AsyncMock(side_effect=sessions.PlaywrightTimeoutError("login form absent"))
    page.locator.return_value.or_.return_value.first.wait_for = AsyncMock()
    page.fill = AsyncMock()
    await session._login(page)
    page.locator.return_value.or_.return_value.first.wait_for.assert_awaited_once()
    page.fill.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalidation_closes_all_resources(browser_session):
    context = SimpleNamespace(close=AsyncMock())
    browser = SimpleNamespace(close=AsyncMock())
    driver = SimpleNamespace(stop=AsyncMock())
    browser_session._context = context
    browser_session._browser = browser
    browser_session._playwright = driver
    await browser_session._invalidate_session()
    context.close.assert_awaited_once()
    browser.close.assert_awaited_once()
    driver.stop.assert_awaited_once()
    assert browser_session._browser is None
    assert browser_session._playwright is None


@pytest.mark.asyncio
async def test_server_lifespan_closes_existing_sessions(monkeypatch):
    from yonsei_portal_mcp import server

    opened = [SimpleNamespace(close=AsyncMock()) for _ in range(3)]
    for name, instance in zip(("_session", "_library_session", "_erp_session"), opened):
        monkeypatch.setattr(sessions, name, instance)
    async with server.server_lifespan(server.mcp):
        for instance in opened:
            instance.close.assert_not_awaited()
    for instance in opened:
        instance.close.assert_awaited_once()
    assert sessions._session is None
    assert sessions._library_session is None
    assert sessions._erp_session is None


@pytest.mark.asyncio
async def test_close_releases_remaining_resources_when_context_fails(browser_session):
    browser = SimpleNamespace(close=AsyncMock())
    driver = SimpleNamespace(stop=AsyncMock())
    browser_session._context = SimpleNamespace(close=AsyncMock(side_effect=RuntimeError("closed")))
    browser_session._browser = browser
    browser_session._playwright = driver
    await browser_session.close()
    await browser_session.close()
    browser.close.assert_awaited_once()
    driver.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_launch_stops_driver(browser_session, monkeypatch):
    driver = SimpleNamespace(chromium=SimpleNamespace(launch=AsyncMock(side_effect=RuntimeError("launch failed"))), stop=AsyncMock())
    monkeypatch.setattr(sessions, "async_playwright", lambda: SimpleNamespace(start=AsyncMock(return_value=driver)))
    with pytest.raises(RuntimeError):
        await browser_session.start()
    driver.stop.assert_awaited_once()
    assert browser_session._playwright is None


@pytest.mark.asyncio
async def test_retry_holds_session_lock_and_sanitizes_errors(browser_session, monkeypatch):
    page = SimpleNamespace(close=AsyncMock())
    context = SimpleNamespace(new_page=AsyncMock(return_value=page))

    async def start():
        browser_session._context = context

    async def invalidate():
        assert browser_session._lock.locked(), "Retry must retain the page lock"

    monkeypatch.setattr(browser_session, "start", start)
    monkeypatch.setattr(browser_session, "ensure_authenticated", AsyncMock())
    monkeypatch.setattr(browser_session, "_invalidate_session", invalidate)
    action = AsyncMock(side_effect=sessions.PlaywrightTimeoutError("private credentials in upstream error"))
    with pytest.raises(SessionExpiredError) as caught:
        await browser_session.run(action)
    assert "private credentials" not in str(caught.value)
    assert caught.value.__suppress_context__
    assert action.await_count == 2


@pytest.mark.asyncio
async def test_close_waits_for_active_request(browser_session, monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()
    context = SimpleNamespace(new_page=AsyncMock(return_value=SimpleNamespace(close=AsyncMock())), close=AsyncMock())
    browser_session._context = context
    monkeypatch.setattr(browser_session, "ensure_authenticated", AsyncMock())
    async def start():
        browser_session._context = context
    monkeypatch.setattr(browser_session, "start", start)

    async def action(page):
        entered.set()
        await release.wait()
        context.close.assert_not_awaited()

    running = asyncio.create_task(browser_session.run(action))
    await entered.wait()
    closing = asyncio.create_task(browser_session.close())
    release.set()
    await asyncio.gather(running, closing)
    context.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancellation_during_cleanup_still_closes_browser_and_driver(browser_session):
    entered, release = asyncio.Event(), asyncio.Event()

    async def close_context():
        entered.set()
        await release.wait()

    browser = SimpleNamespace(close=AsyncMock())
    driver = SimpleNamespace(stop=AsyncMock())
    browser_session._context = SimpleNamespace(close=close_context)
    browser_session._browser = browser
    browser_session._playwright = driver
    closing = asyncio.create_task(browser_session.close())
    await entered.wait()
    closing.cancel()
    try:
        checkpoint = asyncio.get_running_loop().create_future()
        asyncio.get_running_loop().call_soon(checkpoint.set_result, None)
        await checkpoint
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await closing
    browser.close.assert_awaited_once()
    driver.stop.assert_awaited_once()
    assert browser_session._browser is None
    assert browser_session._playwright is None
    assert not browser_session._lock.locked()
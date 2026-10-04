"""LearnUs (ys.learnus.org) authenticated browser session.

A single shared Playwright Chromium context is kept alive for the lifetime of
the MCP server process. Cookies are persisted to ``storage_state.json`` so that
restarts can reuse an existing login without re-entering credentials.

Login flow (validated against the live site):

1. Open ``https://ys.learnus.org/``.
2. If already authenticated (a logout link is present) we are done.
3. Otherwise click the "연세포털 로그인" button (``a.btn-sso``). Triggering it via
   a real click sets the correct referer; navigating to the SSO endpoint
   directly returns ``403 Incorrect access!!``.
4. On the Yonsei infra SSO form fill ``#loginId`` / ``#loginPasswd`` and submit
   through the page's own ``fSubmitSSOLoginForm()`` function.
5. Wait to be redirected back to ``ys.learnus.org``.

The password is never logged or returned to callers.
"""
from __future__ import annotations

import asyncio
import hashlib
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Awaitable, Callable, Optional, TypeVar

import anyio
from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from .config import (
    ERP_URL,
    LEARNUS_URL,
    LIBRARY_LOGIN_URL,
    LIBRARY_URL,
    Settings,
    load_settings,
)
from .errors import (
    AuthFailedError,
    AuthRequiredError,
    MFARequiredError,
    PortalError,
    ScrapeFailedError,
    SessionExpiredError,
)

_LOGOUT_SELECTOR = 'a[href*="/login/logout.php"]'
_SSO_TRIGGER = "a.btn-sso"
_LIBRARY_LOGOUT_SELECTOR = 'a[href*="spLogout"]'
# Heuristic: how long to wait for a human to finish 2FA / CAPTCHA in headed mode.
_INTERACTIVE_LOGIN_TIMEOUT_MS = 180_000

T = TypeVar("T")


def _account_storage(settings: Settings, system: str, filename: str):
    account = hashlib.sha256(settings.yonsei_id.encode("utf-8")).hexdigest()
    return settings.storage_state_path.parent / account / system / filename


class BrowserSession:
    """Shared Playwright lifecycle for one authenticated Yonsei web property.

    Subclasses own a single long-lived Chromium context whose cookies are
    persisted to ``storage_state_path``. They must implement
    :meth:`_is_authenticated` and :meth:`_login` for their specific site; all
    lifecycle, locking and one-shot retry behaviour lives here.
    """

    def __init__(self, settings: Settings, storage_state_path) -> None:
        self.settings = settings
        self._storage_state_path = storage_state_path
        self._storage_state_path.parent.mkdir(parents=True, exist_ok=True)
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._lock = asyncio.Lock()

    # -- lifecycle -----------------------------------------------------------
    async def start(self) -> None:
        if self._context is not None:
            return
        try:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=not self.settings.headed
            )
            context_kwargs: dict = {}
            if self._storage_state_path.exists():
                context_kwargs["storage_state"] = str(self._storage_state_path)
            self._context = await self._browser.new_context(**context_kwargs)
        except BaseException:
            await self._close_unlocked()
            raise

    async def close(self) -> None:
        async with self._lock:
            await self._close_unlocked()

    async def _close_unlocked(self) -> None:
        context, browser, driver = self._context, self._browser, self._playwright

        async def release() -> None:
            for resource, method in ((context, "close"), (browser, "close"), (driver, "stop")):
                if resource is not None:
                    try:
                        await getattr(resource, method)()
                    except Exception:
                        pass
            self._context = self._browser = self._playwright = None

        cancelled = None
        with anyio.CancelScope(shield=True):
            cleanup = asyncio.create_task(release())
            while not cleanup.done():
                try:
                    await asyncio.shield(cleanup)
                except asyncio.CancelledError as exc:
                    cancelled = exc
            cleanup.result()
        if cancelled is not None:
            raise cancelled

    async def _save_storage_state(self) -> None:
        if self._context is None:
            return
        await self._context.storage_state(path=str(self._storage_state_path))

    # -- authentication (site-specific hooks) --------------------------------
    async def _is_authenticated(self, page: Page) -> bool:
        raise NotImplementedError

    async def _login(self, page: Page) -> None:
        raise NotImplementedError

    async def ensure_authenticated(self, page: Page) -> None:
        if await self._is_authenticated(page):
            return
        await self._login(page)

    async def _invalidate_session(self) -> None:
        """Drop cached cookies so the next access performs a fresh login."""
        try:
            if self._storage_state_path.exists():
                self._storage_state_path.unlink()
        except Exception:
            pass
        await self._close_unlocked()

    # -- page access ---------------------------------------------------------
    @asynccontextmanager
    async def page(self) -> AsyncIterator[Page]:
        """Yield an authenticated page, serialising access with a lock."""
        async with self._lock:
            async with self._page_unlocked() as page:
                yield page

    @asynccontextmanager
    async def _page_unlocked(self) -> AsyncIterator[Page]:
        await self.start()
        assert self._context is not None
        page = await self._context.new_page()
        try:
            await self.ensure_authenticated(page)
            yield page
        finally:
            try:
                await page.close()
            except Exception:
                pass

    async def run(self, action: Callable[[Page], Awaitable[T]]) -> T:
        """Run ``action`` on an authenticated page, re-logging in once on failure.

        If the first attempt fails for a non-auth reason (timeout / stale cookies), we drop the
        cached session and retry exactly once with a fresh login.
        """
        async with self._lock:
            for attempt in range(2):
                try:
                    async with self._page_unlocked() as page:
                        return await action(page)
                except (AuthRequiredError, AuthFailedError, MFARequiredError):
                    raise
                except PortalError:
                    if attempt == 0:
                        await self._invalidate_session()
                        continue
                    raise
                except PlaywrightTimeoutError:
                    if attempt == 0:
                        await self._invalidate_session()
                        continue
                    raise SessionExpiredError(
                        "세션이 만료되었거나 응답이 지연되어 재시도에도 실패했습니다."
                    ) from None
                except Exception:
                    if attempt == 0:
                        await self._invalidate_session()
                        continue
                    raise ScrapeFailedError("조회 중 오류가 발생했습니다. 세션 또는 사이트 응답을 확인하세요.") from None
        raise ScrapeFailedError("알 수 없는 이유로 요청을 완료하지 못했습니다.")


class LearnUsSession(BrowserSession):
    """Owns a Playwright browser context authenticated against LearnUs."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        s = settings or load_settings()
        super().__init__(s, _account_storage(s, "learnus", s.storage_state_path.name))

    # -- authentication ------------------------------------------------------
    async def _is_authenticated(self, page: Page) -> bool:
        if "ys.learnus.org" not in page.url:
            return False
        try:
            return await page.locator(_LOGOUT_SELECTOR).count() > 0
        except Exception:
            return False

    async def _login(self, page: Page) -> None:
        if not self.settings.has_credentials:
            raise AuthRequiredError(
                "연세 포털 자격 증명이 없습니다. .env 파일에 YONSEI_ID/ID 와 "
                "YONSEI_PASSWORD/password 를 설정하세요."
            )

        nav_timeout = self.settings.nav_timeout_ms
        await page.goto(LEARNUS_URL, wait_until="domcontentloaded")
        if await self._is_authenticated(page):
            return

        # Kick off SSO by clicking the portal-login button (sets proper referer).
        trigger = page.locator(_SSO_TRIGGER).first
        if await trigger.count() == 0:
            raise ScrapeFailedError(
                "LearnUs 로그인 페이지에서 SSO 버튼(a.btn-sso)을 찾지 못했습니다."
            )
        # A real click bounces through spLogin2.php before landing on the infra
        # SSO form. Don't wrap this in expect_navigation: the multi-hop redirect
        # chain races with a single navigation event. Just wait for the form.
        await page.evaluate("document.querySelector('a.btn-sso').click()")

        # Fill the Yonsei infra SSO form and submit via its own JS function.
        try:
            await page.wait_for_selector("#loginId", timeout=nav_timeout)
        except PlaywrightTimeoutError as exc:
            raise ScrapeFailedError(
                "연세 통합 로그인 폼(#loginId)을 제시간 내에 불러오지 못했습니다."
            ) from exc
        await page.fill("#loginId", self.settings.yonsei_id)
        await page.fill("#loginPasswd", self.settings.yonsei_password)
        await page.evaluate("fSubmitSSOLoginForm()")

        # Submitting POSTs to the infra auth service which then redirects back to
        # ys.learnus.org on success. The first landing page (spLoginData.php) is
        # an intermediate hop that JS-redirects to the dashboard, so wait for the
        # round-trip and then for the logout link to actually appear.
        try:
            await page.wait_for_url("**ys.learnus.org/**", timeout=nav_timeout)
            await page.wait_for_selector(_LOGOUT_SELECTOR, timeout=15_000)
        except PlaywrightTimeoutError:
            pass

        # Allow extra time for a human to complete 2FA / CAPTCHA when headed.
        if not await self._is_authenticated(page) and self.settings.headed:
            try:
                await page.wait_for_url(
                    "**ys.learnus.org/**",
                    timeout=_INTERACTIVE_LOGIN_TIMEOUT_MS,
                )
            except PlaywrightTimeoutError:
                pass

        if not await self._is_authenticated(page):
            await self._raise_login_failure(page)

        await self._save_storage_state()

    async def _raise_login_failure(self, page: Page) -> None:
        """Classify why the login did not complete."""
        body = ""
        try:
            body = (await page.inner_text("body"))[:4000]
        except Exception:
            body = ""
        if any(
            kw in body
            for kw in ("일치하지 않", "비밀번호를 확인", "등록되지 않은 아이디")
        ):
            raise AuthFailedError(
                "아이디 또는 비밀번호가 일치하지 않습니다. .env 자격 증명을 확인하세요."
            )
        if any(
            kw in body
            for kw in ("OTP", "보안문자", "인증번호", "CAPTCHA", "2단계")
        ):
            raise MFARequiredError(
                "2단계 인증(OTP) 또는 보안문자가 필요합니다. 최초 1회는 "
                "YONSEI_HEADED=true 로 실행해 직접 로그인하면 세션이 저장됩니다."
            )
        raise AuthFailedError(
            "LearnUs 로그인에 실패했습니다. 자격 증명 또는 추가 인증을 확인하세요."
        )


class LibrarySession(BrowserSession):
    """Owns a Playwright context authenticated against the Yonsei Library.

    The library has its own POST login form (``form#login``) with a login-type
    radio defaulting to ``SSO`` (연세포털 ID). Filling ``#id`` / ``#password`` and
    submitting logs in directly — no infra SSO redirect hop (verified). Cookies
    are kept in a separate store from LearnUs so the two never clobber each other.
    """

    def __init__(self, settings: Optional[Settings] = None) -> None:
        s = settings or load_settings()
        storage = _account_storage(s, "library", "library.json")
        super().__init__(s, storage)

    async def _is_authenticated(self, page: Page) -> bool:
        if "library.yonsei.ac.kr" not in page.url:
            return False
        try:
            return await page.locator(_LIBRARY_LOGOUT_SELECTOR).count() > 0
        except Exception:
            return False

    async def _login(self, page: Page) -> None:
        if not self.settings.has_credentials:
            raise AuthRequiredError(
                "연세 포털 자격 증명이 없습니다. .env 파일에 YONSEI_ID/ID 와 "
                "YONSEI_PASSWORD/password 를 설정하세요."
            )

        nav_timeout = self.settings.nav_timeout_ms
        await page.goto(LIBRARY_URL, wait_until="domcontentloaded")
        if await self._is_authenticated(page):
            return

        await page.goto(LIBRARY_LOGIN_URL, wait_until="domcontentloaded")
        try:
            await page.wait_for_selector("#id", timeout=nav_timeout)
        except PlaywrightTimeoutError as exc:
            raise ScrapeFailedError(
                "도서관 로그인 폼(#id)을 제시간 내에 불러오지 못했습니다."
            ) from exc
        # The SSO (연세포털 ID) radio is the default; make sure it stays selected.
        try:
            await page.check("#sso", timeout=2_000)
        except Exception:
            pass
        await page.fill("#id", self.settings.yonsei_id)
        await page.fill("#password", self.settings.yonsei_password)
        # Submitting redirects back to the library home on success; the logout
        # link only exists once authenticated.
        await page.click('#login input[type="submit"], #login button[type="submit"]')
        try:
            await page.wait_for_selector(
                _LIBRARY_LOGOUT_SELECTOR, timeout=nav_timeout
            )
        except PlaywrightTimeoutError:
            pass

        if not await self._is_authenticated(page):
            await self._raise_library_login_failure(page)

        await self._save_storage_state()

    async def _raise_library_login_failure(self, page: Page) -> None:
        body = ""
        try:
            body = (await page.inner_text("body"))[:4000]
        except Exception:
            body = ""
        if any(
            kw in body
            for kw in ("일치하지 않", "비밀번호를 확인", "등록되지 않은", "확인하시기")
        ):
            raise AuthFailedError(
                "아이디 또는 비밀번호가 일치하지 않습니다. .env 자격 증명을 확인하세요."
            )
        raise AuthFailedError(
            "도서관 로그인에 실패했습니다. 자격 증명 또는 추가 인증을 확인하세요."
        )


class ErpSession(BrowserSession):
    """Owns a Playwright context authenticated against the ERP (underwood1).

    Visiting ``underwood1.yonsei.ac.kr`` while unauthenticated redirects straight
    to the Yonsei infra SSO form with ``#loginId`` already present — unlike
    LearnUs there is no ``a.btn-sso`` hop. We fill the same infra form and submit
    through the page's own ``fSubmitSSOLoginForm()`` function, then wait to land
    back on underwood1. Cookies live in their own ``erp.json`` store (the ERP
    cookie domain is unrelated to LearnUs / Library).
    """

    def __init__(self, settings: Optional[Settings] = None) -> None:
        s = settings or load_settings()
        storage = _account_storage(s, "erp", "erp.json")
        super().__init__(s, storage)

    async def _is_authenticated(self, page: Page) -> bool:
        if "underwood1.yonsei.ac.kr" not in page.url:
            return False
        try:
            # The SSO form means we are NOT logged in yet.
            if await page.locator("#loginId").count() > 0:
                return False
            # The authenticated shell always shows a 로그아웃 control.
            return await page.get_by_text("로그아웃", exact=False).count() > 0
        except Exception:
            return False

    async def _login(self, page: Page) -> None:
        if not self.settings.has_credentials:
            raise AuthRequiredError(
                "연세 포털 자격 증명이 없습니다. .env 파일에 YONSEI_ID/ID 와 "
                "YONSEI_PASSWORD/password 를 설정하세요."
            )

        nav_timeout = self.settings.nav_timeout_ms
        await page.goto(ERP_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(1_200)
        if await self._is_authenticated(page):
            return

        # Unauthenticated visits land directly on the infra SSO form.
        try:
            await page.locator("#loginId").or_(
                page.get_by_text("로그아웃", exact=False)
            ).first.wait_for(timeout=nav_timeout)
        except PlaywrightTimeoutError as exc:
            raise ScrapeFailedError(
                "ERP 로그인 폼 또는 인증 화면을 제시간 내에 불러오지 못했습니다."
            ) from exc
        if await self._is_authenticated(page):
            return
        await page.fill("#loginId", self.settings.yonsei_id)
        await page.fill("#loginPasswd", self.settings.yonsei_password)
        await page.evaluate("fSubmitSSOLoginForm()")

        try:
            await page.wait_for_url(
                "**underwood1.yonsei.ac.kr/**", timeout=nav_timeout
            )
            await page.get_by_text("로그아웃", exact=False).first.wait_for(
                timeout=15_000
            )
        except PlaywrightTimeoutError:
            pass

        if not await self._is_authenticated(page) and self.settings.headed:
            try:
                await page.wait_for_url(
                    "**underwood1.yonsei.ac.kr/**",
                    timeout=_INTERACTIVE_LOGIN_TIMEOUT_MS,
                )
            except PlaywrightTimeoutError:
                pass

        if not await self._is_authenticated(page):
            await self._raise_erp_login_failure(page)

        await self._save_storage_state()

    async def _raise_erp_login_failure(self, page: Page) -> None:
        body = ""
        try:
            body = (await page.inner_text("body"))[:4000]
        except Exception:
            body = ""
        if any(
            kw in body
            for kw in ("일치하지 않", "비밀번호를 확인", "등록되지 않은 아이디")
        ):
            raise AuthFailedError(
                "아이디 또는 비밀번호가 일치하지 않습니다. .env 자격 증명을 확인하세요."
            )
        if any(kw in body for kw in ("OTP", "보안문자", "인증번호", "CAPTCHA", "2단계")):
            raise MFARequiredError(
                "2단계 인증(OTP) 또는 보안문자가 필요합니다. 최초 1회는 "
                "YONSEI_HEADED=true 로 실행해 직접 로그인하면 세션이 저장됩니다."
            )
        raise AuthFailedError(
            "학사행정(ERP) 로그인에 실패했습니다. 자격 증명 또는 추가 인증을 확인하세요."
        )


_session: Optional[LearnUsSession] = None
_library_session: Optional[LibrarySession] = None
_erp_session: Optional[ErpSession] = None


def validate_session_settings(settings: Settings) -> None:
    for session in (_session, _library_session, _erp_session):
        if session is not None and session.settings != settings:
            raise AuthRequiredError("로그인 설정이 변경되었습니다. MCP 서버를 재시작하세요.")


def get_session() -> LearnUsSession:
    global _session
    settings = load_settings()
    validate_session_settings(settings)
    if _session is None:
        _session = LearnUsSession(settings)
    return _session


def get_library_session() -> LibrarySession:
    global _library_session
    settings = load_settings()
    validate_session_settings(settings)
    if _library_session is None:
        _library_session = LibrarySession(settings)
    return _library_session


def get_erp_session() -> ErpSession:
    global _erp_session
    settings = load_settings()
    validate_session_settings(settings)
    if _erp_session is None:
        _erp_session = ErpSession(settings)
    return _erp_session


async def close_sessions() -> None:
    """Release only sessions already created by this MCP process."""
    global _session, _library_session, _erp_session
    opened = (_session, _library_session, _erp_session)
    _session = _library_session = _erp_session = None
    await asyncio.gather(*(session.close() for session in opened if session is not None))

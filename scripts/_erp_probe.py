"""Exploratory probe: can we log into the ERP (underwood1) via portal SSO?

Read-only. Reports the redirect landing + whether grade/timetable menus exist.
"""
import asyncio
import os
import sys
from pathlib import Path

os.environ.setdefault("YONSEI_HEADED", "false")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from playwright.async_api import async_playwright  # noqa: E402

from yonsei_portal_mcp.config import load_settings  # noqa: E402

PORTAL = "https://portal.yonsei.ac.kr/"
ERP = "https://underwood1.yonsei.ac.kr/"


async def main() -> None:
    s = load_settings()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not s.headed)
        ctx = await browser.new_context()
        page = await ctx.new_page()

        await page.goto(PORTAL, wait_until="domcontentloaded")
        await page.wait_for_timeout(2500)
        print("PORTAL landed:", page.url, "| title:", await page.title())

        # Does a login form / SSO field appear directly, or is there a button?
        has_loginid = await page.locator("#loginId").count()
        has_sso_btn = await page.locator(
            "a.btn-sso, a[href*='sso'], button:has-text('로그인'), a:has-text('로그인')"
        ).count()
        print("loginId field:", has_loginid, "| login-ish elements:", has_sso_btn)

        # Try the infra SSO directly via ERP entry (may redirect to login).
        await page.goto(ERP, wait_until="domcontentloaded")
        await page.wait_for_timeout(2500)
        print("ERP landed:", page.url, "| title:", await page.title())
        print("ERP loginId field:", await page.locator("#loginId").count())

        # Dump a snippet of visible text to understand the gate.
        try:
            body = (await page.inner_text("body"))[:600]
        except Exception as e:  # noqa: BLE001
            body = f"<err {e}>"
        print("--- ERP body snippet ---")
        print(body)

        # List frames (ERP is iframe-heavy).
        print("--- frames ---")
        for f in page.frames:
            print("  frame:", f.url[:120])

        await ctx.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())

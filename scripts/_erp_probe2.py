"""Exploratory probe 2: actually log into ERP and dump post-login structure."""
import asyncio
import os
import sys
from pathlib import Path

os.environ.setdefault("YONSEI_HEADED", "false")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from playwright.async_api import async_playwright  # noqa: E402

from yonsei_portal_mcp.config import load_settings  # noqa: E402

ERP = "https://underwood1.yonsei.ac.kr/"


async def main() -> None:
    s = load_settings()
    if not s.has_credentials:
        print("NO CREDENTIALS")
        return
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not s.headed)
        ctx = await browser.new_context()
        page = await ctx.new_page()

        await page.goto(ERP, wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)
        if await page.locator("#loginId").count():
            await page.fill("#loginId", s.yonsei_id)
            pw_sel = "#loginPasswd" if await page.locator("#loginPasswd").count() else "#loginPwd"
            await page.fill(pw_sel, s.yonsei_password)
            try:
                await page.evaluate("fSubmitSSOLoginForm()")
            except Exception as e:  # noqa: BLE001
                print("submit fn err:", e)
                await page.locator("button:has-text('로그인'), input[type=submit]").first.click()
            await page.wait_for_timeout(5000)

        print("AFTER LOGIN url:", page.url, "| title:", await page.title())
        try:
            body = (await page.inner_text("body"))[:400]
        except Exception as e:  # noqa: BLE001
            body = f"<err {e}>"
        print("--- body snippet ---\n", body)

        print("--- frames ---")
        for f in page.frames:
            print("  frame:", f.url[:140])

        # Look for left-menu category labels across all frames.
        cats = ["학적", "수업", "성적", "졸업", "등록", "장학", "시간표", "강의시간표"]
        for f in page.frames:
            try:
                txt = await f.inner_text("body")
            except Exception:
                continue
            found = [c for c in cats if c in txt]
            if found:
                print(f"  [{f.url[:80]}] contains:", found)

        await ctx.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())

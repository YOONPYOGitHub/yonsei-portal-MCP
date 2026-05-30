"""Probe 9: wait for lazy grade iframe, enumerate, dump rows."""
import asyncio
import os
import sys
from pathlib import Path

os.environ.setdefault("YONSEI_HEADED", "false")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from playwright.async_api import async_playwright  # noqa: E402

from yonsei_portal_mcp.config import load_settings  # noqa: E402

ERP = "https://underwood1.yonsei.ac.kr/"


async def login(page, s):
    await page.goto(ERP, wait_until="domcontentloaded")
    await page.wait_for_timeout(2000)
    if await page.locator("#loginId").count():
        await page.fill("#loginId", s.yonsei_id)
        await page.fill("#loginPasswd", s.yonsei_password)
        await page.evaluate("fSubmitSSOLoginForm()")
        await page.wait_for_timeout(5000)


async def main() -> None:
    s = load_settings()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not s.headed)
        ctx = await browser.new_context()
        page = await ctx.new_page()
        await login(page, s)
        await page.wait_for_timeout(2000)
        mf = page.main_frame

        await mf.get_by_text("성적", exact=True).first.click()
        await page.wait_for_timeout(1500)
        await mf.get_by_text("전체성적조회", exact=True).first.click()

        # Poll for new frames + grade row text over 12s.
        for i in range(6):
            await page.wait_for_timeout(2000)
            print(f"--- t={2*(i+1)}s frames={len(page.frames)} ---")
        for f in page.frames:
            print("FRAME:", f.url[:120])

        # Search every frame for table rows w/ grade tokens.
        for f in page.frames:
            try:
                ntab = await f.locator("table tr").count()
            except Exception:
                continue
            if ntab:
                try:
                    body = await f.inner_text("body")
                except Exception:
                    continue
                hit = [l.strip() for l in body.split("\n")
                       if l.strip() and any(k in l for k in ["A+", "A0", "B+", "P", "학기", "201", "202", "평점", "취득"])]
                if hit:
                    print(f"\n### GRADE-ish frame {f.url[-50:]} (tr={ntab}) ###")
                    for l in hit[:30]:
                        print("   >", l[:140])

        await ctx.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())

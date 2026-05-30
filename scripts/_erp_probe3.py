"""Probe 3: navigate ERP menu to grades & timetable, capture sub-items/tables."""
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

        main_frame = page.main_frame

        async def click_text(label):
            loc = main_frame.get_by_text(label, exact=True)
            n = await loc.count()
            if n == 0:
                print(f"  '{label}' not found")
                return False
            await loc.first.click()
            await page.wait_for_timeout(1800)
            return True

        for cat in ["성적", "수업"]:
            print(f"=== category: {cat} ===")
            await click_text(cat)
            # After expanding, dump menu-ish leaf labels containing key words.
            try:
                txt = await main_frame.inner_text("body")
            except Exception as e:  # noqa: BLE001
                txt = f"<err {e}>"
            keys = [
                "성적조회", "성적표", "취득성적", "학기별성적", "성적증명",
                "시간표", "수강", "강의시간표", "개인시간표",
            ]
            print("  leaf hits:", [k for k in keys if k in txt])

        # Try opening a grade query menu explicitly.
        for leaf in ["학기별성적조회", "취득성적조회", "성적조회", "개인별시간표조회", "개인시간표조회"]:
            loc = main_frame.get_by_text(leaf, exact=True)
            if await loc.count():
                print(f"--- opening '{leaf}' ---")
                await loc.first.click()
                await page.wait_for_timeout(2500)
                # Dump tables in all frames.
                for f in page.frames:
                    try:
                        ntab = await f.locator("table").count()
                    except Exception:
                        continue
                    if ntab:
                        print(f"  frame {f.url[:70]} tables={ntab}")
                break

        await ctx.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())

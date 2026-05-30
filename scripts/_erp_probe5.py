"""Probe 5: open 전체성적조회 & 수업시간표조회, capture table DOM."""
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


async def dump_tables(page, tag):
    print(f"\n##### {tag}: frames & tables #####")
    for f in page.frames:
        try:
            tabs = f.locator("table")
            n = await tabs.count()
        except Exception:
            continue
        for i in range(n):
            try:
                t = tabs.nth(i)
                rows = await t.locator("tr").count()
                if rows < 2:
                    continue
                txt = (await t.inner_text())[:500].replace("\n", " | ")
                if any(k in txt for k in ["과목", "학점", "등급", "평점", "요일", "교시", "강의실", "시간"]):
                    print(f"  frame={f.url[-40:]} table#{i} rows={rows}")
                    print("    ", txt)
            except Exception:
                continue


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
        await page.wait_for_timeout(3500)
        await dump_tables(page, "전체성적조회")

        await mf.get_by_text("수업", exact=True).first.click()
        await page.wait_for_timeout(1500)
        await mf.get_by_text("수업시간표조회", exact=True).first.click()
        await page.wait_for_timeout(3500)
        await dump_tables(page, "수업시간표조회")

        await ctx.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())

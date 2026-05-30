"""Probe 7: dump main-frame body of 전체성적조회 + detect grid framework."""
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
        await page.wait_for_timeout(4000)

        # Detect grid framework globals.
        fw = await mf.evaluate(
            """() => ({
                websquare: typeof window.WebSquare !== 'undefined' || typeof window.$w !== 'undefined',
                nexacro: typeof window.nexacro !== 'undefined',
                miplatform: typeof window.MIP !== 'undefined',
                realgrid: typeof window.RealGrid !== 'undefined' || !!document.querySelector('[id*=realgrid]'),
                ag: !!document.querySelector('.ag-root'),
                wq_grid: document.querySelectorAll('[id*=grd], [id*=Grid], [class*=w2grid]').length,
            })"""
        )
        print("FRAMEWORK:", fw)

        # Dump body text of the active screen region.
        body = await mf.inner_text("body")
        lines = [l.strip() for l in body.split("\n") if l.strip()]
        print(f"\nMAIN BODY lines={len(lines)}; tail showing screen content:")
        # show lines after the menu (heuristic: lines containing grade-ish tokens)
        for l in lines:
            if any(k in l for k in ["전체성적", "학기", "학점", "평점", "등급", "GPA", "취득", "이수", "신청", "과목", "조회"]):
                print("   >", l[:140])

        # Count w2grid rows if WebSquare grid present.
        gridinfo = await mf.evaluate(
            """() => {
                const grids = document.querySelectorAll('[id*=grd],[id*=Grid],[class*=w2grid]');
                return [...grids].slice(0,5).map(g => ({id:g.id, cls:g.className, rows:g.querySelectorAll('tr').length}));
            }"""
        )
        print("\nGRID ELEMENTS:", gridinfo)

        await ctx.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())

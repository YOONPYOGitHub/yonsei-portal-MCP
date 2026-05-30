"""Probe 12: capture request payloads for grade + timetable endpoints."""
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
    reqs = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not s.headed)
        ctx = await browser.new_context()
        page = await ctx.new_page()

        async def on_request(req):
            u = req.url
            if any(k in u for k in ["Sgrarg", "findAllGrade", "Sttb", "Lect", "Tmtb", "timetable", "Sugang", "findMy", "Smtb"]):
                try:
                    pd = req.post_data
                except Exception:
                    pd = None
                reqs.append((req.method, u.split("underwood1.yonsei.ac.kr")[-1][:80], (pd or "")[:500]))

        page.on("request", on_request)
        await login(page, s)
        await page.wait_for_timeout(2000)
        mf = page.main_frame

        # GRADES
        await mf.get_by_text("성적", exact=True).first.click()
        await page.wait_for_timeout(1200)
        reqs.clear()
        await mf.get_by_text("전체성적조회", exact=True).first.click()
        await page.wait_for_timeout(7000)
        print("=== GRADE requests ===")
        for m, u, pd in reqs:
            print(f"  {m} {u}\n     POST={pd!r}")

        # TIMETABLE
        await mf.get_by_text("수업", exact=True).first.click()
        await page.wait_for_timeout(1200)
        reqs.clear()
        tt = mf.get_by_text("수업시간표조회", exact=True)
        if await tt.count():
            await tt.first.click()
            await page.wait_for_timeout(7000)
        print("\n=== TIMETABLE requests ===")
        for m, u, pd in reqs:
            print(f"  {m} {u}\n     POST={pd!r}")

        await ctx.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())

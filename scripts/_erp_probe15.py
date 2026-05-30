"""Probe 15: capture ALL .do JSON during timetable open to find schedule detail."""
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
    caught = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not s.headed)
        ctx = await browser.new_context()
        page = await ctx.new_page()

        async def on_resp(resp):
            u = resp.url
            if ".do" in u and "underwood1" in u:
                ct = resp.headers.get("content-type", "")
                if "json" in ct:
                    try:
                        b = await resp.text()
                    except Exception:
                        b = ""
                    # only show ones not already-known noise
                    if not any(k in u for k in ["MenuCtr", "PropCtr", "DataCtr", "CodeCtr", "findOpenMenu"]):
                        caught.append((u.split("underwood1.yonsei.ac.kr")[-1][:80], b[:700]))

        page.on("response", on_resp)
        await login(page, s)
        await page.wait_for_timeout(1500)
        mf = page.main_frame
        await mf.get_by_text("수업", exact=True).first.click()
        await page.wait_for_timeout(1500)
        caught.clear()
        await mf.get_by_text("수업시간표조회", exact=True).first.click()
        await page.wait_for_timeout(6000)

        # try clicking a 조회 button if present in any frame
        for f in page.frames:
            try:
                btn = f.get_by_text("조회", exact=True)
                if await btn.count():
                    await btn.first.click()
                    await page.wait_for_timeout(4000)
                    break
            except Exception:
                pass
        await page.wait_for_timeout(2000)

        print(f"=== {len(caught)} data .do responses ===")
        for u, b in caught:
            print(f"\n{u}\n   {b!r}")

        await ctx.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())

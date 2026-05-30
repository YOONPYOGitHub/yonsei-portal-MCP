"""Probe 14: open timetable only, capture all .do JSON to find data endpoint."""
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
            if ".do" in u and "underwood1" in u and "Ctr/find" in u:
                ct = resp.headers.get("content-type", "")
                if "json" in ct:
                    try:
                        b = (await resp.text())
                    except Exception:
                        b = ""
                    caught.append((u.split("underwood1.yonsei.ac.kr")[-1][:75], len(b), b[:350]))

        page.on("response", on_resp)
        await login(page, s)
        await page.wait_for_timeout(1500)
        mf = page.main_frame

        await mf.get_by_text("수업", exact=True).first.click()
        await page.wait_for_timeout(1500)
        caught.clear()
        await mf.get_by_text("수업시간표조회", exact=True).first.click()
        await page.wait_for_timeout(8000)

        print(f"=== {len(caught)} json responses during timetable open ===")
        for u, n, b in caught:
            # highlight ones with real data arrays
            print(f"\n{u}  len={n}")
            print(f"   {b!r}")

        await ctx.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())

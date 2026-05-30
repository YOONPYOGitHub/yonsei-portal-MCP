"""Probe 6: deep-dive 전체성적조회 - find 조회 button + grid structure."""
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
        await page.wait_for_timeout(3500)

        # The active tab content lives in an iframe. Identify the newest frame
        # that holds the screen (has buttons / grids).
        print("FRAMES:")
        for f in page.frames:
            print("  ", f.url[:110])

        # Search all frames for a 조회 button and click it.
        for f in page.frames:
            try:
                btn = f.get_by_text("조회", exact=True)
                if await btn.count():
                    print("found 조회 in", f.url[-40:])
                    try:
                        await btn.first.click()
                        await page.wait_for_timeout(3000)
                    except Exception as e:  # noqa: BLE001
                        print("  click err", e)
                    break
            except Exception:
                continue

        # Dump structure: every frame's tables/grids text.
        for f in page.frames:
            try:
                ntab = await f.locator("table").count()
                ngrid = await f.locator("[class*=grid], [id*=grid], [class*=Grid]").count()
            except Exception:
                continue
            if ntab or ngrid:
                print(f"\nframe {f.url[-50:]} tables={ntab} grids={ngrid}")
                try:
                    body = (await f.inner_text("body"))
                    # print lines that look like grade rows
                    for line in body.split("\n"):
                        line = line.strip()
                        if line and any(k in line for k in ["학점", "등급", "평점", "GPA", "취득", "이수", "과목"]):
                            print("   >", line[:120])
                except Exception:
                    pass

        await ctx.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())

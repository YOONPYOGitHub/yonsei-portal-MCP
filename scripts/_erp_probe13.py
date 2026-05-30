"""Probe 13: timetable endpoint + direct page.request call to grade endpoint."""
import asyncio
import os
import sys
from pathlib import Path

os.environ.setdefault("YONSEI_HEADED", "false")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from playwright.async_api import async_playwright  # noqa: E402

from yonsei_portal_mcp.config import load_settings  # noqa: E402

ERP = "https://underwood1.yonsei.ac.kr/"
GRADE_EP = ERP + "sch/sgra/SgrargCtr/findAllGradeDtlAsSyySmtList.do"


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

        async def on_resp(resp):
            u = resp.url
            if ".do" in u and "underwood1" in u and any(
                k in u for k in ["Sttb", "Lect", "Tmtb", "Smtb", "Sugang", "Sufm", "lectTime", "TimeTable", "Cour"]
            ):
                try:
                    b = (await resp.text())[:600]
                except Exception:
                    b = "<nobody>"
                reqs.append((u.split("underwood1.yonsei.ac.kr")[-1][:70], b))

        page.on("response", on_resp)
        await login(page, s)
        await page.wait_for_timeout(1500)

        # (a) direct grade endpoint call via page.request (reuses cookies)
        try:
            r = await page.request.post(
                GRADE_EP,
                form={"@d1#syy": "", "@d1#smtDivCd": "", "@d#": "@d1#", "@d1#": "dmCond", "@d1#tp": "dm"},
            )
            print("DIRECT grade call status:", r.status)
            print("  body:", (await r.text())[:300])
        except Exception as e:  # noqa: BLE001
            print("direct call err:", e)

        # (b) open timetable freshly
        mf = page.main_frame
        await mf.get_by_text("수업", exact=True).first.click()
        await page.wait_for_timeout(1500)
        reqs.clear()
        tt = mf.get_by_text("수업시간표조회", exact=True)
        print("\ntimetable menu count:", await tt.count())
        if await tt.count():
            await tt.first.click()
            await page.wait_for_timeout(8000)
        print("=== TIMETABLE data responses ===")
        for u, b in reqs:
            print(f"  {u}\n     {b[:400]!r}")

        await ctx.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())

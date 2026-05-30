"""Probe 16: find & click timetable query button, capture schedule detail."""
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
            if ".do" in u and "underwood1" in u and "json" in resp.headers.get("content-type", ""):
                if not any(k in u for k in ["MenuCtr", "PropCtr", "DataCtr", "CodeCtr", "findOpenMenu", "findAccpsStdSchdlList"]):
                    try:
                        b = await resp.text()
                    except Exception:
                        b = ""
                    caught.append((u.split("underwood1.yonsei.ac.kr")[-1][:80], b[:900]))

        page.on("response", on_resp)
        await login(page, s)
        await page.wait_for_timeout(1500)
        mf = page.main_frame
        await mf.get_by_text("수업", exact=True).first.click()
        await page.wait_for_timeout(1500)
        await mf.get_by_text("수업시간표조회", exact=True).first.click()
        await page.wait_for_timeout(6000)

        # Enumerate candidate query buttons in main frame.
        btns = await mf.evaluate(
            """() => {
                const out=[];
                document.querySelectorAll("a,button,input,img,[onclick],[role=button]").forEach((b,i)=>{
                    const t=(b.innerText||b.value||b.title||b.alt||'').trim();
                    const oc=(b.getAttribute('onclick')||'').slice(0,40);
                    if(/조회|검색|search|find/i.test(t+oc)) out.push({i, t, id:b.id, oc});
                });
                return out.slice(0,20);
            }"""
        )
        print("query-ish buttons:", btns)

        # Click first 조회-ish element and capture.
        caught.clear()
        clicked = False
        for sel in ["조회", "검색"]:
            loc = mf.get_by_role("button", name=sel)
            if await loc.count():
                await loc.first.click(); clicked = True; break
        if not clicked:
            loc = mf.locator("a:has-text('조회'), button:has-text('조회'), input[value='조회'], img[alt*='조회']")
            if await loc.count():
                await loc.first.click(); clicked = True
        print("clicked query button:", clicked)
        await page.wait_for_timeout(6000)

        print(f"\n=== {len(caught)} detail responses after query ===")
        for u, b in caught:
            print(f"\n{u}\n   {b!r}")

        await ctx.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())

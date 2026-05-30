"""Probe 18: click the screen-local 조회 button on timetable, capture detail."""
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
    seen = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not s.headed)
        ctx = await browser.new_context()
        page = await ctx.new_page()

        async def on_resp(resp):
            u = resp.url
            if ".do" in u and "underwood1" in u and "json" in resp.headers.get("content-type", ""):
                if any(k in u for k in ["Sles", "Sgra", "Lect", "Tmtb", "Schdl", "sles", "sgra"]) and "findAccpsStdSchdlList" not in u:
                    try:
                        b = await resp.text()
                    except Exception:
                        b = ""
                    seen.append((u.split("underwood1.yonsei.ac.kr")[-1].split("?")[0], b[:1200]))

        page.on("response", on_resp)
        await login(page, s)
        await page.wait_for_timeout(1500)
        mf = page.main_frame
        await mf.get_by_text("수업", exact=True).first.click()
        await page.wait_for_timeout(1500)
        await mf.get_by_text("수업시간표조회", exact=True).first.click()
        await page.wait_for_timeout(6000)

        # Enumerate exact "조회" buttons with geometry, click ones in screen body.
        cands = await mf.evaluate(
            """() => {
                const out=[];
                document.querySelectorAll("a,button,input,[role=button]").forEach((b)=>{
                    const t=(b.innerText||b.value||b.title||'').trim();
                    if(t==='조회'){
                        const r=b.getBoundingClientRect();
                        out.push({id:b.id, cls:(b.className||'').slice(0,40), x:Math.round(r.x), y:Math.round(r.y), w:Math.round(r.width)});
                    }
                });
                return out;
            }"""
        )
        print("exact-조회 buttons:", cands)

        # Click each visible 조회 by id and capture.
        for c in cands:
            if not c.get("id"):
                continue
            seen.clear()
            try:
                await mf.locator(f"#{c['id']}").click(timeout=4000)
                await page.wait_for_timeout(5000)
            except Exception as e:  # noqa: BLE001
                print(f"  click #{c['id']} err:", str(e)[:80])
                continue
            print(f"\n--- after click #{c['id']} ({c['x']},{c['y']}): {len(seen)} detail resp ---")
            for u, b in seen:
                print(f"   {u}\n     {b!r}")
            if seen:
                break

        await ctx.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())

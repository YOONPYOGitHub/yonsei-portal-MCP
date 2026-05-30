"""Probe 10: dump main-frame grade rows + grid HTML structure after wait."""
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
        await page.wait_for_timeout(8000)

        print("=== MAIN BODY after wait ===")
        print((await mf.inner_text("body"))[:2500])

        # Find any element containing grade letters and dump its tag/class/id chain.
        info = await mf.evaluate(
            """() => {
                const res = {tables: document.querySelectorAll('table').length, divGrids: [], gradeCells: []};
                // grade-letter cells
                const all = document.querySelectorAll('td,div,span');
                let count=0;
                for (const e of all) {
                    const t=(e.textContent||'').trim();
                    if (/^(A\\+|A0|A-|B\\+|B0|B-|C\\+|C0|P|NP)$/.test(t)) {
                        res.gradeCells.push({tag:e.tagName, cls:e.className, id:e.id, txt:t});
                        if (++count>8) break;
                    }
                }
                // grid containers
                document.querySelectorAll("[id*='grd'],[id*='grid'],[id*='Grid'],[class*='grid'],[class*='Grid'],[class*='dhx'],[class*='ag-']").forEach(g=>{
                    if(res.divGrids.length<8) res.divGrids.push({tag:g.tagName,id:g.id,cls:(g.className||'').slice(0,60)});
                });
                return res;
            }"""
        )
        print("\n=== STRUCT ===")
        print("tables:", info["tables"])
        print("gradeCells:", info["gradeCells"])
        print("divGrids:", info["divGrids"])

        await ctx.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())

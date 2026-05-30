"""Probe 4: list exact menu leaf labels under 성적 and 수업."""
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

        for cat in ["성적", "수업"]:
            await mf.get_by_text(cat, exact=True).first.click()
            await page.wait_for_timeout(1800)
            print(f"=== {cat}: candidate menu items ===")
            # Grab all anchor/li/span with menu-ish handlers
            items = await mf.evaluate(
                """() => {
                    const out = [];
                    const els = document.querySelectorAll('a, li, span, div');
                    for (const e of els) {
                        const t = (e.innerText||'').trim();
                        if (!t || t.length>20 || t.includes('\\n')) continue;
                        if (/성적|시간표|수강|증명|조회/.test(t)) out.push(t);
                    }
                    return [...new Set(out)];
                }"""
            )
            for it in items:
                print("  ", it)

        await ctx.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())

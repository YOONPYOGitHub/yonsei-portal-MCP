"""Probe 11: capture network XHR endpoints the grade screen calls."""
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
    captured = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not s.headed)
        ctx = await browser.new_context()
        page = await ctx.new_page()
        await login(page, s)
        await page.wait_for_timeout(2000)
        mf = page.main_frame

        async def on_response(resp):
            try:
                url = resp.url
                if ".do" in url and "underwood1" in url:
                    ct = resp.headers.get("content-type", "")
                    if any(x in ct for x in ["json", "xml", "text"]):
                        body = ""
                        try:
                            body = (await resp.text())[:400]
                        except Exception:
                            body = "<nobody>"
                        captured.append((url, ct, body))
            except Exception:
                pass

        page.on("response", on_response)

        await mf.get_by_text("성적", exact=True).first.click()
        await page.wait_for_timeout(1500)
        captured.clear()
        await mf.get_by_text("전체성적조회", exact=True).first.click()
        await page.wait_for_timeout(9000)

        print(f"=== captured {len(captured)} .do responses ===")
        for url, ct, body in captured:
            short = url.split("underwood1.yonsei.ac.kr")[-1][:90]
            print(f"\nURL {short}\n  ct={ct}\n  body={body[:300]!r}")

        await ctx.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())

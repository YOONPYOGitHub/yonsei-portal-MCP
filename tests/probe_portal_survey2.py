"""READ-ONLY survey v2: per-category ERP leaves + portal dashboard iframe."""
from __future__ import annotations

import asyncio

from yonsei_portal_mcp.config import ERP_URL
from yonsei_portal_mcp.session import ErpSession

PORTAL_INDEX = "https://portal.yonsei.ac.kr/ui/index.html"

_JS_LABELS = """
() => {
  const out = new Set();
  for (const el of document.querySelectorAll('a, li, span, td, div, p')) {
    const t = (el.innerText || '').trim();
    if (!t || t.length > 24 || t.split('\\n').length > 1) continue;
    if (!/[가-힣]/.test(t)) continue;
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) continue;
    out.add(t);
  }
  return Array.from(out);
}
"""


async def main() -> None:
    sess = ErpSession()
    async with sess.page() as page:
        if "underwood1.yonsei.ac.kr" not in page.url:
            await page.goto(ERP_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(2_500)
        mf = page.main_frame
        base = set(await mf.evaluate(_JS_LABELS))

        categories = ["학적", "수업", "성적", "졸업", "등록", "장학",
                      "학생지원", "학사기타", "셔틀버스", "기숙사(신촌)",
                      "국제학생교류", "지도교수면담"]
        for cat in categories:
            try:
                loc = mf.get_by_text(cat, exact=True).first
                if await loc.count() == 0:
                    print(f"CAT-MISS| {cat}")
                    continue
                await loc.click(timeout=4_000)
                await page.wait_for_timeout(1_100)
                now = set(await mf.evaluate(_JS_LABELS))
                leaves = sorted(now - base - set(categories))
                print(f"\n## {cat} ({len(leaves)})")
                for t in leaves:
                    print("  -", t)
                base |= now
            except Exception as exc:  # noqa: BLE001
                print(f"CAT-ERR| {cat}: {exc}")

        # ---- portal dashboard iframe --------------------------------------
        try:
            await page.goto(PORTAL_INDEX, wait_until="domcontentloaded")
            await page.wait_for_timeout(3_500)
            print("\n=== PORTAL URL:", page.url)
            for fr in page.frames:
                if "main.jsp" in fr.url or "portal" in fr.url:
                    try:
                        labels = sorted(set(await fr.evaluate(_JS_LABELS)))
                    except Exception as exc:  # noqa: BLE001
                        print("FRAME-ERR", fr.url, exc)
                        continue
                    print(f"\n--- FRAME {fr.url} labels ({len(labels)}) ---")
                    for t in labels:
                        print("  P|", t)
        except Exception as exc:  # noqa: BLE001
            print("PORTAL probe failed:", exc)


if __name__ == "__main__":
    asyncio.run(main())

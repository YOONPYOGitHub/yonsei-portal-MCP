"""READ-ONLY live survey of what the Yonsei portal/ERP actually provides.

Logs into the ERP (underwood1) with the saved SSO session, then:
  1. Dumps the full left-menu tree (category -> leaf labels) = real 전수조사.
  2. Visits portal.yonsei.ac.kr/ui/index.html in the same authed context and
     dumps its service links / menu text.

NO write actions are performed: we only read menu labels and hrefs. The output
goes to stdout so we can capture it to a log file.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from yonsei_portal_mcp.config import ERP_URL
from yonsei_portal_mcp.session import ErpSession

PORTAL_INDEX = "https://portal.yonsei.ac.kr/ui/index.html"


async def _dump_menu_labels(mf) -> list[str]:
    """Collect short, visible, clickable text labels from the ERP menu frame."""
    js = """
    () => {
      const out = new Set();
      const els = document.querySelectorAll('a, li, span, td, div');
      for (const el of els) {
        const t = (el.innerText || '').trim();
        if (!t) continue;
        if (t.length > 22) continue;
        if (t.split('\\n').length > 1) continue;
        const r = el.getBoundingClientRect();
        if (r.width === 0 && r.height === 0) continue;
        // keep Korean-bearing labels only
        if (!/[가-힣]/.test(t)) continue;
        out.add(t);
      }
      return Array.from(out);
    }
    """
    try:
        return await mf.evaluate(js)
    except Exception as exc:  # noqa: BLE001
        return [f"<evaluate failed: {exc}>"]


async def main() -> None:
    sess = ErpSession()
    async with sess.page() as page:
        # ---- ERP shell -----------------------------------------------------
        if "underwood1.yonsei.ac.kr" not in page.url:
            await page.goto(ERP_URL, wait_until="domcontentloaded")
            await page.wait_for_timeout(2_000)
        await page.wait_for_timeout(2_500)
        print("=== ERP URL:", page.url)
        print("=== ERP frames:", [f.url for f in page.frames])

        mf = page.main_frame
        labels = await _dump_menu_labels(mf)
        print(f"\n=== ERP menu/labels ({len(labels)}) ===")
        for t in sorted(labels):
            print("ERP|", t)

        # Try clicking each top-category to reveal leaves. Common ERP categories:
        categories = [
            "학적", "수업", "성적", "졸업", "등록", "장학", "학생",
            "수강신청", "증명", "설문", "상담", "근로", "셔틀",
        ]
        for cat in categories:
            try:
                loc = mf.get_by_text(cat, exact=True).first
                if await loc.count() == 0:
                    continue
                await loc.click(timeout=4_000)
                await page.wait_for_timeout(900)
            except Exception:
                continue
        after = await _dump_menu_labels(mf)
        new = sorted(set(after) - set(labels))
        print(f"\n=== ERP leaves revealed after expanding ({len(new)}) ===")
        for t in new:
            print("LEAF|", t)

        # ---- Portal dashboard ---------------------------------------------
        try:
            await page.goto(PORTAL_INDEX, wait_until="domcontentloaded")
            await page.wait_for_timeout(3_000)
            print("\n=== PORTAL URL:", page.url)
            pmf = page.main_frame
            plabels = await _dump_menu_labels(pmf)
            print(f"=== PORTAL labels ({len(plabels)}) ===")
            for t in sorted(plabels):
                print("PORTAL|", t)
            # anchors / service links
            anchors = await pmf.evaluate(
                """() => Array.from(document.querySelectorAll('a[href]'))
                    .map(a => (a.href||'').trim())
                    .filter(h => h && !h.startsWith('javascript'))
                """
            )
            uniq = sorted(set(anchors))
            print(f"=== PORTAL anchor hrefs ({len(uniq)}) ===")
            for h in uniq[:120]:
                print("HREF|", h)
            print("=== PORTAL frames:", [f.url for f in page.frames])
        except Exception as exc:  # noqa: BLE001
            print("PORTAL probe failed:", exc)


if __name__ == "__main__":
    asyncio.run(main())

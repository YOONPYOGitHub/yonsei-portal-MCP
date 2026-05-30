"""Probe the logged-in /relation/seat page DOM (reading-room seats)."""
import asyncio
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("YONSEI_HEADED", "false")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from yonsei_portal_mcp.session import get_library_session  # noqa: E402

URL = "https://library.yonsei.ac.kr/relation/seat"

JS = """() => {
  const out = {tables: []};
  document.querySelectorAll('table').forEach(t => {
    const cls = t.className || '';
    const head = [...t.querySelectorAll('thead th, thead td')].map(e => e.innerText.trim());
    const rows = [...t.querySelectorAll('tbody tr')].slice(0, 4).map(
      tr => [...tr.querySelectorAll('td,th')].map(td => td.innerText.trim())
    );
    const nrows = t.querySelectorAll('tbody tr').length;
    out.tables.push({cls, head, nrows, sample: rows});
  });
  return out;
}"""


async def probe(page):
    await page.goto(URL, wait_until="networkidle")
    await page.wait_for_timeout(1200)
    return {"url": page.url, "title": await page.title(), **(await page.evaluate(JS))}


async def main():
    data = await get_library_session().run(probe)
    print(json.dumps(data, ensure_ascii=False, indent=2)[:5000])


if __name__ == "__main__":
    asyncio.run(main())

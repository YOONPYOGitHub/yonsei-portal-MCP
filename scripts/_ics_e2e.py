"""Quick E2E check: tool registration + real ICS export. Run headed-off.

Run: ``uv run python scripts/_ics_e2e.py``
"""
import asyncio
import os
import sys
from pathlib import Path

os.environ.setdefault("YONSEI_HEADED", "false")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from yonsei_portal_mcp import server  # noqa: E402


async def main() -> None:
    tools = await server.mcp.list_tools()
    names = [t.name for t in tools]
    print("TOOLS:", names)
    assert "export_calendar_ics" in names, "export_calendar_ics not registered"

    ics_text = await server.export_calendar_ics(include_loans=True)
    assert ics_text.startswith("BEGIN:VCALENDAR"), "bad ICS header"
    assert ics_text.rstrip().endswith("END:VCALENDAR"), "bad ICS footer"
    n_events = ics_text.count("BEGIN:VEVENT")
    print(f"ICS OK: {len(ics_text)} chars, {n_events} VEVENT(s), {len(names)} tools")
    # Show first lines (no PII expected in headers).
    print("\n".join(ics_text.split("\r\n")[:8]))
    print("ICS E2E PASSED")


if __name__ == "__main__":
    asyncio.run(main())

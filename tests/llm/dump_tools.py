"""Dump the *raw* JSON a tool returns to the model — for data-quality debugging.

Unlike :mod:`tests.llm.scenarios` (which prints the LLM's paraphrase), this
calls the MCP tools directly over the **real** stdio server and prints the
exact payload the model would receive. Use it to verify whether a wrong-looking
answer is a scraper/date bug or just how the portal data actually looks.

Usage (real portal login — requires RUN_LIVE_LLM=1)::

    RUN_LIVE_LLM=1 uv run python -m tests.llm.dump_tools
    RUN_LIVE_LLM=1 uv run python -m tests.llm.dump_tools get_lms_attendance '{"course_query":"인공지능"}'

With no positional args it dumps get_lms_deadlines and get_lms_overview.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

try:
    from dotenv import load_dotenv

    load_dotenv(override=True)
except ImportError:  # pragma: no cover
    pass

from .mcp_host import call_result_to_text, stdio_client_session


# (tool name, arguments) pairs dumped when no CLI override is given.
DEFAULT_CALLS: list[tuple[str, dict]] = [
    ("get_lms_deadlines", {}),
    ("get_lms_overview", {}),
]


def _pretty(raw: str) -> str:
    try:
        return json.dumps(json.loads(raw), ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        return raw


async def _main(calls: list[tuple[str, dict]]) -> int:
    if os.getenv("RUN_LIVE_LLM") != "1":
        print(
            "[dump] refusing live run: set RUN_LIVE_LLM=1 to confirm "
            "(real portal login + real data)",
            flush=True,
        )
        return 98

    async with stdio_client_session() as session:
        for name, args in calls:
            print("=" * 72, flush=True)
            print(f"[tool] {name}  args={json.dumps(args, ensure_ascii=False)}", flush=True)
            print("-" * 72, flush=True)
            try:
                result = await session.call_tool(name, args)
                print(_pretty(call_result_to_text(result)), flush=True)
            except Exception as exc:  # surface tool failures
                print(f"ERROR: {type(exc).__name__}: {exc}", flush=True)
    print("=" * 72, flush=True)
    return 0


def main() -> None:
    if len(sys.argv) > 1:
        name = sys.argv[1]
        args = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
        calls = [(name, args)]
    else:
        calls = DEFAULT_CALLS
    sys.exit(asyncio.run(_main(calls)))


if __name__ == "__main__":
    main()

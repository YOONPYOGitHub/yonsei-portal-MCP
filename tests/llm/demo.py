"""Manual demo runner for the LLM <-> MCP harness.

Examples (from the project root, with `.env` filled in):

    # Mocked tools (fixtures) + whatever LLM_PROVIDER points at — no portal login
    uv run python -m tests.llm.demo "이번 학기 내 시간표 알려줘"

    # Force a provider for this run
    uv run python -m tests.llm.demo --provider azure-openai "도서관 빈자리 있어?"

    # No API key needed — scripted stub provider
    uv run python -m tests.llm.demo --provider stub --tool get_my_loans "책 목록"

    # Interactive chat (keep typing questions; blank line or "exit" to quit)
    uv run python -m tests.llm.demo --chat
    uv run python -m tests.llm.demo            # (no question also starts chat)

    # FULLY LIVE: real portal login + real LLM (sends real data to the model)
    uv run python -m tests.llm.demo --live "내 시간표 알려줘"
"""
from __future__ import annotations

import argparse
import asyncio
import os

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

from .mcp_host import inmemory_client, run_agent, stdio_client_session
from .providers import ProviderUnavailable, StubProvider, make_provider


async def _main(args: argparse.Namespace) -> int:
    if args.provider == "stub":
        planned = [(args.tool, {})] if args.tool else [("get_my_timetable", {})]
        provider = StubProvider(planned_calls=planned)
    else:
        try:
            provider = make_provider(args.provider)
        except ProviderUnavailable as exc:
            print(f"[demo] provider unavailable: {exc}")
            return 2

    chat = args.chat or not args.question
    if chat:
        return await _run_chat(args, provider)

    print(f"[demo] provider = {provider.name}")
    print(f"[demo] question = {args.question}")
    print(f"[demo] mode     = {'LIVE portal' if args.live else 'mocked fixtures'}")
    print("-" * 60)

    if args.live:
        if os.getenv("RUN_LIVE_LLM") != "1":
            print("[demo] refusing live run: set RUN_LIVE_LLM=1 to confirm")
            return 3
        async with stdio_client_session() as session:
            run = await run_agent(session, provider, args.question, max_turns=8)
    else:
        async with inmemory_client(mock_tools=True) as session:
            run = await run_agent(session, provider, args.question, max_turns=8)

    print("[demo] tools called:", run.called_tool_names or "(none)")
    print("-" * 60)
    print(run.final_text or "(no answer)")
    return 0


async def _chat_loop(session, provider, *, live: bool) -> None:
    """Read questions from stdin and answer them, reusing one MCP session."""
    print(f"[demo] provider = {provider.name}")
    print(f"[demo] mode     = {'LIVE portal' if live else 'mocked fixtures'}")
    print("[demo] type a question and press Enter. Blank line or 'exit' quits.")
    print("-" * 60)
    loop = asyncio.get_event_loop()
    while True:
        # Print the prompt first, then read with a bare input() so the
        # terminal's own line editing (cooked mode) handles backspace and
        # cannot erase the prompt. Passing the prompt to input() while running
        # in a worker thread confuses readline and eats the prompt text.
        print("\nyou> ", end="", flush=True)
        try:
            question = (await loop.run_in_executor(None, input)).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not question or question.lower() in {"exit", "quit", ":q"}:
            break
        run = await run_agent(session, provider, question, max_turns=8)
        if run.called_tool_names:
            print("[tools]", ", ".join(run.called_tool_names))
        print("bot>", run.final_text or "(no answer)")


async def _run_chat(args: argparse.Namespace, provider) -> int:
    if args.live:
        if os.getenv("RUN_LIVE_LLM") != "1":
            print("[demo] refusing live run: set RUN_LIVE_LLM=1 to confirm")
            return 3
        async with stdio_client_session() as session:
            await _chat_loop(session, provider, live=True)
    else:
        async with inmemory_client(mock_tools=True) as session:
            await _chat_loop(session, provider, live=False)
    return 0


def main() -> None:
    p = argparse.ArgumentParser(description="LLM <-> MCP demo runner")
    p.add_argument(
        "question",
        nargs="?",
        default=None,
        help="user question (Korean ok); omit to start interactive chat",
    )
    p.add_argument(
        "--provider",
        default=os.getenv("LLM_PROVIDER", "stub"),
        help="azure-openai | openai | anthropic | stub (default: LLM_PROVIDER)",
    )
    p.add_argument(
        "--tool",
        default=None,
        help="stub provider only: which tool to call",
    )
    p.add_argument(
        "--chat",
        action="store_true",
        help="interactive chat loop (keep typing questions)",
    )
    p.add_argument(
        "--live",
        action="store_true",
        help="use the REAL portal over stdio (requires RUN_LIVE_LLM=1)",
    )
    raise SystemExit(asyncio.run(_main(p.parse_args())))


if __name__ == "__main__":
    main()

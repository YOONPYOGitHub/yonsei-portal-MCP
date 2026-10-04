"""Manual demo runner for the LLM <-> MCP harness.

This talks to the **real** MCP server over stdio, which logs in to the live
Yonsei portal and sends the resulting real data to the configured LLM. It is
therefore gated behind ``RUN_LIVE_LLM=1``.

Examples (from the project root, with `.env` filled in)::

    # Single question
    RUN_LIVE_LLM=1 uv run python -m tests.llm.demo "이번 학기 내 시간표 알려줘"

    # Force a provider for this run
    RUN_LIVE_LLM=1 uv run python -m tests.llm.demo --provider azure-openai "도서관 빈자리 있어?"

    # Interactive chat (keep typing questions; blank line or "exit" to quit)
    RUN_LIVE_LLM=1 uv run python -m tests.llm.demo --chat
    RUN_LIVE_LLM=1 uv run python -m tests.llm.demo            # (no question also starts chat)
"""
from __future__ import annotations

import argparse
import asyncio
import os

from .env import load_harness_env

load_harness_env()

from .mcp_host import run_agent, stdio_client_session
from .providers import ProviderUnavailable, make_provider


async def _main(args: argparse.Namespace) -> int:
    if os.getenv("RUN_LIVE_LLM") != "1":
        print("[demo] refusing live run: set RUN_LIVE_LLM=1 to confirm "
              "(real portal login + real data sent to the LLM)")
        return 3
    try:
        provider = make_provider(args.provider)
    except ProviderUnavailable:
        print("[demo] provider unavailable (details suppressed)")
        return 2

    chat = args.chat or not args.question
    if chat:
        return await _run_chat(args, provider)

    print(f"[demo] provider = {provider.name}")
    print(f"[demo] question = {args.question}")
    print("[demo] mode     = LIVE portal")
    print("-" * 60)

    async with stdio_client_session() as session:
        run = await run_agent(session, provider, args.question, max_turns=8)

    print("[demo] tools called:", run.called_tool_names or "(none)")
    print("-" * 60)
    print(run.final_text or "(no answer)")
    return 0


async def _chat_loop(session, provider) -> None:
    """Read questions from stdin and answer them, reusing one MCP session."""
    print(f"[demo] provider = {provider.name}")
    print("[demo] mode     = LIVE portal")
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
    async with stdio_client_session() as session:
        await _chat_loop(session, provider)
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
        default=os.getenv("LLM_PROVIDER"),
        help=(
            "azure-openai | openai | anthropic | gemini "
            "(default: LLM_PROVIDER)"
        ),
    )
    p.add_argument(
        "--chat",
        action="store_true",
        help="interactive chat loop (keep typing questions)",
    )
    raise SystemExit(asyncio.run(_main(p.parse_args())))


if __name__ == "__main__":
    main()

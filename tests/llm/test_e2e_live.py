"""L3 end-to-end test: real LLM + real Yonsei portal over stdio. Opt-in only.

This actually logs in to the portal and sends the resulting (real) data to the
configured external LLM. It is therefore gated behind ``RUN_LIVE_LLM=1`` AND a
configured provider, and is skipped by default.
"""
from __future__ import annotations

import os

import pytest

from .mcp_host import run_agent, stdio_client_session
from .providers import ProviderUnavailable, make_provider


@pytest.mark.live
@pytest.mark.llm
@pytest.mark.asyncio
async def test_live_end_to_end():
    if os.getenv("RUN_LIVE_LLM") != "1":
        pytest.skip("set RUN_LIVE_LLM=1 to run the live portal+LLM test")
    if (os.getenv("LLM_PROVIDER") or "stub").strip().lower() == "stub":
        pytest.skip("configure a real LLM_PROVIDER for the live test")
    try:
        provider = make_provider()
    except ProviderUnavailable as exc:
        pytest.skip(f"LLM provider unavailable: {exc}")

    async with stdio_client_session() as session:
        run = await run_agent(
            session, provider, "이번 학기 내 시간표를 알려줘.", max_turns=8
        )
    assert run.tool_calls, "expected the live model to call a tool"
    assert run.final_text, "expected a final answer from the live model"

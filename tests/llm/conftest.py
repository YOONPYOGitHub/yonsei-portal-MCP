"""Shared pytest fixtures for the LLM harness.

Loads ``.env`` (so AZURE_OPENAI_* etc. are visible), exposes an in-memory MCP
session with fixture tools, and a real-LLM ``provider`` fixture that skips
cleanly when no API key is configured.
"""
from __future__ import annotations

import os

import pytest

# Load the project .env early so provider config is available.
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

from .mcp_host import inmemory_client, run_agent  # noqa: E402
from .providers import ProviderUnavailable, StubProvider, make_provider  # noqa: E402


@pytest.fixture
def run_question():
    """Return an async helper that runs one question against fixture tools.

    The in-memory MCP session is opened and closed entirely inside the test's
    own task, which avoids the anyio "cancel scope in a different task" error
    that occurs when an async-generator fixture yields across the session.
    """

    async def _run(provider, question: str, **kwargs):
        async with inmemory_client(mock_tools=True) as session:
            return await run_agent(session, provider, question, **kwargs)

    return _run



@pytest.fixture
def stub_provider() -> StubProvider:
    return StubProvider()


@pytest.fixture
def provider():
    """A real provider selected via LLM_PROVIDER; skips if unconfigured.

    Force a provider for a run with e.g. ``LLM_PROVIDER=azure-openai``.
    """
    if (os.getenv("LLM_PROVIDER") or "stub").strip().lower() == "stub":
        pytest.skip("LLM_PROVIDER=stub (set a real provider to run L2 tests)")
    try:
        return make_provider()
    except ProviderUnavailable as exc:
        pytest.skip(f"LLM provider unavailable: {exc}")

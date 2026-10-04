"""Shared pytest fixtures for the LLM harness.

Loads legacy ``.env`` and, only with live opt-in, provider-only ``.env.llm``.
Exposes a real-LLM ``provider`` fixture that skips when unconfigured.
"""
from __future__ import annotations

import os

import pytest

# Load the project .env early so provider config is available.
from .env import load_harness_env

load_harness_env()

from .providers import ProviderUnavailable, make_provider  # noqa: E402


@pytest.fixture
def provider():
    """A real provider selected via LLM_PROVIDER; skips if unconfigured.

    Force a provider for a run with e.g. ``LLM_PROVIDER=azure-openai``.
    """
    if os.getenv("RUN_LIVE_LLM") != "1":
        pytest.skip("set RUN_LIVE_LLM=1 to construct a live LLM provider")
    try:
        return make_provider()
    except ProviderUnavailable:
        pytest.skip("LLM provider unavailable (details suppressed)")
    except Exception:
        pass
    pytest.fail("LLM provider initialization failed (details suppressed)", pytrace=False)

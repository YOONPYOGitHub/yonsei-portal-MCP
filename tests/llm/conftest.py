"""Shared pytest fixtures for the LLM harness.

Loads ``.env`` (so AZURE_OPENAI_* etc. are visible) and exposes a real-LLM
``provider`` fixture that skips cleanly when no API key is configured.
"""
from __future__ import annotations

import pytest

# Load the project .env early so provider config is available.
try:
    from dotenv import load_dotenv

    load_dotenv(override=True)
except ImportError:  # pragma: no cover
    pass

from .providers import ProviderUnavailable, make_provider  # noqa: E402


@pytest.fixture
def provider():
    """A real provider selected via LLM_PROVIDER; skips if unconfigured.

    Force a provider for a run with e.g. ``LLM_PROVIDER=azure-openai``.
    """
    try:
        return make_provider()
    except ProviderUnavailable as exc:
        pytest.skip(f"LLM provider unavailable: {exc}")

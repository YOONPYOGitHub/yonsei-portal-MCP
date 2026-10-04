"""Development-only split dotenv loader; never imported by the installed MCP.

Precedence is process environment > legacy .env > repository-root .env.llm,
including explicit empty values. Legacy .env discovery/interpolation is unchanged
(``load_dotenv(override=False)``), preserving existing provider configurations.

The optional .env.llm is read ONLY after RUN_LIVE_LLM is exactly "1" (the base
.env may enable it; process "0" wins). Its fixed path comes from this module's
__file__, never cwd or an upward dotenv search. Only LLM_PROVIDER_KEYS are copied;
school credentials, browser paths and RUN_LIVE_* flags are ignored. Interpolation
is disabled, so inherited secrets cannot be expanded into provider settings.

PYTHON_DOTENV_DISABLED values 1/true/t/yes/y (case-insensitive, as in python-dotenv)
return before dotenv imports or file discovery, including on older python-dotenv.
A disable flag loaded by the base .env also prevents subsequent .env.llm access.
No values or raw configuration errors are printed. Missing files are optional.
Provider selection remains in the existing adapters: --provider > LLM_PROVIDER;
azure-openai, openai, anthropic and gemini are unchanged.
"""
from __future__ import annotations

import os
from pathlib import Path


_TRUE_VALUES = frozenset({"1", "true", "t", "yes", "y"})
LLM_PROVIDER_KEYS = frozenset({
    "LLM_PROVIDER",
    "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_DEPLOYMENT", "AZURE_OPENAI_API_VERSION",
    "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_APIM_SUBSCRIPTION_KEY",
    "OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_BASE_URL",
    "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL",
    "GEMINI_API_KEY", "GEMINI_MODEL", "GEMINI_BASE_URL",
})


def load_harness_env() -> None:
    """Load base dotenv, then allowlisted live-LLM fallbacks, without override."""
    if os.getenv("PYTHON_DOTENV_DISABLED", "").lower() in _TRUE_VALUES:
        return
    try:
        from dotenv import dotenv_values, load_dotenv
    except ImportError:  # pragma: no cover
        return
    try:
        load_dotenv(override=False)
        if (
            os.getenv("RUN_LIVE_LLM") != "1"
            or os.getenv("PYTHON_DOTENV_DISABLED", "").lower() in _TRUE_VALUES
        ):
            return
        values = dotenv_values(
            Path(__file__).resolve().parents[2] / ".env.llm", interpolate=False,
        )
        for key, value in values.items():
            if key in LLM_PROVIDER_KEYS and value is not None:
                os.environ.setdefault(key, value)
    except (OSError, ValueError):
        raise RuntimeError("Harness environment loading failed (details suppressed)") from None

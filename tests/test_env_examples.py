"""Public configuration templates stay aligned with the split loader."""
from pathlib import Path
from dotenv import dotenv_values
from tests.llm.env import LLM_PROVIDER_KEYS

ROOT = Path(__file__).resolve().parents[1]


def test_llm_template_has_only_supported_provider_keys():
    values = dotenv_values(ROOT / ".env.llm.example", interpolate=False)
    assert set(values) == LLM_PROVIDER_KEYS
    assert values["LLM_PROVIDER"] in {"azure-openai", "openai", "anthropic", "gemini"}
    assert not any(key.startswith(("RUN_LIVE_", "YONSEI_")) for key in values)
    assert all(not values[key] for key in values if key.endswith(("API_KEY", "SUBSCRIPTION_KEY")))


def test_school_template_does_not_include_llm_credentials():
    values = dotenv_values(ROOT / ".env.example", interpolate=False)
    assert not set(values) & LLM_PROVIDER_KEYS
    assert values["RUN_LIVE_PORTAL"] == values["RUN_LIVE_LLM"] == "0"

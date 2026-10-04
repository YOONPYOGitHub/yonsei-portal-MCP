"""Public configuration templates stay aligned with the split loader."""
import ast
from pathlib import Path

import pytest
from dotenv import dotenv_values
from tests.llm.env import LLM_PROVIDER_KEYS

ROOT = Path(__file__).resolve().parents[1]


def _factory_env_keys(source: str) -> set[str]:
    """Inspect the factory's direct os.getenv calls, never import providers."""
    factory = next(
        node for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef) and node.name == "make_provider"
    )
    keys = set()
    for node in ast.walk(factory):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "os"
            and node.func.attr == "getenv"
        ):
            assert (
                node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ), "factory os.getenv must use a literal positional key"
            keys.add(node.args[0].value)
    return keys


def _assert_factory_env_contract(source, loader_keys, template_keys):
    factory_keys = _factory_env_keys(source)
    assert factory_keys == loader_keys, "factory/loader provider keys differ"
    assert factory_keys == template_keys, "factory/template provider keys differ"


def test_factory_env_key_collector_reads_literals_without_executing_source():
    source = '''
raise RuntimeError("source must not execute")
def unrelated():
    return os.getenv("OUTSIDE_FACTORY")
def make_provider():
    selected = os.getenv("LLM_PROVIDER")
    if selected:
        return os.getenv("API_KEY", ""), os.getenv("API_KEY")
'''
    assert _factory_env_keys(source) == {"LLM_PROVIDER", "API_KEY"}


@pytest.mark.parametrize("call", [
    "os.getenv(key)",
    'os.getenv("PREFIX_" + suffix)',
    "os.getenv(key=key)",
])
def test_factory_env_key_collector_rejects_dynamic_keys(call):
    with pytest.raises(AssertionError, match="literal positional key"):
        _factory_env_keys(f"def make_provider():\n    return {call}\n")


@pytest.mark.parametrize("target", ["factory", "loader", "template"])
@pytest.mark.parametrize("change", ["missing", "extra"])
def test_factory_env_contract_rejects_key_drift(target, change):
    keys = {name: {"LLM_PROVIDER", "API_KEY"} for name in ("factory", "loader", "template")}
    if change == "missing":
        keys[target].remove("API_KEY")
    else:
        keys[target].add("UNEXPECTED_KEY")
    source = "def make_provider():\n" + "\n".join(
        f"    os.getenv({key!r})" for key in sorted(keys["factory"])
    )
    with pytest.raises(AssertionError, match="loader|template"):
        _assert_factory_env_contract(source, keys["loader"], keys["template"])


def test_provider_factory_keys_match_loader_and_public_template():
    source = (ROOT / "tests" / "llm" / "providers.py").read_text(encoding="utf-8")
    template = dotenv_values(ROOT / ".env.llm.example", interpolate=False)
    _assert_factory_env_contract(source, LLM_PROVIDER_KEYS, set(template))


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

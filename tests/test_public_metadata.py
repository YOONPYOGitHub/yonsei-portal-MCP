"""Installed metadata must let public users identify licensing and dev setup."""
from importlib import metadata

from packaging.requirements import Requirement


def test_distribution_declares_machine_readable_mit_license():
    info = metadata.metadata("yonsei-portal-mcp")
    assert info["License-Expression"] == "MIT"
    assert any(value.endswith("LICENSE") for value in info.get_all("License-File", []))


def test_offline_dev_extra_does_not_require_llm_clients():
    requirements = [Requirement(raw) for raw in metadata.requires("yonsei-portal-mcp") or []]
    dev = {r.name for r in requirements if r.marker and r.marker.evaluate({"extra": "dev"})}
    assert {"pytest", "pytest-asyncio"} <= dev
    assert not {"openai", "anthropic"} & dev

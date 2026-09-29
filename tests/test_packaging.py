"""Offline distribution checks, reusable against a freshly installed wheel."""
import asyncio
import importlib
import os
import sys
from importlib import metadata, resources

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from packaging.requirements import Requirement
from packaging.version import Version


def test_distribution_requires_supported_mcp_sdk():
    requirements = [Requirement(value) for value in metadata.requires("yonsei-portal-mcp") or []]
    requirement = next(item for item in requirements if item.name == "mcp")
    assert requirement.specifier.contains("1.27.2")
    assert not requirement.specifier.contains("2.0.0")
    assert not requirement.specifier.contains("2.2.0")
    assert not requirement.specifier.contains("1.2.0")


def test_installed_sdk_satisfies_supported_range():
    assert Version("1.27.2") <= Version(metadata.version("mcp")) < Version("2")


def test_distribution_contains_modules_and_certificate(monkeypatch):
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    for module in ("academic", "boards", "erp", "learnus", "library", "seats"):
        importlib.import_module(f"yonsei_portal_mcp.scrapers.{module}")
    certificate = resources.files("yonsei_portal_mcp").joinpath("_certs", "sectigo_ov_intermediate.pem")
    assert certificate.is_file()
    assert "BEGIN CERTIFICATE" in certificate.read_text(encoding="ascii")
    entry_points = metadata.distribution("yonsei-portal-mcp").entry_points
    entry_point = next(item for item in entry_points if item.group == "console_scripts" and item.name == "yonsei-portal-mcp")
    assert entry_point.value == "yonsei_portal_mcp.__main__:main"


@pytest.mark.asyncio
async def test_distribution_starts_stdio_without_credentials(tmp_path):
    async def probe():
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-I", "-m", "yonsei_portal_mcp"],
            cwd=str(tmp_path),
            env={
                "HOME": str(tmp_path),
                "PYTHON_DOTENV_DISABLED": "1",
                "RUN_LIVE_PORTAL": "0",
                "RUN_LIVE_LLM": "0",
                "YONSEI_ID": "",
                "YONSEI_PASSWORD": "",
            },
        )
        with open(os.devnull, "w") as error_log:
            async with stdio_client(parameters, errlog=error_log) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    tools = (await session.list_tools()).tools
                    assert len(tools) == len({tool.name for tool in tools}) == 33
                    search = next(tool for tool in tools if tool.name == "search_library_books")
                    assert set(search.inputSchema["properties"]) == {"query", "page", "limit", "campus", "search_field", "offset"}
                    history = next(tool for tool in tools if tool.name == "get_my_loan_history")
                    assert not history.inputSchema.get("properties")
                    assert history.inputSchema["additionalProperties"] is False

    await asyncio.wait_for(probe(), timeout=30)
    assert not (tmp_path / ".session").exists()
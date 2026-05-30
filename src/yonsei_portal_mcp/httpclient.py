"""Shared httpx helper for the no-browser (hybrid) scraper path (DESIGN §10.2).

Some Yonsei endpoints (e.g. ``library.yonsei.ac.kr/seat/info``) serve their TLS
leaf certificate **without** the Sectigo intermediate, so a stock ``certifi``
bundle can't build the chain (browsers paper over this via AIA fetching). We
ship that one intermediate alongside the package and splice it into a verify
context so the lightweight path works on every platform.
"""
from __future__ import annotations

import ssl
from functools import lru_cache
from importlib import resources

import certifi
import httpx

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


@lru_cache(maxsize=1)
def _ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context(cafile=certifi.where())
    # Append the bundled Sectigo OV intermediate (missing from the server chain).
    pem = (
        resources.files("yonsei_portal_mcp")
        .joinpath("_certs", "sectigo_ov_intermediate.pem")
        .read_text(encoding="ascii")
    )
    ctx.load_verify_locations(cadata=pem)
    return ctx


async def get_json(url: str, *, params: dict | None = None, timeout: float = 15.0):
    """GET ``url`` and return parsed JSON, verifying TLS with the spliced chain."""
    headers = {"User-Agent": _USER_AGENT, "X-Requested-With": "XMLHttpRequest"}
    async with httpx.AsyncClient(
        verify=_ssl_context(), timeout=timeout, headers=headers
    ) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

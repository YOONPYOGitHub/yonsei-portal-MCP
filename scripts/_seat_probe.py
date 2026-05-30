"""Probe /seat/info with certifi + bundled Sectigo intermediate."""
import json
import ssl
from pathlib import Path

import certifi
import httpx

INTER = Path("src/yonsei_portal_mcp/_certs/sectigo_ov_intermediate.pem")
ctx = ssl.create_default_context(cafile=certifi.where())
ctx.load_verify_locations(cafile=str(INTER))

URL = "https://library.yonsei.ac.kr/seat/info"
with httpx.Client(verify=ctx, timeout=15.0) as c:
    r = c.get(URL, headers={"X-Requested-With": "XMLHttpRequest"})
    print("STATUS", r.status_code, r.headers.get("content-type"))
    data = r.json()
    print(json.dumps(data, ensure_ascii=False, indent=2)[:4000])
    if isinstance(data, dict):
        print("TOP KEYS:", list(data.keys()))

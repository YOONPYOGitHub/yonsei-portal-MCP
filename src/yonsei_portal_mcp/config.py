"""Configuration & credential loading.

Credentials are read from environment variables (loaded from a local .env that
is git-ignored). We never log or print the password.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=False)

PORTAL_URL = "https://portal.yonsei.ac.kr/"
LEARNUS_URL = "https://ys.learnus.org/"
LIBRARY_URL = "https://library.yonsei.ac.kr/"
LIBRARY_LOGIN_URL = "https://library.yonsei.ac.kr/login"
LIBRARY_SEAT_INFO_URL = "https://library.yonsei.ac.kr/seat/info"

# 학사행정(ERP) — WebSquare MDI. Visiting it redirects to the infra SSO form
# (with #loginId already present, unlike LearnUs which needs a btn-sso click).
ERP_URL = "https://underwood1.yonsei.ac.kr/"
ERP_PROFILE_URL = "https://underwood1.yonsei.ac.kr/com/cnst/PropCtr/findMyGLIOList.do"
ERP_GRADES_URL = (
    "https://underwood1.yonsei.ac.kr/sch/sgra/SgrargCtr/findAllGradeDtlAsSyySmtList.do"
)
ERP_TIMETABLE_TERMS_URL = (
    "https://underwood1.yonsei.ac.kr/sch/sles/SlesapCtr/findAccpsStdSchdlList.do"
)
ERP_ENROLLMENT_URL = (
    "https://underwood1.yonsei.ac.kr/sch/sles/SlesapCtr/findAccpcsStdList.do"
)


DEFAULT_NAV_TIMEOUT_MS = 30_000


@dataclass(frozen=True)
class Settings:
    yonsei_id: str
    yonsei_password: str
    headed: bool
    storage_state_path: Path
    nav_timeout_ms: int = DEFAULT_NAV_TIMEOUT_MS

    @property
    def has_credentials(self) -> bool:
        return bool(self.yonsei_id and self.yonsei_password)


def _read_id() -> str:
    # Support both the documented var names and the raw keys some users put in .env
    return (
        os.getenv("YONSEI_ID")
        or os.getenv("ID")
        or ""
    ).strip()


def _read_password() -> str:
    return (
        os.getenv("YONSEI_PASSWORD")
        or os.getenv("password")
        or os.getenv("PASSWORD")
        or ""
    ).strip()


def load_settings() -> Settings:
    # Default to headless for unattended MCP server use. Set YONSEI_HEADED=true
    # for the very first login or whenever 2FA / CAPTCHA must be solved manually.
    headed = os.getenv("YONSEI_HEADED", "false").lower() in {"1", "true", "yes"}
    # System-scoped session file (DESIGN §2.5): LearnUs and ERP get separate
    # cookie stores. Default is .session/learnus.json; legacy override honoured.
    storage = Path(os.getenv("YONSEI_STORAGE_STATE", ".session/learnus.json"))
    storage.parent.mkdir(parents=True, exist_ok=True)
    return Settings(
        yonsei_id=_read_id(),
        yonsei_password=_read_password(),
        headed=headed,
        storage_state_path=storage,
        nav_timeout_ms=_read_nav_timeout(),
    )


def _read_nav_timeout() -> int:
    raw = os.getenv("YONSEI_NAV_TIMEOUT_MS", "").strip()
    if not raw:
        return DEFAULT_NAV_TIMEOUT_MS
    try:
        value = int(raw)
        return value if value > 0 else DEFAULT_NAV_TIMEOUT_MS
    except ValueError:
        return DEFAULT_NAV_TIMEOUT_MS

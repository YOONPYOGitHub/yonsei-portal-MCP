"""Structured error types (DESIGN §2.5).

Every recoverable failure surfaces a stable ``code`` so the MCP client / LLM can
react deterministically instead of pattern-matching on free-form messages. The
string form is ``[CODE] message`` which FastMCP propagates as the tool error.
"""
from __future__ import annotations


class PortalError(Exception):
    """Base class for all portal failures carrying a stable error code."""

    code: str = "PORTAL_ERROR"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        if code:
            self.code = code
        self.message = message
        super().__init__(message)

    def __str__(self) -> str:  # surfaced verbatim by FastMCP
        return f"[{self.code}] {self.message}"

    def to_dict(self) -> dict:
        return {"error": {"code": self.code, "message": self.message}}


class AuthRequiredError(PortalError):
    """No usable credentials / session; interactive login required."""

    code = "AUTH_REQUIRED"


class AuthFailedError(PortalError):
    """Credentials were rejected by the SSO service."""

    code = "AUTH_FAILED"


class MFARequiredError(PortalError):
    """Login needs a second factor / CAPTCHA that cannot be solved headless."""

    code = "MFA_REQUIRED"


class SessionExpiredError(PortalError):
    """A previously valid session expired mid-flight; re-auth then retry."""

    code = "SESSION_EXPIRED"


class ScrapeFailedError(PortalError):
    """The page loaded but the expected data could not be extracted."""

    code = "SCRAPE_FAILED"


class UpstreamTimeoutError(PortalError):
    """An upstream Yonsei service did not respond within the nav timeout."""

    code = "UPSTREAM_TIMEOUT"

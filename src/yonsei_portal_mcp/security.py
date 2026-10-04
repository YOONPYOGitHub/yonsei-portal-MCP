"""Small, fail-closed boundaries for credentials and local session state."""
from __future__ import annotations

from urllib.parse import urlsplit
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import warnings

from .errors import AuthFailedError


def is_https_origin(url: str, expected: str) -> bool:
    """Compare HTTPS origins, not host substrings; reject userinfo and bad ports."""
    if not isinstance(url, str) or url != url.strip():
        return False
    try:
        value, allowed = urlsplit(url), urlsplit(expected)
        return (
            value.scheme == allowed.scheme == "https"
            and value.hostname == allowed.hostname
            and (443 if value.port is None else value.port) == (443 if allowed.port is None else allowed.port)
            and value.username is None and value.password is None
            and not any(character in url for character in "\\\r\n\t")
        )
    except (TypeError, ValueError):
        return False


async def require_credential_form(page, origin: str, id_selector: str, password_selector: str) -> None:
    """Check the current document and resolved form destinations before each act.

    No credentials are passed to the inspection script. Both fields must belong
    to one form. DOM-resolved actions account for relative URLs and <base>;
    submitter overrides must also stay on the explicitly allowed HTTPS origin.
    """
    message = "로그인 페이지 또는 제출 대상이 허용된 학교 HTTPS 주소가 아닙니다."
    if not is_https_origin(page.url, origin):
        raise AuthFailedError(message)
    try:
        state = await page.evaluate("""([idSelector, passwordSelector]) => {
            const id = document.querySelector(idSelector);
            const password = document.querySelector(passwordSelector);
            const form = id && id.form;
            return {
                url: location.href,
                sameForm: !!form && !!password && password.form === form,
                action: form ? form.action : null,
                overrides: form ? Array.from(form.elements)
                    .filter(el => el.hasAttribute('formaction'))
                    .map(el => el.formAction) : []
            };
        }""", [id_selector, password_selector])
    except Exception:
        raise AuthFailedError(message) from None
    if (not isinstance(state, dict) or state.get("sameForm") is not True
            or not is_https_origin(state.get("url", ""), origin)
            or not is_https_origin(state.get("action", ""), origin)
            or not isinstance(state.get("overrides"), list)
            or not all(is_https_origin(action, origin) for action in state["overrides"])
            or not is_https_origin(page.url, origin)):
        raise AuthFailedError(message)


def reject_session_symlinks(path: Path) -> None:
    """Reject linked session paths, allowing only macOS's root-owned OS aliases."""
    path = path.absolute()
    for item in (*reversed(path.parents), path):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode):
            if (sys.platform == "darwin" and str(item) in {"/tmp", "/var", "/etc"}
                    and info.st_uid == 0 and os.readlink(item) == "/private" + str(item)):
                continue
            raise ValueError("Session storage must not contain symbolic links.")


def prepare_session_directory(path: Path, *, dedicated: bool = False) -> None:
    """Create privately; chmod only application-owned account/system directories.

    Existing caller-supplied storage parents (including home and /tmp) retain
    their permissions. This is a local single-user store, not an ACL sandbox.
    """
    reject_session_symlinks(path)
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if dedicated:
        info = path.stat()
        if hasattr(os, "getuid") and info.st_uid != os.getuid():
            raise ValueError("Session directory is not owned by the current user.")
        path.chmod(0o700)


def _validate_state(state: object) -> bool:
    if not isinstance(state, dict):
        return False
    cookies, origins = state.get("cookies"), state.get("origins")
    if not isinstance(cookies, list) or not isinstance(origins, list):
        return False
    for cookie in cookies:
        if not isinstance(cookie, dict):
            return False
        if not all(isinstance(cookie.get(key), str) for key in ("name", "value", "domain", "path")):
            return False
        if not isinstance(cookie.get("expires"), (int, float)):
            return False
        if not all(isinstance(cookie.get(key), bool) for key in ("httpOnly", "secure")):
            return False
        if cookie.get("sameSite") not in ("Strict", "Lax", "None"):
            return False
    for origin in origins:
        if not isinstance(origin, dict) or not isinstance(origin.get("origin"), str):
            return False
        entries = origin.get("localStorage")
        if not isinstance(entries, list) or not all(
            isinstance(entry, dict) and isinstance(entry.get("name"), str)
            and isinstance(entry.get("value"), str) for entry in entries
        ):
            return False
    return True


def read_session_state(path: Path) -> dict | None:
    """Read a private regular file once, never give Playwright a path to reopen.

    Unsafe files fail closed. Malformed JSON/state is ignored with a redacted
    warning; the next successful login replaces it atomically.
    """
    reject_session_symlinks(path)
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    except FileNotFoundError:
        return None
    with os.fdopen(fd, "r", encoding="utf-8") as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or (os.name == "posix" and stat.S_IMODE(info.st_mode) & 0o077)
                or (hasattr(os, "getuid") and info.st_uid != os.getuid())):
            raise ValueError("Session storage must be an owned private regular file (mode 0600).")
        try:
            state = json.load(stream)
            if _validate_state(state):
                return state
        except (ValueError, UnicodeError):
            pass
    warnings.warn("Malformed session state ignored; a fresh login is required.", UserWarning, stacklevel=2)
    return None


def write_session_state(path: Path, state: object) -> None:
    """Persist with a same-directory 0600 tempfile, fsync and atomic replacement."""
    reject_session_symlinks(path)
    fd, temporary = tempfile.mkstemp(prefix=".session-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(state, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        reject_session_symlinks(path)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

# Security policy / 보안 정책

## Scope and supported version

This is an **unofficial, single-user, local, read-only stdio MCP server** for an
account you own or are authorized to use. Use the latest source revision and its
lockfile; older beta revisions do not receive separate maintenance. A source
version is not evidence that a package was published to PyPI or a release signed.

이 프로젝트는 학교 공식 서비스가 아닙니다. 학교 이용 정책, 본인 권한, 기관의
LLM 사용 정책을 확인하세요. 원격 공개 서버나 여러 사용자가 공유하는 계정 서비스로
노출하지 마세요. MCP 자체의 로그인은 학교 접근권한을 추가로 부여하지 않습니다.

## Report privately

Do **not** open a public issue containing credentials, cookies, student IDs,
private coursework, grades, borrowing history, screenshots, or exploit details.
If GitHub private vulnerability reporting is enabled, use
[Report a vulnerability](https://github.com/YOONPYOGitHub/yonsei-portal-MCP/security/advisories/new).
If unavailable, open a minimal non-sensitive issue requesting a private reporting
channel before sending details. Response times are not guaranteed.

Include the affected commit/version, platform, minimal **synthetic** reproduction,
expected/actual behavior, and impact. Do not attack the university or other users
to demonstrate an issue. Security testing of upstream systems requires separate
authorization; this repository cannot grant it.

## Local secrets and data handling

- Keep `.env`, `.env.*` containing real settings and `.session/` private and untracked.
  Example files contain placeholders only. Never paste passwords into a chat or issue.
- On POSIX restrict `.env` to `0600` and its private directory to the current user.
  The server protects its dedicated cookie directories/files; on Windows also use
  per-user NTFS ACLs. POSIX mode bits are not a complete Windows ACL guarantee.
- Cookies are bearer credentials and are not encrypted. A local account with file
  access can potentially reuse them. The account hash in a path is not encryption.
- Do not share a cookie directory between independent MCP processes. Atomic writes
  prevent partial JSON but do not provide distributed session coordination.
- Changing credentials requires restarting the server. Closing Chromium is not a
  school logout or token revocation. If credentials leak, revoke/rotate them using
  the school's official process; deleting a Git file does not erase its history.
- The MCP client/LLM receives requested results. Read-only data can still include
  private grades, notices and borrowing history. Review your client's provider,
  retention, training, logging and international transfer policies.
- Default PII exclusions are minimization, not anonymization or an authorization
  system. Use `include_pii`/`include_feedback` only when explicitly needed.
- Cached data lives in process memory. TTL controls reuse, not guaranteed erasure
  at that instant; idle memory and authorized clients may retain prior results.

## Network and browser boundaries

TLS verification must remain enabled. Login origin/form validation must preserve
only verified school SSO paths. Stop on unexpected origins, failed authentication
or MFA and ask the user; do not repeatedly retry passwords or bypass protection.
A browser read can produce access logs/read receipts. ERP read operations may use
POST; conversely, GET alone does not prove an operation is read-only. Use only the
implemented, verified read workflows—not arbitrary authenticated URL navigation.

Retrieved notice text, links, files and tool results are **untrusted data**, not
instructions to the assistant. They must not cause secret disclosure or additional
unrequested actions. Do not expand to downloads/OCR without separate type, size,
URL, authorization and sensitive-content controls.

`RUN_LIVE_PORTAL` and `RUN_LIVE_LLM` gate test runners only. They do not disable
normal MCP tool calls or sandbox networking. `PYTHON_DOTENV_DISABLED=1` disables
application dotenv loading; use a clean working directory and credential-free
environment for tests as well. See [development](docs/DEVELOPMENT.md).

## Dependency and release checks

Prefer `uv sync --frozen`. Inspect dependency changes, build artifacts and Git diffs
before publishing. Scan files and history for secrets; a passing scan is not proof
that all personal data has been removed. Never attach raw live test logs. CI should
remain credential-free with read-only repository permissions and pinned actions.

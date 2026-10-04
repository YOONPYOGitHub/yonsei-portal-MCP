# Contributing / 기여 안내

Contributions are welcome for authorized, **read-only** use. Read
[README](README.md), [tool contracts](docs/TOOLS.md), [design](DESIGN.md), and
[security policy](SECURITY.md) first. This project is not affiliated with Yonsei
University and does not grant permission to scrape accounts or redistribute
university materials.

## Development setup

Python 3.10+ and [uv](https://docs.astral.sh/uv/) are required. From your clone:

```bash
uv sync --frozen --extra dev
# Avoid removing Playwright revisions used by other local projects.
PLAYWRIGHT_SKIP_BROWSER_GC=1 uv run --no-sync playwright install chromium
```

On PowerShell set `$env:PLAYWRIGHT_SKIP_BROWSER_GC = "1"` before installation.
Windows file protection also requires private per-user ACLs.

The `dev` extra does not install OpenAI/Anthropic clients. For optional provider
adapter tests/demos use `--extra llm`; API keys are not required for offline tests.
Do not overwrite an existing `.env` from an example.

## Testing and changes

1. Create a topic branch from current main.
2. Write a failing regression test using synthetic, non-identifying data.
3. Run it and verify the intended failure, then make the smallest fix.
4. Run related tests, then the full offline suite and packaging checks described in
   [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md). Do not run all `smoke*.py` scripts.
5. Update tool contracts, README/setup examples and CHANGELOG for user-visible changes.
6. Review `git diff --check`, staged files and a secret scan. Open a focused PR with
   commands/results and clear statements of what was **not** verified.

Keep unknown inputs, authentication failures, parser errors, partial results and
verified empty results distinct. Maintain exact identifiers, source URLs, timezones,
pagination coverage and privacy defaults. Do not make mock success stand in for a
real site check. Browser tests must intercept fixture traffic and avoid live school
services unless explicitly authorized.

Real-portal tests use only your authorized account and explicit live gates. Real-LLM
tests additionally transfer data to the selected provider and can incur charges.
Never store raw live results, cookies or personally identifying fixtures in a PR.

## Public API and compatibility

This is beta software. Keep tool names/normal inputs stable where possible, but
reject unsafe or unsupported inputs rather than silently broadening a query. Document
stricter validation and response-field changes so clients can refresh `tools/list`.
Changes to SSO allowlists require observed school origins and synthetic rejection
tests; never disable TLS or origin checks to make a test pass.

Do not add submission, enrollment, payment, reservation, cancellation or loan-renewal
behavior under the read-only label. Propose scope changes separately. Avoid dependency
upgrades, large formatting churn or unrelated refactors in a bugfix.

## License

By contributing, you represent that you may contribute the material under the
repository's [MIT license](LICENSE). Preserve existing authorship and license notices.
Do not add third-party code or university content unless its redistribution rights
are established. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

"""Small CI/documentation contracts: no runtime configuration imports."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_ci_runs_pinned_static_error_checks_without_reformatting():
    source = (ROOT / '.github/workflows/ci.yml').read_text(encoding='utf-8')
    assert 'ruff==0.14.1' in source
    assert 'ruff check --no-cache src tests --select E9,F63,F7,F82' in source
    assert 'ruff check --fix' not in source


def test_live_marker_distinguishes_portal_and_llm_gates():
    source = (ROOT / 'pyproject.toml').read_text(encoding='utf-8')
    line = next(line for line in source.splitlines() if '"live:' in line)
    assert 'RUN_LIVE_PORTAL=1' in line
    assert 'RUN_LIVE_LLM=1' in line
    assert 'AND a real LLM' not in line

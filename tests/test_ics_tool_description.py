"""ICS tool metadata should prevent misleading client-side explanations."""
import ast
from pathlib import Path


def test_calendar_export_description_states_actual_output_boundaries():
    source = Path(__file__).resolve().parents[1] / 'src/yonsei_portal_mcp/server.py'
    node = next(n for n in ast.parse(source.read_text(encoding='utf-8')).body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'export_calendar_ics')
    description = ast.get_docstring(node)
    assert description is not None
    for term in ('progress', 'completion', 'UTC', 'DTEND', 'DURATION', '일회성', '자동 동기화', 'course_id'):
        assert term in description
    assert '바로 구독' not in description
    assert '반납일에는 적용되지' in description

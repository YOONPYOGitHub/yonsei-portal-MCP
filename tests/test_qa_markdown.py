"""The readable catalog must not drift from the executable question source."""
import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]


def sources():
    cases = [json.loads(line) for line in (ROOT / 'docs/evaluation/questions.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    return cases, (ROOT / 'docs/evaluation/QUESTIONS.md').read_text(encoding='utf-8')


def test_public_markdown_matches_question_contract():
    from tests.qa.catalog import validate_markdown
    cases, text = sources()
    assert validate_markdown(cases, text) == {'questions': len(cases)}


@pytest.mark.parametrize('field', ['question', 'expected_behavior', 'expected_tools', 'evaluation_mode', 'privacy', 'link', 'missing', 'duplicate', 'total', 'category_total'])
def test_drift_is_rejected(field):
    from tests.qa.catalog import validate_markdown
    cases, text = sources()
    if field == 'question':
        cases[0]['question'] += ' 다른 의미'
    elif field == 'expected_behavior':
        cases[0][field].append('추가 확인 기준')
    elif field == 'expected_tools':
        cases[0][field] = ['get_notice']
    elif field == 'evaluation_mode':
        cases[0][field] = 'refusal'
    elif field == 'privacy':
        cases[0][field] = 'public'
    elif field == 'link':
        text = text.replace('(questions.jsonl#L1)', '(questions.jsonl#L2)', 1)
    elif field == 'missing':
        text = text.replace('#### [get_lms_courses.basic]', '### [get_lms_courses.basic]', 1)
    elif field == 'duplicate':
        text += '\n#### [get_lms_courses.basic](questions.jsonl#L1)\n'
    elif field == 'total':
        text = text.replace('총 152개', '총 153개', 1)
    else:
        text = text.replace('| 15 | 15 | 60 |', '| 15 | 15 | 61 |', 1)
    with pytest.raises(ValueError, match='Markdown'):
        validate_markdown(cases, text)

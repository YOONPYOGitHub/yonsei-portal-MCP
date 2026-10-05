"""Conditional search continuation must retain the response that permits it."""
import json
from pathlib import Path


def test_search_followup_can_cite_search_and_page_evidence():
    path = Path(__file__).resolve().parents[1] / 'docs/evaluation/questions.jsonl'
    case = next(json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if json.loads(line)['id'] == 'search_lms_board_posts.followup')
    assert case['expected_tools'] == ['search_lms_board_posts', 'get_lms_board_posts']

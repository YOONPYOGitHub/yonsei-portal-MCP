"""Natural dialogue packets contain user text, never grading hints."""
import copy
import json
from pathlib import Path
import pytest


def sample():
    prompts = [{'id': f'human.c01.t{i:02}', 'conversation_id': 'human.c01', 'turn': i, 'user': text} for i, text in enumerate(['이번주 뭐 있지', '수업 말야', '그중에 내일꺼만', '그럼 됐어'], 1)]
    rubric = [{'id': p['id'], 'allowed_outcomes': ['answer', 'clarification'], 'criteria': ['문맥과 근거 확인'], 'forbidden': ['추측한 데이터']} for p in prompts]
    return prompts, rubric


def test_packet_has_no_gold_or_future_turns():
    from tests.qa.natural import validate_dialogues, turn_packet
    prompts, rubric = sample()
    assert validate_dialogues(prompts, rubric) == {'conversations': 1, 'turns': 4}
    packet = turn_packet(prompts[0], '연세대 본인 계정의 읽기 전용 조회')
    assert packet == {'id': 'human.c01.t01', 'conversation_id': 'human.c01', 'turn': 1, 'user': '이번주 뭐 있지', 'context': '연세대 본인 계정의 읽기 전용 조회'}
    assert 'criteria' not in json.dumps(packet) and prompts[1]['user'] not in json.dumps(packet, ensure_ascii=False)


@pytest.mark.parametrize('kind', ['duplicate', 'order', 'hidden_hint', 'empty', 'rubric_id', 'outcome'])
def test_bad_dialogues_are_rejected(kind):
    from tests.qa.natural import validate_dialogues
    prompts, rubric = sample()
    if kind == 'duplicate': prompts[1] = copy.deepcopy(prompts[0])
    elif kind == 'order': prompts[0], prompts[1] = prompts[1], prompts[0]
    elif kind == 'hidden_hint': prompts[0]['expected_tools'] = ['get_my_schedule']
    elif kind == 'empty': prompts[0]['user'] = ' '
    elif kind == 'rubric_id': rubric[0]['id'] = 'human.c99.t01'
    else: rubric[0]['allowed_outcomes'] = ['invent_success']
    with pytest.raises(ValueError): validate_dialogues(prompts, rubric)


def test_packet_rejects_gold_fields_instead_of_silently_stripping():
    from tests.qa.natural import turn_packet
    prompts, _ = sample()
    prompts[0]['criteria'] = ['hidden']
    with pytest.raises(ValueError): turn_packet(prompts[0], 'context')


def test_readable_dialogues_reject_question_drift():
    from tests.qa.natural import validate_readable_dialogues
    prompts, _ = sample()
    text = '## 대화 01\n\n' + '\n'.join(f"{p['turn']}. {p['user']}" for p in prompts)
    assert validate_readable_dialogues(prompts, text) == {'turns': 4}
    with pytest.raises(ValueError):
        validate_readable_dialogues(prompts, text.replace('이번주 뭐 있지', '다른 질문'))


def test_public_natural_dataset():
    from tests.qa.natural import validate_dialogues
    folder = Path(__file__).resolve().parents[1] / 'docs/evaluation/natural'
    prompts = [json.loads(l) for l in (folder/'prompts.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
    rubric = [json.loads(l) for l in (folder/'rubric.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
    assert validate_dialogues(prompts, rubric) == {'conversations': 10, 'turns': 40}
    from tests.qa.natural import validate_readable_dialogues
    assert validate_readable_dialogues(prompts, (folder/'QUESTIONS.md').read_text(encoding='utf-8')) == {'turns': 40}

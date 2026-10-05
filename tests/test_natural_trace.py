"""Trace completeness is distinct from semantic grading and remote authenticity."""
import pytest
from tests.test_natural_dialogues import sample


def fixture():
    prompts, _ = sample()
    turns = {p['id']: {**p, 'assistant': '확인이 필요합니다.', 'status': 'needs_clarification', 'call_ids': [], 'evidence': []} for p in prompts}
    audit = [event for p in prompts for event in [{'event':'packet_opened','qid':p['id']}, {'event':'turn_answered','qid':p['id']}]]
    return prompts, turns, {}, {}, audit


def test_complete_trace_without_calls_is_not_faked_tool_success():
    from tests.qa.natural import validate_trace
    result = validate_trace(*fixture())
    assert result == {'turns': 4, 'calls': 0, 'referenced_calls': 0, 'unreferenced_calls': 0}


@pytest.mark.parametrize('kind', ['missing', 'question_changed', 'status', 'future_peek', 'overlap', 'foreign_evidence', 'wrong_hash'])
def test_invalid_trace_is_rejected(kind):
    from tests.qa.natural import validate_trace
    prompts, turns, calls, hashes, audit = fixture()
    first = prompts[0]['id']
    if kind == 'missing': turns.pop(first)
    elif kind == 'question_changed': turns[first]['user'] = '다른 질문'
    elif kind == 'status': turns[first]['status'] = 'invented_success'
    elif kind == 'future_peek': audit[1], audit[2] = audit[2], audit[1]
    else:
        cid = first + '.call01'
        calls[cid] = {'qid': first}
        hashes[cid] = 'a'*64
        turns[first]['call_ids'] = [cid]
        turns[first]['evidence'] = [{'call_id': cid, 'sha256': 'a'*64}]
        audit[1:1] = [{'event':'call_started','qid':first,'call_id':cid}, {'event':'call_finished','qid':first,'call_id':cid}]
        if kind == 'overlap': audit.insert(2, {'event':'call_started','qid':first,'call_id':cid})
        elif kind == 'foreign_evidence':
            other = 'human.c02.t01.call01'
            calls[other] = calls.pop(cid); hashes[other] = hashes.pop(cid)
            turns[first]['call_ids'] = [other]; turns[first]['evidence'][0]['call_id'] = other
            for event in audit:
                if event.get('call_id') == cid: event['call_id'] = other
        else: turns[first]['evidence'][0]['sha256'] = 'b'*64
    with pytest.raises(ValueError): validate_trace(prompts, turns, calls, hashes, audit)

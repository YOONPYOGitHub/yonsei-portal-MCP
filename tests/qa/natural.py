"""Offline validation and single-turn packets for rubric-separated dialogues."""
from collections import Counter
import re

PROMPT_FIELDS = {'id', 'conversation_id', 'turn', 'user'}
RUBRIC_FIELDS = {'id', 'allowed_outcomes', 'criteria', 'forbidden'}
OUTCOMES = {'answer', 'clarification', 'refusal', 'conditional_blocked'}


def _prompt(prompt):
    if not isinstance(prompt, dict) or set(prompt) != PROMPT_FIELDS:
        raise ValueError('Natural prompt must not include grading hints')
    cid, turn = prompt['conversation_id'], prompt['turn']
    if (not isinstance(cid, str) or not re.fullmatch(r'human\.c[0-9]{2}', cid)
            or type(turn) is not int or not 1 <= turn <= 4
            or prompt['id'] != f'{cid}.t{turn:02}'
            or not isinstance(prompt['user'], str) or not prompt['user'].strip()):
        raise ValueError('Invalid natural prompt identity or text')


def turn_packet(prompt, context):
    """Deliver only this user turn and neutral context, not future turns/gold."""
    _prompt(prompt)
    if not isinstance(context, str) or not context.strip():
        raise ValueError('Missing neutral conversation context')
    return {**prompt, 'context': context}


def validate_dialogues(prompts, rubric):
    if not isinstance(prompts, list) or not prompts or not isinstance(rubric, list):
        raise ValueError('Invalid dialogue lists')
    seen, progress = set(), Counter()
    for prompt in prompts:
        _prompt(prompt)
        cid, turn, qid = prompt['conversation_id'], prompt['turn'], prompt['id']
        if qid in seen or turn != progress[cid] + 1:
            raise ValueError('Duplicate or out-of-order dialogue turn')
        seen.add(qid)
        progress[cid] = turn
    if any(value != 4 for value in progress.values()):
        raise ValueError('Incomplete four-turn dialogue')
    golden = set()
    for row in rubric:
        if not isinstance(row, dict) or set(row) != RUBRIC_FIELDS:
            raise ValueError('Invalid rubric schema')
        if row['id'] not in seen or row['id'] in golden:
            raise ValueError('Rubric identity mismatch')
        for field in ('allowed_outcomes', 'criteria', 'forbidden'):
            values = row[field]
            if not isinstance(values, list) or not values or any(not isinstance(v, str) or not v.strip() for v in values):
                raise ValueError('Missing rubric criteria')
        if not set(row['allowed_outcomes']) <= OUTCOMES:
            raise ValueError('Unknown rubric outcome')
        golden.add(row['id'])
    if seen != golden:
        raise ValueError('Rubric coverage mismatch')
    return {'conversations': len(progress), 'turns': len(prompts)}


def validate_readable_dialogues(prompts, text):
    """Require the readable conversation order and utterances to match JSONL."""
    headings = list(re.finditer(r'^## 대화 ([0-9]{2})\s*$', text, re.MULTILINE))
    actual = []
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        for turn, user in re.findall(r'^([1-4])\. (.+)$', text[heading.end():end], re.MULTILINE):
            actual.append({'id': f'human.c{heading[1]}.t{int(turn):02}', 'conversation_id': f'human.c{heading[1]}', 'turn': int(turn), 'user': user})
    if actual != prompts or len(headings) != len({p['conversation_id'] for p in prompts}):
        raise ValueError('Readable natural questions differ from JSONL')
    return {'turns': len(actual)}


def validate_trace(prompts, turns, calls, call_hashes, audit):
    """Check complete dialogue references and observed gateway order, not truth."""
    def fail():
        raise ValueError('Natural dialogue trace is inconsistent')

    expected = {p['id']: p for p in prompts}
    if len(expected) != len(prompts) or set(turns) != set(expected) or set(calls) != set(call_hashes):
        fail()
    referenced = set()
    for qid, row in turns.items():
        prompt = expected[qid]
        if any(row.get(key) != value for key, value in prompt.items()):
            fail()
        if row.get('status') not in {'answered', 'needs_clarification', 'refused', 'blocked', 'tool_error'}:
            fail()
        if not isinstance(row.get('assistant'), str) or not row['assistant'].strip():
            fail()
        refs = row.get('call_ids')
        if not isinstance(refs, list) or len(set(refs)) != len(refs):
            fail()
        evidence = []
        for cid in refs:
            if cid not in calls:
                fail()
            origin = calls[cid].get('qid')
            if origin not in expected or expected[origin]['conversation_id'] != prompt['conversation_id'] or expected[origin]['turn'] > prompt['turn']:
                fail()
            if not cid.startswith(origin + '.call'):
                fail()
            evidence.append({'call_id': cid, 'sha256': call_hashes[cid]})
            referenced.add(cid)
        if row.get('evidence') != evidence:
            fail()
    opened, completed, started, finished = set(), set(), set(), set()
    active = None
    for event in audit:
        qid, kind = event.get('qid'), event.get('event')
        if qid not in expected:
            fail()
        prompt = expected[qid]
        if kind == 'packet_opened':
            prior = f"{prompt['conversation_id']}.t{prompt['turn'] - 1:02}"
            if qid in completed or prompt['turn'] > 1 and prior not in completed:
                fail()
            opened.add(qid)
        elif kind == 'call_started':
            cid = event.get('call_id')
            if active is not None or qid not in opened or qid in completed or cid in started or cid not in calls or calls[cid].get('qid') != qid:
                fail()
            active = cid
            started.add(cid)
        elif kind == 'call_finished':
            if active is None or event.get('call_id') != active or calls[active].get('qid') != qid:
                fail()
            finished.add(active)
            active = None
        elif kind == 'turn_answered':
            if qid not in opened or qid in completed or active is not None:
                fail()
            completed.add(qid)
        else:
            fail()
    if completed != set(expected) or started != set(calls) or finished != started or active is not None:
        fail()
    return {'turns': len(turns), 'calls': len(calls), 'referenced_calls': len(referenced), 'unreferenced_calls': len(calls) - len(referenced)}

"""QA-3 eval layer over the committed golden transcripts (no live model):

1. PERSONA FORMAT — every spoken/final-reply text in a transcript obeys the
   voice contract: <= voice_personality.spoken_reply_max_sentences
   sentences, NO markdown, none of the `banned` phrases, no model
   self-announcement (REQUIREMENTS addendum §10 / config voice_personality).
2. TOOL-CALL ACCURACY — the recorded act_req matches the scenario's intent
   oracle exactly (action + args), and non-tool scenarios contain NO act_req.
3. ANSWER SHAPE — `answer` frames carry format='answer' and non-empty text
   (PROTOCOL §3).

Eval reads GOLDEN files only — pure fixture assertions, ms-fast (Rule 15).
"""
import json
import re
from pathlib import Path

import pytest
import yaml

from golden.scenarios import SCENARIO_META

GOLDEN_DIR = Path(__file__).parent / 'transcripts'
CONFIG = yaml.safe_load(Path('config.yaml').read_text(encoding='utf-8'))
VP = CONFIG['voice_personality']
MAX_SENT = int(VP.get('spoken_reply_max_sentences', 2))
BANNED = [b.lower() for b in VP.get('banned', [])]

MD_MARKERS = ('**', '```', '`', '[[', '](')
MD_LIST = re.compile(r'(?m)^\s*[-*]\s+')
SELF_ANNOUNCE = ('language model', 'ai assistant', 'as an ai', 'chatgpt')


def _load(name):
    return json.loads((GOLDEN_DIR / f'{name}.jsonl').read_text(
        encoding='utf-8'))


def _spoken_texts(doc):
    """Texts the USER HEARS or READS as the reply (speak + answer)."""
    out = []
    for label, sess in doc['sessions'].items():
        for f in sess['recv']:
            if f.get('type') == 'speak' and f.get('event') == 'start':
                out.append((label, 'speak', f.get('text', '')))
            elif f.get('type') == 'answer':
                out.append((label, 'answer', f.get('text', '')))
    return out


def _sentences(text):
    parts = [p.strip() for p in re.split(r'(?<=[.!?])\s+', text.strip())
             if p.strip()]
    return parts or ([text.strip()] if text.strip() else [])


@pytest.mark.parametrize('name', sorted(SCENARIO_META))
def test_persona_format_eval(name):
    doc = _load(name)
    texts = _spoken_texts(doc)
    assert texts, f'{name}: no spoken/answer texts recorded'
    for label, kind, text in texts:
        assert text, f'{name}/{label}: empty {kind} text'
        n = len(_sentences(text))
        assert n <= MAX_SENT, (
            f'{name}/{label}: {kind} text has {n} sentences '
            f'(> {MAX_SENT}): {text!r}')
        for marker in MD_MARKERS:
            assert marker not in text, \
                f'{name}/{label}: markdown {marker!r} in {kind}: {text!r}'
        assert not MD_LIST.search(text), \
            f'{name}/{label}: markdown list in {kind}: {text!r}'
        low = text.lower()
        for banned in BANNED:
            assert banned not in low, \
                f'{name}/{label}: banned phrase {banned!r} in {kind}: {text!r}'
        for announce in SELF_ANNOUNCE:
            assert announce not in low, \
                f'{name}/{label}: self-announcement {announce!r} in {kind}'


@pytest.mark.parametrize('name', sorted(SCENARIO_META))
def test_tool_call_accuracy_eval(name):
    meta = SCENARIO_META[name]
    doc = _load(name)
    act_reqs = [f for _, sess in doc['sessions'].items()
                for f in sess['recv'] if f.get('type') == 'act_req']
    if meta['tool'] is None:
        assert act_reqs == [], \
            f'{name}: unexpected act_req(s): {act_reqs}'
        return
    assert len(act_reqs) == 1, f'{name}: expected 1 act_req, got {act_reqs}'
    req = act_reqs[0]
    assert req['action'] == meta['tool'], req
    assert req['args'] == meta['tool_args'], req
    assert isinstance(req['lock'], bool) and 'timeout_ms' in req


@pytest.mark.parametrize('name', sorted(SCENARIO_META))
def test_answer_frame_shape_eval(name):
    meta = SCENARIO_META[name]
    doc = _load(name)
    answers = [f for _, sess in doc['sessions'].items()
               for f in sess['recv'] if f.get('type') == 'answer']
    if not meta.get('expect_answer', True):
        # a denied/cancelled job speaks "Aborted." — it is NOT a final reply
        # and PROTOCOL §3's answer frame must NOT be emitted for it
        assert answers == [], f'{name}: cancelled job emitted answer {answers}'
        return
    assert answers, f'{name}: no answer frame recorded'
    for a in answers:
        assert a['format'] == 'answer', a
        assert a['text'], a
        assert a.get('job', '').startswith('j_') or a.get('job') is None, a


@pytest.mark.parametrize('name', sorted(SCENARIO_META))
def test_confirm_gate_eval(name):
    meta = SCENARIO_META[name]
    doc = _load(name)
    confirms = [f for _, sess in doc['sessions'].items()
                for f in sess['recv'] if f.get('type') == 'needs_confirm']
    if meta['expect_confirm']:
        # the question is broadcast to BOTH ui and cli -> >=1 frames
        assert len(confirms) >= 1, f'{name}: needs_confirm never recorded'
        assert all(c.get('actions') == ['yes', 'no'] for c in confirms), \
            confirms
    else:
        assert confirms == [], f'{name}: unexpected needs_confirm {confirms}'

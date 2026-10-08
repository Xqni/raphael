"""QA-4 machine-check: wave_done lint (packet docs/audit-tasks/qa-security.md
lines 7-8 — wave_done without a CI run id gets bounced)."""
import json
from pathlib import Path

import pytest

import wave_done_lint as lint


@pytest.mark.parametrize('msg,ok_kind', [
    ('Wave 5 DONE — https://github.com/<gh-owner>/raphael/actions/runs/37714371665',
     'ci-run-url'),
    ('wave done, see run 37714092239', 'ci-run-id'),
    ('wave done (runs/37714092239)', 'ci-run-id'),
    ('local closure sha256:' + 'ab' * 32, 'output-sha256'),
])
def test_valid_messages_pass(msg, ok_kind):
    ok, why = lint.validate(msg)
    assert ok, why
    assert why == ok_kind


@pytest.mark.parametrize('msg', [
    'wave done, everything green',
    'wave done — local: 319 passed (no run id)',
    'https://github.com/<gh-owner>/raphael/actions',   # no /runs/<id>
    'sha256:notahexdigest',                       # not 64 hex
])
def test_invalid_messages_bounce(msg):
    ok, why = lint.validate(msg)
    assert not ok
    assert 'MISSING' in why


def test_lints_last_wave_done_from_events_file(tmp_path):
    events = tmp_path / 'qa-security.jsonl'
    rows = [
        {'type': 'task_done', 'msg': 'no id here'},
        {'type': 'wave_done', 'msg': 'bounced: no id'},
    ]
    events.write_text('\n'.join(json.dumps(r) for r in rows) + '\n',
                      encoding='utf-8')
    # no run id -> exit 1
    assert lint.main(['--file', str(events)]) == 1
    # append a compliant one -> last wave_done must now lint clean
    rows.append({'type': 'wave_done',
                 'msg': 'green https://github.com/o/r/actions/runs/123456'})
    events.write_text('\n'.join(json.dumps(r) for r in rows) + '\n',
                      encoding='utf-8')
    assert lint.main(['--file', str(events)]) == 0


def test_missing_events_file_exits_1(tmp_path):
    assert lint.main(['--file', str(tmp_path / 'nope.jsonl')]) == 1

"""P0-URGENT (coord inbox 47): wake-drop visibility.

The user reports 'if she ever replies' — wake segments DO reach STT but some
are gate-dropped SILENTLY (no wake match, or the pre-STT gate refuses). This
adds a lightweight count+reason log (never content) so the live drop rate is
observable. `note_wake_drop` increments a per-reason counter and emits a
structured `wake_drop` log line.

Run:  brain/.venv/bin/python -m pytest brain/tests/test_wake_drop_visibility.py -q
"""
import json

from brain import ws


def _reset():
    ws._WAKE_DROP_COUNTS.clear()


def test_note_wake_drop_counts_per_reason(capsys):
    _reset()
    assert ws.note_wake_drop('no_wake_match') == 1
    assert ws.note_wake_drop('no_wake_match') == 2
    assert ws.note_wake_drop('silence') == 1
    assert ws._WAKE_DROP_COUNTS == {'no_wake_match': 2, 'silence': 1}
    # structured log: event + reason + running total, NO transcript content
    lines = [l for l in capsys.readouterr().out.splitlines() if l.strip()]
    drops = [json.loads(l) for l in lines if '"wake_drop"' in l]
    assert len(drops) == 3
    assert drops[0]['event'] == 'wake_drop'
    assert drops[0]['reason'] == 'no_wake_match'
    assert drops[0]['total'] == 1
    assert drops[2]['reason'] == 'silence'
    assert drops[2]['total'] == 1


def test_note_wake_drop_never_raises_and_never_logs_content(capsys):
    _reset()
    # a reason carrying content-ish text is still just a key (no transcript
    # field ever reaches the log)
    ws.note_wake_drop("undecided:'open youtube'")
    out = capsys.readouterr().out
    rec = json.loads([l for l in out.splitlines() if '"wake_drop"' in l][-1])
    assert rec['event'] == 'wake_drop'
    assert set(rec) == {'ts', 'event', 'reason', 'total'}
    _reset()


def test_ws_module_exports_note_wake_drop():
    assert callable(ws.note_wake_drop)
    assert isinstance(ws._WAKE_DROP_COUNTS, dict)
    _reset()

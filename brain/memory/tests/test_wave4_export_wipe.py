"""Wave-4 memory export / delete control tests (user-directed surfaces)."""
import json
import stat

import pytest

import brain.memory as mem
from brain.memory import conversation, export, store, summary


@pytest.fixture(autouse=True)
def _no_background_flusher(monkeypatch):
    """Deterministic flushes: the daemon thread must not win the race."""
    monkeypatch.setattr(conversation, '_ensure_flusher', lambda: None)


def test_export_covers_everything_for_owner_only_and_is_0600(tmp_path):
    store.remember('mine fact', source='user', category='fact')
    store.remember('mine identity', source='user', category='identity')
    store.remember('other person row', source='user', category='fact',
                   owner='alice')
    conversation.on_turn(user='u', assistant='a')
    conversation.on_turn(user='u2', assistant='a2')
    assert conversation.flush() == 2
    summary.add_summary('rolling summary', covers_from=1, covers_to=2)

    path = export.export_all(dest=tmp_path)
    assert path.is_file()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600     # personal data

    counts = export.export_count(path)
    assert counts == {'memory': 2, 'turn': 2, 'summary': 1}  # alice excluded

    lines = [json.loads(l) for l in path.read_text(encoding='utf-8').splitlines()]
    texts = [r.get('text') for r in lines if r['kind'] == 'memory']
    assert 'mine fact' in texts and 'mine identity' in texts
    assert 'other person row' not in texts                 # owner discipline
    assert all(r['kind'] in ('memory', 'turn', 'summary') for r in lines)


def test_export_raises_on_bad_destination(tmp_path):
    blocker = tmp_path / 'blocker'
    blocker.write_text('i am a file, not a directory')
    with pytest.raises(OSError):
        export.export_all(dest=blocker / 'exports')


def test_wipe_scopes_are_surgical():
    store.remember('keep me?', category='fact')
    conversation.on_turn(user='u', assistant='a')
    conversation.flush()
    summary.add_summary('s')

    # conversations scope leaves memories alone
    counts = export.wipe('conversations')
    assert counts['memories'] == 0 and counts['turns'] == 1 and counts['summaries'] == 1
    assert len(store.list_memories()) == 1
    assert conversation.turn_count() == 0
    assert summary.recent_summaries() == []

    # memories scope leaves conversations alone
    conversation.on_turn(user='u', assistant='a')
    conversation.flush()
    counts = export.wipe('memories')
    assert counts == {'memories': 1, 'turns': 0, 'summaries': 0}
    assert store.list_memories() == []
    assert conversation.turn_count() == 1


def test_wipe_is_owner_scoped():
    store.remember('default row', category='fact')
    store.remember('alice row', category='fact', owner='alice')
    counts = export.wipe('memories', owner='alice')
    assert counts['memories'] == 1
    remaining = [r['text'] for r in store.list_memories()]
    assert remaining == ['default row']                   # PR #2404 discipline


def test_wipe_all_and_scope_validation():
    store.remember('x', category='fact')
    conversation.on_turn(user='u', assistant='a')
    conversation.flush()
    summary.add_summary('y')
    counts = export.wipe('all')
    assert counts['memories'] == 1 and counts['turns'] == 1 and counts['summaries'] == 1
    assert store.list_memories() == []
    assert conversation.turn_count() == 0
    assert summary.recent_summaries() == []
    with pytest.raises(ValueError):
        export.wipe('everything')                          # loud, not silent


def test_export_count_fail_silent():
    assert export.export_count('/nonexistent/export.jsonl') == {}

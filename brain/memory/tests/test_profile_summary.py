"""Profile view + conversation summary tests."""
import pytest

import brain.memory as mem
from brain.memory import conversation, profile, store, summary


def test_profile_only_identity_and_preference_pinned_first():
    ident = store.remember('user name is <wsl-user>', source='user',
                           category='identity')
    pref = store.remember('prefers concise answers', source='user',
                          category='preference')
    store.remember('deploy runs on fridays', category='fact')      # excluded
    store.remember('unknown phone number', category='contact')     # excluded
    store.pin(ident, True)
    rows = profile.user_profile()
    ids = [r['id'] for r in rows]
    assert ids == [ident, pref]                # pinned identity first
    assert all(r['category'] in ('identity', 'preference') for r in rows)


def test_profile_uses_tiebreak_and_owner_scope():
    a = store.remember('likes green tea', source='user', category='preference')
    b = store.remember('likes oolong tea', source='user', category='preference')
    store.bump_use(b)
    store.bump_use(b)
    ids = [r['id'] for r in profile.user_profile()]
    assert ids.index(b) < ids.index(a)          # more uses -> higher
    # owner isolation
    store.remember('other person fact', source='user', category='identity',
                   owner='alice')
    assert [r for r in profile.user_profile(owner='bob')
            if r['text'] == 'other person fact'] == []


def test_profile_fail_silent(monkeypatch):
    def _raise():
        raise RuntimeError('db gone')
    monkeypatch.setattr(mem, 'get_conn', _raise)
    assert profile.user_profile() == []


# ---- summaries --------------------------------------------------------------
def test_add_summary_validation_and_recent_order():
    with pytest.raises(ValueError):
        summary.add_summary('   ')
    s1 = summary.add_summary('earlier summary', covers_from=0, covers_to=0)
    s2 = summary.add_summary('user likes tests', covers_from=1, covers_to=5)
    recent = summary.recent_summaries()
    assert [r['id'] for r in recent] == [s2, s1]        # newest first
    assert recent[0]['covers_to'] == 5
    assert summary.covers_up_to() == 5                  # max coverage


def test_covers_range_keys_on_turn_ids_not_timestamps():
    """Same-second turns: coverage advances by id, no turn is ever skipped."""
    for i in range(4):                       # all four land in the same second
        conversation.on_turn(user=f'u{i}', assistant='a')
    assert conversation.flush() == 4
    turns = summary.uncovered_turns()
    assert len(turns) == 4
    summary.add_summary('covers first three', covers_from=turns[0]['id'],
                        covers_to=turns[2]['id'])
    rest = summary.uncovered_turns()
    assert [t['id'] for t in rest] == [turns[3]['id']]   # exactly one left


def test_maybe_summarize_due_and_not_due(monkeypatch):
    calls = []

    def fake_chat(messages, purpose='chat'):
        calls.append(messages)
        return {'text': 'rolling summary text'}

    # not due: below threshold
    conversation.on_turn(user='u', assistant='a')
    conversation.flush()
    assert summary.maybe_summarize(min_uncovered=5, chat_fn=fake_chat) is None
    assert calls == []
    # due
    for _ in range(4):
        conversation.on_turn(user='u', assistant='a')
    conversation.flush()
    sid = summary.maybe_summarize(min_uncovered=5, chat_fn=fake_chat)
    assert isinstance(sid, int)
    assert len(calls) == 1
    # transcript rendered chronologically inside the prompt
    user_msgs = [m for m in calls[0] if m['role'] == 'user']
    assert 'User: u' in user_msgs[0]['content']
    assert 'Raphael: a' in user_msgs[0]['content']
    # already covered -> not due again without new turns
    assert summary.maybe_summarize(min_uncovered=5, chat_fn=fake_chat) is None
    assert len(calls) == 1


def test_maybe_summarize_fail_silent_on_router_error():
    for _ in range(3):
        conversation.on_turn(user='u', assistant='a')
    conversation.flush()

    def boom(messages, purpose='chat'):
        raise ConnectionError('provider offline')

    assert summary.maybe_summarize(min_uncovered=2, chat_fn=boom) is None
    assert summary.recent_summaries() == []            # nothing half-recorded


def test_summarize_turns_handles_string_and_junk_responses():
    turns = [{'user': 'hi', 'assistant': 'hello'}]
    assert summary.summarize_turns(turns, chat_fn=lambda m, purpose='chat': 'ok') == 'ok'
    assert summary.summarize_turns(turns, chat_fn=lambda m, purpose='chat': {}) is None
    assert summary.summarize_turns([], chat_fn=lambda m, purpose='chat': 'ok') is None
    assert summary.summarize_turns(
        turns, chat_fn=lambda m, purpose='chat': (_ for _ in ()).throw(
            RuntimeError('x'))) is None


def test_summaries_fail_silent_and_clear():
    summary.add_summary('temp')
    def _raise():
        raise RuntimeError('db gone')
    orig = mem.get_conn
    mem.get_conn = _raise
    try:
        assert summary.recent_summaries() == []
        assert summary.covers_up_to() == 0
        assert summary.uncovered_turns() == []
        assert summary.clear_summaries() == 0
    finally:
        mem.get_conn = orig
    assert summary.clear_summaries() == 1             # real delete worked


def test_conversation_tables_cleared_between_tests():
    """Conftest hygiene: state must not leak across tests."""
    assert conversation.turn_count() == 0
    assert store.list_memories() == []
    assert summary.recent_summaries() == []

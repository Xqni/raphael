"""Store + additive-schema tests (memories table, owner discipline)."""
import pytest

import brain.memory as mem
from brain.memory import fts, store


def test_remember_returns_id_and_lists():
    mid = store.remember('user prefers concise answers',
                         source='user', category='preference', pinned=True)
    assert isinstance(mid, int) and mid > 0
    rows = store.list_memories()
    assert len(rows) == 1
    r = rows[0]
    assert r['text'] == 'user prefers concise answers'
    assert r['source'] == 'user'
    assert r['category'] == 'preference'
    assert r['pinned'] == 1
    assert r['uses'] == 0


def test_validation_is_loud():
    with pytest.raises(ValueError):
        store.remember('   ')                         # empty after strip
    with pytest.raises(ValueError):
        store.remember('x', source='telepathy')       # bad source
    with pytest.raises(ValueError):
        store.remember('x', category='vibes')         # bad category
    with pytest.raises(ValueError):
        store.list_memories(category='vibes')         # bad filter too


def test_owner_isolation_on_every_query():
    """PR #2404 regression: one owner's rows never leak to another."""
    a = store.remember('alice secret', source='user', category='fact',
                       owner='alice')
    assert store.list_memories(owner='bob') == []
    assert store.list_memories() == []                # default owner != alice
    assert store.forget(a, owner='bob') is False      # cannot delete cross-owner
    assert len(store.list_memories(owner='alice')) == 1
    assert store.forget(a, owner='alice') is True
    assert store.list_memories(owner='alice') == []


def test_pin_and_listing_order_and_filter():
    m1 = store.remember('first fact', category='fact')
    m2 = store.remember('pinned preference', category='preference')
    store.pin(m2, True)
    rows = store.list_memories()
    assert [r['id'] for r in rows] == [m2, m1]        # pinned floats to top
    assert [r['id'] for r in store.list_memories(pinned=True)] == [m2]
    assert [r['id'] for r in store.list_memories(category='fact')] == [m1]
    store.pin(m2, False)
    assert store.list_memories(pinned=True) == []


def test_forget_removes_row():
    mid = store.remember('transient observation')
    assert store.forget(mid) is True
    assert store.forget(mid) is False                 # already gone
    assert store.list_memories() == []


def test_bump_use_increments_and_is_fail_silent():
    mid = store.remember('used memory')
    store.bump_use(mid)
    store.bump_use(mid)
    r = store.list_memories()[0]
    assert r['uses'] == 2
    assert r['last_used'] is not None
    # fail-silent: broken DB -> no exception
    def _raise():
        raise RuntimeError('db gone')
    orig = mem.get_conn
    mem.get_conn = _raise
    try:
        store.bump_use(mid)                            # must not raise
    finally:
        mem.get_conn = orig


def test_init_db_is_idempotent_additive():
    """Re-running migration must not duplicate or break anything."""
    mem.init_db()
    mem.init_db()
    assert len(store.list_memories()) == 0            # jobs untouched, data kept
    # jobs/journal/state tables still exist after re-migration
    conn = mem.get_conn()
    try:
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()
    assert {'jobs', 'journal', 'state', 'memories',
            'conversation_turns'} <= names


def test_fts_availability_is_boolean_and_sticky():
    # never assumed: a build without FTS5 must not break anything (store tests
    # above already pass either way); here we only pin the API shape.
    ok = fts.available()
    assert isinstance(ok, bool)
    conn = mem.get_conn()
    try:
        assert isinstance(fts.ensure(conn), bool)     # ensure() safe anytime
        assert fts.ensure(conn) == ok                 # sticky after first check
    finally:
        conn.close()


@pytest.mark.skipif(not fts.available(), reason='sqlite build without FTS5')
def test_fts_index_syncs_with_store():
    mid = store.remember('the quick brown fox jumps', category='fact')
    conn = mem.get_conn()
    try:
        hits = conn.execute(
            "SELECT rowid FROM memories_fts WHERE memories_fts MATCH 'quick' "
            "AND rowid = ?", (mid,)).fetchall()
        assert len(hits) == 1
    finally:
        conn.close()
    store.forget(mid)
    conn = mem.get_conn()
    try:
        hits = conn.execute(
            "SELECT rowid FROM memories_fts WHERE memories_fts MATCH 'quick' "
            "AND rowid = ?", (mid,)).fetchall()
        assert hits == []
    finally:
        conn.close()

"""FTS corruption detection + recovery tests (wave-4 hardening).

Proves: integrity_check detects ghost/missing index rows, rebuild() cures
them from the content table, and retrieval DEGRADES gracefully (keyword
fallback + self-heal) when the FTS query itself blows up — never a failed
turn, never lost pinned rows.
"""
import pytest

import brain.memory as mem
from brain.memory import fts, retrieval, store

pytestmark = pytest.mark.skipif(not fts.available(),
                                reason='sqlite build without FTS5')


def _conn():
    return mem.get_conn()


def test_integrity_ok_after_normal_store_ops():
    store.remember('alpha beta gamma', category='fact')
    conn = _conn()
    try:
        assert fts.integrity_check(conn) == 'ok'
    finally:
        conn.close()


def test_ghost_index_row_detected_and_rebuilt():
    mid = store.remember('ordinary fact about kettles', category='fact')
    conn = _conn()
    try:
        # bypass the triggers: a row in the index that content does NOT have
        conn.execute('INSERT INTO memories_fts(rowid, text) '
                     "VALUES (999999, 'ghostword spectralentry')")
        conn.commit()
        assert 'mismatch' in fts.integrity_check(conn)
        # ghost is reachable by MATCH before the rebuild...
        hits = conn.execute("SELECT count(*) FROM memories_fts WHERE "
                            "memories_fts MATCH 'ghostword'").fetchone()[0]
        assert hits == 1
        assert fts.rebuild(conn) is True
        assert fts.integrity_check(conn) == 'ok'
        hits = conn.execute("SELECT count(*) FROM memories_fts WHERE "
                            "memories_fts MATCH 'ghostword'").fetchone()[0]
        assert hits == 0                        # ghost purged by rebuild
    finally:
        conn.close()
    assert retrieval.retrieve('kettles')[0]['id'] == mid   # real row intact


def test_missing_index_entry_misses_then_rebuild_recovers():
    mid = store.remember('zephyr quilts usage report', category='fact')
    conn = _conn()
    try:
        # drop THIS row's index entry behind the triggers' back
        row = conn.execute('SELECT text FROM memories WHERE id = ?', (mid,)).fetchone()
        conn.execute("INSERT INTO memories_fts(memories_fts, rowid, text) "
                     "VALUES ('delete', ?, ?)", (mid, row['text']))
        conn.commit()
        assert 'mismatch' in fts.integrity_check(conn)     # content vs index
        out = retrieval.retrieve('zephyr quilts')          # FTS path: a miss
        assert all(r['id'] != mid for r in out)
        assert fts.rebuild(conn) is True
        out = retrieval.retrieve('zephyr quilts')
        assert out and out[0]['id'] == mid                 # recovered
    finally:
        conn.close()


def test_fts_exception_degrades_to_keyword_and_self_heals(monkeypatch):
    mid = store.remember('cobalt wrenches reconciliation', category='fact')

    def _boom(conn, toks, owner, limit):
        raise RuntimeError('fts index is corrupt')
    monkeypatch.setattr(retrieval, '_fts_matches', _boom)

    healed = {'n': 0}
    real_rebuild = fts.rebuild
    def _spy(conn):
        healed['n'] += 1
        return real_rebuild(conn)
    monkeypatch.setattr(fts, 'rebuild', _spy)

    out = retrieval.retrieve('cobalt wrenches')            # degraded, not dead
    assert out and out[0]['id'] == mid
    assert healed['n'] == 1                                # self-heal attempted
    # pinned rows survive even if EVERYTHING else fails
    pinned = store.remember('pinned survives outages', source='user',
                            category='preference', pinned=True)
    monkeypatch.setattr(retrieval, '_keyword_matches',
                        lambda *a, **k: (_ for _ in ()).throw(
                            RuntimeError('keyword path also broken')))
    out = retrieval.retrieve('cobalt wrenches')
    assert any(r['id'] == pinned for r in out)             # pinned is separate

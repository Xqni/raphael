"""AUD-15 (memory DB location/perms/retention), AUD-25 (MCP concurrent
replies), AUD-28 (schedule atomic claim) — verify-first fixes, all fixtures
in TEMP dirs (never the real data-dir or checkout DB)."""
import datetime as dt
import os
import stat
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

import brain.memory as mem
from brain.memory import store
from brain.tools import schedule as sc
from brain.tools import mcp as m


# ---- AUD-15 -----------------------------------------------------------------
def test_db_migrates_from_checkout_to_data_dir(tmp_path, monkeypatch):
    from brain import config as appcfg
    legacy = tmp_path / 'checkout' / 'memory.db'
    legacy.parent.mkdir()
    legacy.write_bytes(b'legacy-bytes')
    datadir = tmp_path / 'datadir'
    monkeypatch.setattr(mem, '_DEFAULT', str(legacy))
    monkeypatch.setattr(mem, '_migrated', False, raising=False)
    monkeypatch.setattr(appcfg, 'data_dir', lambda: datadir)
    monkeypatch.delenv('RAPHAEL_DB_PATH', raising=False)
    try:
        path = mem.db_path()
        assert str(path).startswith(str(datadir))       # NOT checkout-local
        assert os.path.exists(path) or not legacy.exists()
        assert not legacy.exists()                      # one-time move happened
        assert (datadir / 'memory.db').exists()         # data preserved
    finally:
        mem._migrated = True                            # don't leak migration state


def test_db_files_are_owner_only_0600(tmp_path, monkeypatch):
    db = tmp_path / 'fresh.db'
    monkeypatch.setenv('RAPHAEL_DB_PATH', str(db))
    mem.init_db()                       # fresh file -> full schema + migrate
    for _ in range(2):                # 2 cycles so -wal/-shm exist and harden
        conn = mem.get_conn()
        try:
            conn.execute(
                "INSERT INTO state (key, value) VALUES ('perm', 'x') "
                "ON CONFLICT(key) DO UPDATE SET value='x'")
            conn.commit()
        finally:
            conn.close()
    perms = stat.S_IMODE(db.stat().st_mode)
    assert perms == 0o600, oct(perms)                    # was umask-default
    for suf in ('-wal', '-shm'):
        p = tmp_path / ('fresh.db' + suf)
        if p.exists():
            assert stat.S_IMODE(p.stat().st_mode) == 0o600


def test_retention_cap_drops_oldest_keeps_pinned(tmp_path, monkeypatch):
    from brain import config as appcfg
    monkeypatch.setattr(appcfg, 'get_config',
                        lambda: {'memory': {'max_rows': 3}})
    kept = [store.remember(f'row {n}', category='fact') for n in range(5)]
    pinned = store.remember('never trimmed', category='fact', pinned=True)
    rows = store.list_memories(limit=50)
    unpinned_ids = {r['id'] for r in rows if not r['pinned']}
    assert unpinned_ids <= set(kept[-3:])                # newest 3 survive
    assert set(kept[:2]) - unpinned_ids == set(kept[:2]) # oldest dropped
    assert pinned in {r['id'] for r in rows}             # pinned immune
    # owner-scoped: another owner's rows are never trimmed by my inserts
    store.remember('other row', owner='alice', category='fact')
    assert any(r['text'] == 'other row'
               for r in store.list_memories(owner='alice', limit=50))


# ---- AUD-25 -----------------------------------------------------------------
def test_concurrent_mcp_calls_never_steal_replies(monkeypatch):
    import sys as _sys
    from pathlib import Path
    from brain import tools as reg
    fake = Path(__file__).resolve().parent / 'fake_mcp_server.py'
    cfg = [{'name': 'conc', 'transport': 'stdio',
            'command': [_sys.executable, str(fake)],
            'allow': ['echo'], 'timeout_s': 15.0}]
    monkeypatch.setattr(m, '_cfg',
                        lambda k, d: cfg if k == 'mcp.servers' else d)
    try:
        out = m.refresh(force=True)
        assert 'mcp_conc_echo' in out['registered']
        call = reg.get('mcp_conc_echo')

        def work(i):
            return call(text=f'worker-{i}')
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(work, range(8)))
        # serialized request cycles: every caller got ITS OWN reply
        assert results == [f'echo: worker-{i}' for i in range(8)]
    finally:
        m.shutdown_clients()
        m._inventory.clear()
        m._booted = False
        reg._registry.pop('mcp_conc_echo', None)
        reg._META.pop('mcp_conc_echo', None)


# ---- AUD-28 -----------------------------------------------------------------
def _due_timer():
    return sc._insert('timer', int(__import__('time').time()) - 5,
                      'Timer done: claim test')


def test_fresh_claim_blocks_a_second_pumper():
    tid = _due_timer()
    conn = sc._conn()
    try:
        conn.execute("UPDATE schedules SET status='firing', claimed_at=? "
                     "WHERE id=?", (sc._now(), tid))
        conn.commit()
    finally:
        conn.close()
    fired = []
    assert sc.pump_once(submit_fn=fired.append) == 0    # claim held elsewhere
    assert fired == []


def test_stale_claim_recovers_and_fires():
    tid = _due_timer()
    conn = sc._conn()
    try:
        conn.execute("UPDATE schedules SET status='firing', claimed_at=? "
                     "WHERE id=?", (sc._now() - 400, tid))   # crash window
        conn.commit()
    finally:
        conn.close()
    fired = []
    assert sc.pump_once(submit_fn=fired.append) == 1    # recovered -> fired
    assert fired == ['Timer done: claim test']


def test_claim_is_exclusive_under_threads():
    tid = _due_timer()
    results = []
    barrier = threading.Barrier(4)

    def try_claim():
        barrier.wait(timeout=5)
        results.append(sc._claim(tid, sc._now()))
    threads = [threading.Thread(target=try_claim) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)
    assert results.count(True) == 1                     # exactly ONE winner


def test_failure_releases_the_claim():
    tid = _due_timer()
    def boom(_t):
        raise RuntimeError('submit failed')
    assert sc.pump_once(submit_fn=boom) == 0            # claimed, failed
    row_state = sc._conn()
    try:
        row = row_state.execute(
            "SELECT status, claimed_at FROM schedules WHERE id=?",
            (tid,)).fetchone()
    finally:
        row_state.close()
    assert row['status'] == 'pending' and row['claimed_at'] is None
    fired = []
    assert sc.pump_once(submit_fn=fired.append) == 1    # retryable next pump

"""Wave-4 resilience: crash recovery, PROTOCOL §5 — end-to-end.

Brain-core owns `_mark_interrupted` (their kill-safety matrix covers the
in-process transitions); THIS drill covers the real restart boundary: seed
a DB exactly as a crashed brain would leave it (running / queued /
awaiting_confirm rows + one terminal row), boot a REAL isolated brain
process against it, and verify via REST that:

- every non-terminal row is reported `interrupted` at startup;
- terminal rows are untouched (state machine immutability);
- NOTHING is auto-resumed (PROTOCOL §5: reported, never auto-resumed) —
  statuses stay `interrupted` after the engine is fully up.

Isolated instance only (harness.instance_proc: ephemeral port, private
token/DB — never the live stack), every process stopped in `finally`.
"""
import os
import time

from harness import instance_proc as ip


def _seed_crash_db(db_path, monkeypatch):
    """Create schema + rows exactly as a mid-run crash would leave them."""
    monkeypatch.setenv('RAPHAEL_DB_PATH', db_path)
    from brain.memory import init_db
    init_db()
    from brain.jobs import store

    ids = {}
    running = store.create_job(text='crash while running', priority='normal',
                               source='text')
    assert store.transition(running['id'], 'running', stage='llm', progress=0.4)
    ids['running'] = running['job']

    queued = store.create_job(text='crash while queued', priority='normal',
                              source='text')
    ids['queued'] = queued['job']

    awaiting = store.create_job(text='crash while confirming',
                                priority='normal', source='text')
    assert store.transition(awaiting['id'], 'running', stage='routing')
    assert store.transition(awaiting['id'], 'awaiting_confirm',
                            stage='routing')
    ids['awaiting'] = awaiting['job']

    done = store.create_job(text='finished before crash', priority='normal',
                            source='text')
    assert store.transition(done['id'], 'done', stage='done', progress=1.0,
                            result='ok')
    ids['done'] = done['job']
    return ids


def _statuses(port, token):
    code, jobs = ip.rest(port, '/jobs', token)
    assert code == 200, (code, jobs)
    return {j['job']: j['status'] for j in jobs}


def test_crash_recovery_marks_interrupted_and_never_auto_resumes(
        tmp_path, monkeypatch):
    import tempfile
    db_fd, db_path = tempfile.mkstemp(prefix='qa-crashseed-db-')
    os.close(db_fd)
    os.remove(db_path)                       # init_db creates it fresh
    ids = _seed_crash_db(db_path, monkeypatch)
    port = ip.free_port()
    proc = meta = None
    try:
        proc, meta = ip.spawn('qa-security-recovery', port, db_path=db_path)
        ip.health(port, meta['token'], meta)

        # 1. every non-terminal row reported interrupted (PROTOCOL §5)
        got = _statuses(port, meta['token'])
        assert got.get(ids['running']) == 'interrupted', got
        assert got.get(ids['queued']) == 'interrupted', got
        assert got.get(ids['awaiting']) == 'interrupted', got

        # 2. terminal row untouched (immutable state machine)
        assert got.get(ids['done']) == 'done', got

        # 3. engine fully up but nothing auto-resumed — statuses hold
        time.sleep(1.2)
        again = _statuses(port, meta['token'])
        for key in ('running', 'queued', 'awaiting'):
            assert again.get(ids[key]) == 'interrupted', \
                f'{key} row was resumed: {again}'

        # 4. repeated reads stay stable (workers never re-dequeue)
        time.sleep(0.8)
        final = _statuses(port, meta['token'])
        assert final == again, (again, final)
    finally:
        if proc is not None:
            ip.stop(proc)
        if meta is not None:
            ip.cleanup_meta(meta)
        for suffix in ('', '-wal', '-shm'):
            try:
                os.remove(db_path + suffix)
            except OSError:
                pass

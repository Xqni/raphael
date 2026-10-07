"""Wave-4 hardening battery: crash-recovery journal replay, engine
kill-safety matrix, input-lock arbitration stress, pidfile test-hygiene.
All mock-only (Rule 14 / live stack up: no servers, no Fish, no Ollama)."""
import asyncio
import json
import os
import tempfile
import time

import pytest

from brain import loop as loop_mod
from brain.jobs import store
from brain.jobs.engine import get_engine


async def wait_for(pred, timeout=8.0, step=0.01):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        await asyncio.sleep(step)
    return False


# ---- (a) crash-recovery: journal replay hardening ---------------------------
@pytest.mark.asyncio
async def test_restart_marks_interrupted_journal_replayable_and_flags_clean():
    """A mid-run crash (here: mid-CONFIRM) must leave a fully replayable
    journal, a clean terminal row (pending_confirm cleared), an immutable
    interrupted status, and a recorded boot id for the Notice emitter."""
    engine = get_engine()
    if engine.started:
        await engine.shutdown()
    engine.pause()
    try:
        snap = await engine.submit(text='crash me mid-confirm',
                                   priority='normal', source='text')
        # simulate: running + confirm asked + crash (no answer ever lands)
        store.transition(snap['id'], 'running', stage='routing', progress=0.2)
        store.set_pending_confirm(snap['id'], True)
        engine.emit_event(store.get_job(snap['id']), 'awaiting_confirm',
                          stage='routing', progress=0.2, text='Crash? Confirm?')
        assert store.get_job(snap['id'])['pending_confirm'] is True

        # ---- "restart": startup recovery ------------------------------------
        marked = engine._mark_interrupted()
        row = store.get_job(snap['id'])
        assert row['status'] == 'interrupted'
        assert row['pending_confirm'] is False, 'stale confirm flag must be cleared'
        assert snap['job'] in marked and engine.interrupted_at_boot == marked
        # terminal + immutable
        assert store.transition(snap['id'], 'done') is False
        assert store.get_job(snap['id'])['status'] == 'interrupted'

        # journal replays end-to-end: created -> queued -> running frame ->
        # awaiting_confirm frame -> interrupted status (order preserved)
        conn = store.get_conn()
        try:
            rows = conn.execute(
                'SELECT event FROM journal WHERE job_id=? ORDER BY rowid',
                (snap['id'],)).fetchall()
        finally:
            conn.close()
        events = [json.loads(r['event']) if str(r['event']).startswith('{')
                  else r['event'] for r in rows]
        kinds = []
        for e in events:
            if isinstance(e, dict):
                kinds.append(e.get('event') or e.get('status'))
            else:
                kinds.append(e)
        assert kinds[0] in ('created',), kinds
        assert 'awaiting_confirm' in kinds, kinds
        assert kinds[-1] == 'status' or 'interrupted' in str(events[-1]), kinds
        # the interrupted status row exists in the journal
        assert any(isinstance(e, dict) and e.get('status') == 'interrupted'
                   for e in events), kinds
        # boot notice had its count source
        assert engine.interrupted_at_boot[0] == snap['job']
    finally:
        engine.resume()


# ---- (b) engine kill-safety matrix ------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize('stage', ['queued', 'running', 'confirm', 'lock'])
async def test_engine_kill_safety_matrix(stage):
    """Cancel at every stage -> job terminal, resources released, hook fired,
    no orphan task entries. Then a full shutdown leaves ZERO non-terminal."""
    engine = get_engine()
    if engine.started:
        await engine.shutdown()
    hooked = []
    engine.on_job_cancelled = lambda rowid, jid: hooked.append((rowid, jid))
    gate = asyncio.Event()
    old_runner = engine.runner

    async def runner(job):
        if stage == 'confirm':
            store.set_pending_confirm(job['id'], True)
            await engine.confirmer.request(job['id'], 'q?', ['yes', 'no'],
                                           risk='high')
            await gate.wait()
        elif stage == 'lock':
            await engine.lock.acquire(job['id'])
            await gate.wait()
        else:
            await gate.wait()

    engine.runner = runner
    if stage == 'queued':
        engine.start(workers=2)
        engine.pause()
    else:
        engine.start(workers=2)
    try:
        snap = await engine.submit(text=f'kill at {stage}', priority='normal',
                                   source='text')
        if stage == 'queued':
            await wait_for(lambda: store.get_job(snap['id'])['status'] == 'queued')
            assert hooked == []
        elif stage == 'confirm':
            await wait_for(lambda: bool(engine.confirmer.pending_ids()))
        elif stage == 'lock':
            await wait_for(lambda: engine.lock.owner == snap['id'])
        else:
            await wait_for(lambda: store.get_job(snap['id'])['status'] == 'running')

        engine.cancel(snap['job'], scope='full')
        assert await wait_for(
            lambda: store.get_job(snap['id'])['status'] == 'cancelled')

        # invariants after the kill
        row = store.get_job(snap['id'])
        assert row['status'] in store.TERMINAL
        assert row['pending_confirm'] is False
        assert engine.confirmer.pending_ids() == []
        assert engine.lock.owner is None and engine.lock.waiters == 0
        assert hooked == [(snap['id'], snap['job'])], hooked
        assert snap['id'] not in engine._tasks or engine._tasks[snap['id']].done()
        assert store.transition(snap['id'], 'done') is False   # immutable
    finally:
        gate.set()
        engine.runner = old_runner
        engine.on_job_cancelled = None
        engine.resume()
        await engine.shutdown()
        # shutdown sweep: nothing non-terminal survives a clean stop
        leftovers = [j for j in store.list_jobs()
                     if j['status'] not in store.TERMINAL]
        assert leftovers == [], leftovers


@pytest.mark.asyncio
async def test_shutdown_mid_speech_cleans_interrupts_and_speakers():
    """Shutdown with an active speech stream: job terminal, the job-scoped
    interrupt released, the speaker task gone (no orphans)."""
    from brain.voice import get_voice
    engine = get_engine()
    if engine.started:
        await engine.shutdown()
    loop_mod.start_loop(hub=None)      # wires the speech-cancel listener too
    engine.pause()
    voice = get_voice()
    try:
        snap = await engine.submit(text='speech shutdown', priority='normal',
                                   source='text')
        ev = voice.interrupts.register(snap['job'])
        assert not ev.is_set()
        await engine.shutdown()        # full stop while "speaking"
        row = store.get_job(snap['id'])
        assert row['status'] in store.TERMINAL
        # shutdown kill path fires the per-job hook -> this job's speech stops
        assert ev.is_set(), 'shutdown cancel must stop this job\'s speech'
        assert engine.lock.owner is None and engine.lock.waiters == 0
        assert engine.confirmer.pending_ids() == []
    finally:
        engine.on_job_cancelled = None


# ---- (d) input-lock arbitration stress --------------------------------------
def test_lock_stress_random_churn_no_orphans_no_double_hold():
    """30 concurrent workers, seeded random cancellations mid-flight: single
    owner at all times, no orphan waiters, every survivor acquires exactly
    once, the lock ends free."""
    from brain.jobs.lock import InputLock
    import random

    async def main():
        lock = InputLock()
        rng = random.Random(42)
        held_concurrently = {'n': 0, 'max': 0}
        acquired_order = []

        async def worker(i):
            got = False
            try:
                if await lock.acquire(i):
                    got = True
                    held_concurrently['n'] += 1
                    held_concurrently['max'] = max(held_concurrently['max'],
                                                   held_concurrently['n'])
                    acquired_order.append(i)
                    await asyncio.sleep(rng.uniform(0, 0.004))
            finally:
                if got:
                    held_concurrently['n'] -= 1
                    lock.release(i)

        tasks = [asyncio.create_task(worker(i)) for i in range(30)]
        for i in sorted(rng.sample(range(30), 8)):
            await asyncio.sleep(0.001)
            tasks[i].cancel()
        results = await asyncio.gather(*tasks, return_exceptions=True)

        assert lock.owner is None and lock.waiters == 0, 'lock must end free'
        assert held_concurrently['max'] == 1, 'mutual exclusion violated'
        assert len(acquired_order) == len(set(acquired_order)), \
            'no worker ever acquired the lock twice'
        cancelled = [i for i, r in enumerate(results)
                     if isinstance(r, asyncio.CancelledError)]
        assert len(cancelled) >= 1, 'seeded cancels must actually cancel'
        completed = [i for i, r in enumerate(results)
                     if not isinstance(r, BaseException)]
        # every survivor acquired exactly once; a worker cancelled WHILE
        # holding is in acquired_order but not completed — that is correct
        # (its finally released the lock)
        assert len(completed) == len(set(completed))
        assert set(completed) <= set(acquired_order), \
            'a survivor that never acquired is a lost wakeup'
        # nobody is stranded: everyone either completed or was cancelled
        assert len(results) == 30

    asyncio.run(main())


def test_pidfile_targets_empty_under_pytest():
    """Wave-4 live-stack safety: TestClient boots must never write the LIVE
    brain's pidfiles (nor the legacy /tmp path)."""
    from brain import app as app_mod
    # running inside pytest -> no targets at all
    assert os.environ.get('PYTEST_CURRENT_TEST')
    assert app_mod._pidfile_targets() == []
    # production semantics: data-dir pidfile (+ legacy for main only)
    import brain.config as appcfg
    old = os.environ.pop('PYTEST_CURRENT_TEST')
    try:
        os.environ['RAPHAEL_INSTANCE'] = 'main'
        targets = app_mod._pidfile_targets()
        assert [str(t) for t in targets][-1] == '/tmp/raphael-brain.pid'
        os.environ['RAPHAEL_INSTANCE'] = 'router'
        targets = app_mod._pidfile_targets()
        assert all('/tmp/raphael-brain.pid' != str(t) for t in targets)
        assert all('router' in str(t) for t in targets)
    finally:
        os.environ['PYTEST_CURRENT_TEST'] = old
        os.environ.pop('RAPHAEL_INSTANCE', None)

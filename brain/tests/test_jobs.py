"""Unit tests for the job engine, input lock, and REAL confirm enforcement."""
import asyncio

import pytest

from brain import confirm as confirm_mod
from brain.jobs import store
from brain.jobs.engine import JobEngine
from brain.jobs.lock import InputLock


def run(coro):
    return asyncio.run(coro)


def _wait_status(job_id, statuses, timeout=5.0):
    """Poll the store until job reaches one of statuses (async)."""
    async def _inner():
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            job = store.get_job(job_id)
            if job and job['status'] in statuses:
                return job
            await asyncio.sleep(0.02)
        return store.get_job(job_id)
    return _inner()


def test_priority_preempts_admission_order():
    async def main():
        order = []

        async def runner(job):
            order.append(job['text'])
            store.transition(job['id'], 'done', result='ok')
            engine.emit_event(store.get_job(job['id']), 'done', stage='done', text='ok')

        engine = JobEngine()
        engine.runner = runner
        engine.start(workers=1)
        try:
            engine.pause()                     # gate admission deterministically
            bg = await engine.submit('background job', priority='background')
            uf = await engine.submit('urgent job', priority='user_facing')
            await asyncio.sleep(0.05)
            engine.resume()
            await _wait_status(bg['id'], ('done',))
            await _wait_status(uf['id'], ('done',))
            # user_facing preempts admission order (rank 0 < 2)
            assert order == ['urgent job', 'background job'], order
        finally:
            await engine.shutdown()
    run(main())


def test_cancel_running_job_no_orphans_releases_lock():
    async def main():
        engine = JobEngine()

        async def slow(job):
            await engine.lock.acquire(job['id'])
            try:
                await asyncio.sleep(30)
            finally:
                engine.lock.release(job['id'])

        engine.runner = slow
        engine.start(workers=2)
        try:
            snap = await engine.submit('gui job', input_lock=True)
            job = await _wait_status(snap['id'], ('running',))
            assert job is not None and job['status'] == 'running'
            # let the runner grab the lock
            for _ in range(100):
                if engine.lock.owner == snap['id']:
                    break
                await asyncio.sleep(0.01)
            assert engine.lock.is_held_by(snap['id'])
            engine.cancel(snap['job'])
            job = await _wait_status(snap['id'], ('cancelled',))
            assert job['status'] == 'cancelled'
            assert job['error_code'] == 'E_CANCELLED'
            await asyncio.sleep(0.05)
            assert engine.lock.owner is None          # lock released, no zombie
            assert engine._tasks == {}                # no orphaned asyncio tasks
        finally:
            await engine.shutdown()


def test_terminal_states_are_immutable():
    async def main():
        engine = JobEngine()
        engine.runner = None
        engine.start(workers=1)
        try:
            engine.pause()                      # deterministic: worker won't pick it
            snap = await engine.submit('doomed job')
            # force terminal via the guarded transition while still queued
            assert store.transition(snap['id'], 'done', result='ok')
            # cancel on a terminal job must NOT flip it
            job = engine.cancel(snap['job'])
            assert job['status'] == 'done'
            # direct guarded transition also refuses
            assert not store.transition(snap['id'], 'cancelled')
            assert store.get_job(snap['id'])['status'] == 'done'
        finally:
            await engine.shutdown()
    run(main())


def test_input_lock_fifo_and_cancel_while_waiting():
    async def main():
        engine = JobEngine()
        release_a = asyncio.Event()

        async def locky(job):
            await engine.lock.acquire(job['id'])
            try:
                if job['text'] == 'A':
                    await release_a.wait()
                else:
                    await asyncio.sleep(30)
            finally:
                engine.lock.release(job['id'])

        engine.runner = locky
        engine.start(workers=3)
        try:
            a = await engine.submit('A')
            await _wait_status(a['id'], ('running',))
            for _ in range(100):
                if engine.lock.is_held_by(a['id']):
                    break
                await asyncio.sleep(0.01)
            assert engine.lock.is_held_by(a['id'])
            b = await engine.submit('B')
            await asyncio.sleep(0.05)          # B queues behind A at the lock
            assert engine.lock.waiters >= 1
            engine.cancel(b['job'])            # cancel B while it waits
            b = await _wait_status(b['id'], ('cancelled',))
            assert b['status'] == 'cancelled'
            assert engine.lock.is_held_by(a['id'])   # lock NEVER stolen
            release_a.set()
            a = await _wait_status(a['id'], ('done',))
            assert a['status'] == 'done'
            await asyncio.sleep(0.05)
            assert engine.lock.owner is None
            assert engine.lock.waiters == 0
        finally:
            await engine.shutdown()
    run(main())


def test_shutdown_cancels_all_tasks():
    async def main():
        engine = JobEngine()

        async def slow(job):
            await asyncio.sleep(30)

        engine.runner = slow
        engine.start(workers=2)
        snaps = [await engine.submit(f'slow {i}') for i in range(3)]
        for s in snaps:
            await _wait_status(s['id'], ('running',))
        await engine.shutdown()
        assert engine._tasks == {}
        for s in snaps:
            job = store.get_job(s['id'])
            assert job['status'] in ('cancelled', 'interrupted'), job
    run(main())


def test_interrupted_marking_at_startup():
    async def main():
        snap = store.create_job('was running when brain died')
        store.transition(snap['id'], 'running')   # simulate crash mid-run
        engine = JobEngine()
        engine.runner = None
        engine.start(workers=1)                    # startup recovery path
        try:
            job = store.get_job(snap['id'])
            assert job['status'] == 'interrupted'  # reported, never auto-resumed
        finally:
            await engine.shutdown()
    run(main())


def test_confirm_classify_risky_vs_benign():
    benign = confirm_mod.classify('echo hello world')
    assert not benign.needs
    for risky in ('run rm -rf /tmp/x', 'delete the project folder',
                  'purchase a new laptop', 'ssh into the server and install stuff'):
        d = confirm_mod.classify(risky)
        assert d.needs, risky
        assert d.question and d.actions == ['yes', 'no']
    d = confirm_mod.classify('open the url', tool='shell')
    assert d.needs  # risky tool metadata alone triggers confirmation


def test_confirmer_yes_no_timeout():
    async def main():
        c = confirm_mod.Confirmer(timeout_s=0.2)
        fut_task = asyncio.create_task(c.request(1, 'q?', ['yes', 'no']))
        await asyncio.sleep(0.02)
        assert c.resolve(1, 'yes') is True
        assert await fut_task == 'yes'

        fut_task = asyncio.create_task(c.request(2, 'q?', ['yes', 'no']))
        await asyncio.sleep(0.02)
        assert c.resolve(2, 'no') is True
        assert await fut_task == 'no'

        # timeout aborts — NEVER auto-approves
        assert await c.request(3, 'q?', ['yes', 'no']) == 'timeout'
        assert c.resolve(99, 'yes') is False      # no pending job -> refused
    run(main())


def test_confirmer_free_text_fails_closed():
    assert confirm_mod.parse_free_text('yes please') == 'yes'
    assert confirm_mod.parse_free_text('no thanks') == 'no'
    assert confirm_mod.parse_free_text('hmm, maybe later modify it') == 'no'


def test_job_id_roundtrip():
    snap = store.create_job('id check')
    assert snap['job'].startswith('j_')
    assert store.parse_job_ref(snap['job']) == snap['id']
    assert store.get_job(snap['job'])['text'] == 'id check'

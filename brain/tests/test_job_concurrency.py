"""Wave-3 job-concurrency polish: input-lock fairness + per-job cancel.

Lock: FIFO hand-off, no queue-jumping (ownerless-with-waiters promotes the
OLDEST waiter, never the newcomer), cancelled waiters dropped cleanly.
Engine: `on_job_cancelled` fires for full-scope cancels only; the wired
listener stops THAT job's speech without touching other jobs' streams.
End-to-end: A holds, B+C queue FIFO, B cancelled mid-wait -> A and C finish
in order, B never runs, lock ends free.
No network, no Fish (TTS mocked by conftest), no real stack.
"""
import asyncio
import json
import os
import tempfile
import time

import pytest

from brain import loop as loop_mod
from brain.jobs import store
from brain.jobs.engine import get_engine
from brain.jobs.lock import InputLock


def run(coro):
    return asyncio.run(coro)


# ---- input-lock fairness ----------------------------------------------------
def test_lock_fifo_handoff_three_jobs():
    async def main():
        lock = InputLock()
        assert await lock.acquire(1) is True
        tb = asyncio.create_task(lock.acquire(2))
        tc = asyncio.create_task(lock.acquire(3))
        await asyncio.sleep(0.01)
        assert lock.waiters == 2 and lock.owner == 1
        assert lock.release(1) is True
        await tb
        assert lock.owner == 2, 'FIFO: second arrival must be next'
        assert lock.release(2) is True
        await tc
        assert lock.owner == 3
        lock.release(3)
        assert not lock.busy()
    run(main())


def test_lock_cancelled_waiter_is_dropped_cleanly():
    async def main():
        lock = InputLock()
        await lock.acquire(1)
        tb = asyncio.create_task(lock.acquire(2))
        tc = asyncio.create_task(lock.acquire(3))
        await asyncio.sleep(0.01)
        tb.cancel()
        with pytest.raises(asyncio.CancelledError):
            await tb
        assert lock.waiters == 1            # B gone, no orphan future
        lock.release(1)
        await tc
        assert lock.owner == 3              # C unaffected by B's cancel
        lock.release(3)
    run(main())


def test_lock_ownerless_with_waiters_promotes_oldest_not_newcomer():
    """The Wave-3 fairness guard: in the transient ownerless state with a
    queue already waiting, a NEW arrival must never jump the queue."""
    async def main():
        lock = InputLock()
        f7 = asyncio.get_running_loop().create_future()
        f9 = asyncio.get_running_loop().create_future()
        lock._owner = None
        lock._waiters.append((7, f7))
        lock._waiters.append((9, f9))
        newcomer = asyncio.create_task(lock.acquire(5))
        await asyncio.sleep(0.01)
        assert lock.owner == 7              # oldest waiter promoted, not 5
        assert not newcomer.done()          # newcomer queued behind
        lock.release(7)
        await asyncio.sleep(0.01)
        assert lock.owner == 9              # FIFO among the rest: 9 before 5
        assert not newcomer.done()
        lock.release(9)
        await newcomer
        assert lock.owner == 5
        lock.release(5)
    run(main())


def test_lock_all_dead_waiters_drain_to_newcomer():
    async def main():
        lock = InputLock()
        dead = asyncio.get_running_loop().create_future()
        dead.cancel()
        lock._waiters.append((6, dead))
        assert await lock.acquire(5) is True   # every waiter dead -> free take
        lock.release(5)
    run(main())


def test_lock_force_release_drops_waiters():
    async def main():
        lock = InputLock()
        await lock.acquire(1)
        t2 = asyncio.create_task(lock.acquire(2))
        await asyncio.sleep(0.01)
        lock.force_release()                # kill_gui / shutdown path
        assert lock.owner is None and lock.waiters == 0
        await asyncio.sleep(0.01)
        assert t2.done() and t2.cancelled()  # waiter dropped, no orphan
    run(main())


# ---- per-job cancel hook ----------------------------------------------------
@pytest.mark.asyncio
async def test_on_job_cancelled_fires_for_full_scope_only():
    engine = get_engine()
    seen = []
    engine.on_job_cancelled = lambda rowid, jid: seen.append((rowid, jid))
    engine.pause()                          # keep workers from dequeuing
    try:
        snap = await engine.submit(text='queued job for cancel hook',
                                   priority='normal', source='text')
        # scope=gui releases only the lock — NOT a stop, no hook
        engine.cancel(snap['job'], scope='gui')
        assert seen == []
        # full scope -> hook with (rowid, external id)
        job = engine.cancel(snap['job'], scope='full')
        assert job['status'] == 'cancelled'
        assert seen == [(snap['id'], snap['job'])]
        # terminal -> immutable, no second fire
        engine.cancel(snap['job'], scope='full')
        assert len(seen) == 1
        # unknown ref -> no fire
        assert engine.cancel('nonsense') is None
        assert len(seen) == 1
    finally:
        engine.on_job_cancelled = None
        engine.resume()


@pytest.mark.asyncio
async def test_cancel_stops_only_that_jobs_speech():
    """loop.start_loop's listener interrupts the cancelled job's stream —
    other jobs' speech keeps playing. Shuts the engine down afterwards so
    no workers are left bound to this test's loop (RAM rule §14)."""
    from brain.voice import get_voice
    engine = get_engine()
    loop_mod.start_loop(hub=None)           # wires on_job_cancelled
    engine.pause()
    voice = get_voice()
    try:
        snap = await engine.submit(text='speech cancel target',
                                   priority='normal', source='text')
        mine = voice.interrupts.register(snap['job'])
        other = voice.interrupts.register('j_someone_else')
        engine.cancel(snap['job'], scope='full')
        assert mine.is_set(), "the cancelled job's stream must be stopped"
        assert not other.is_set(), "other jobs' streams are untouched"
        assert 'j_someone_else' in voice.interrupts._events
        assert not voice.interrupts._events.get(snap['job'])
    finally:
        voice.interrupts.done('j_someone_else')
        engine.resume()
        await engine.shutdown()
        engine.on_job_cancelled = None


# ---- end-to-end: FIFO lock + cancel-while-waiting ---------------------------
def test_lock_fairness_and_cancel_while_waiting():
    """A holds the lock, B and C queue FIFO; B is cancelled mid-wait: A and
    C complete in order, B never ran, the lock ends free. Driven over HTTP so
    everything executes inside the app's own event loop."""
    from fastapi.testclient import TestClient
    import brain.router as router
    from brain import tools as reg
    from brain.app import app

    order = []

    def hold(tag: str):
        time.sleep(0.25)                    # runs via asyncio.to_thread
        order.append(tag)
        return f'held {tag}'

    reg.register('t_lock_hold', hold, description='holds the input lock',
                 needs_lock=True,
                 schema={'type': 'object',
                         'properties': {'tag': {'type': 'string',
                                                'description': 'test tag'}},
                         'required': ['tag'], 'additionalProperties': False})

    tags = iter(['A', 'B', 'C'])

    async def chat(messages, tools=None, stream=False, purpose='chat'):
        # step 1 (no tool feedback yet) requests the lock tool; step 2 ends
        has_tool_result = any(m.get('role') == 'tool' for m in messages)

        async def gen():
            if has_tool_result:
                yield {'finish': 'stop', 'provider': 'fake', 'model': 'm'}
            else:
                tag = next(tags, 'C')
                yield {'finish': 'stop', 'provider': 'fake', 'model': 'm',
                       'tool_calls': [{'id': f'c_{tag}', 'type': 'function',
                                       'function': {
                                           'name': 't_lock_hold',
                                           'arguments': json.dumps({'tag': tag})}}]}
        return gen()

    old_chat = getattr(router, 'chat', None)
    router.chat = chat
    old_env = os.environ.get('RAPHAEL_DISABLE_ROUTER')
    os.environ.pop('RAPHAEL_DISABLE_ROUTER', None)
    fd, tok = tempfile.mkstemp(prefix='raphael-tok-conc-')
    with os.fdopen(fd, 'w') as f:
        f.write('conc-token-991')
    old_tok = os.environ.get('RAPHAEL_TOKEN_PATH')
    os.environ['RAPHAEL_TOKEN_PATH'] = tok

    def wait_http(client, pred, timeout=30.0, step=0.02):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            out = pred()
            if out:
                return out
            time.sleep(step)
        raise AssertionError(f'condition not met in {timeout}s')

    h = {'X-Raphael-Token': 'conc-token-991'}
    try:
        with TestClient(app) as client:
            def lock_stats():
                return client.get('/status', headers=h).json()['input_lock']

            wait_http(client, lambda: not lock_stats()['held'])
            # A: acquires the lock
            a = client.post('/jobs', json={'text': 'job A'}, headers=h
                            ).json()['job_id']
            wait_http(client, lambda: lock_stats()['held']
                      and lock_stats()['job'] == a)
            # B: queues behind A
            b = client.post('/jobs', json={'text': 'job B'}, headers=h
                            ).json()['job_id']
            wait_http(client, lambda: lock_stats()['waiting'] == 1)
            # C: queues behind B (FIFO)
            c = client.post('/jobs', json={'text': 'job C'}, headers=h
                            ).json()['job_id']
            wait_http(client, lambda: lock_stats()['waiting'] == 2)
            # cancel B WHILE it waits for the lock
            r = client.post(f'/jobs/{b}/cancel', json={'scope': 'full'},
                            headers=h)
            assert r.status_code == 200 and r.json()['cancelled'] is True
            wait_http(client, lambda: client.get(f'/jobs/{b}',
                                                 headers=h
                                                 ).json()['status'] == 'cancelled')
            # A and C both finish; FIFO order preserved (B never ran)
            wait_http(client, lambda: client.get(f'/jobs/{a}', headers=h
                                                 ).json()['status'] == 'done')
            wait_http(client, lambda: client.get(f'/jobs/{c}', headers=h
                                                 ).json()['status'] == 'done')
            assert client.get(f'/jobs/{b}', headers=h
                              ).json()['status'] == 'cancelled'
            assert order == ['A', 'C'], order
            final = lock_stats()
            assert final['held'] is False and final['waiting'] == 0
    finally:
        if old_chat is None:
            delattr(router, 'chat')
        else:
            router.chat = old_chat
        if old_env is None:
            os.environ.pop('RAPHAEL_DISABLE_ROUTER', None)
        else:
            os.environ['RAPHAEL_DISABLE_ROUTER'] = old_env
        if old_tok is None:
            os.environ.pop('RAPHAEL_TOKEN_PATH', None)
        else:
            os.environ['RAPHAEL_TOKEN_PATH'] = old_tok
        try:
            os.remove(tok)
        except OSError:
            pass
        reg._registry.pop('t_lock_hold', None)
        reg._META.pop('t_lock_hold', None)


# ---- Wave-5: job kinds + fan-out seam (engine-internal; wire pending) -------
@pytest.mark.asyncio
async def test_kind_and_parent_api_validated():
    engine = get_engine()
    started_here = not engine.started
    if started_here:
        engine.start(workers=1)
    engine.pause()
    try:
        snap = await engine.submit(text='kind me', priority='normal',
                                   source='text')
        assert engine.kind_of(snap['id']) is None
        assert engine.set_kind(snap['id'], 'simulation') is True
        assert engine.kind_of(snap['id']) == 'simulation'
        assert engine.kind_of(snap['job']) == 'simulation'   # ext id works
        # typos never silently become kinds
        assert engine.set_kind(snap['id'], 'simluation') is False
        assert engine.kind_of(snap['id']) == 'simulation'
        # submit kwargs
        snap2 = await engine.submit(text='typed', priority='normal',
                                    source='text', kind='analysis',
                                    parent=snap['job'])
        assert engine.kind_of(snap2['id']) == 'analysis'
        assert engine.parent_of(snap2['id']) == snap['job']
        assert snap2['kind'] == 'analysis' and snap2['parent'] == snap['job']
        # runner receives kind/parent on the snapshot
        seen = {}

        async def probe(job):
            seen['kind'] = job.get('kind')
            seen['parent'] = job.get('parent')

        engine.runner = probe
        engine.resume()
        await asyncio.sleep(0.05)
        assert seen == {'kind': 'analysis', 'parent': snap['job']}, seen
        engine.pause()
        engine.runner = None
        # cleanup: leave rows terminal
        for s in (snap, snap2):
            engine.cancel(s['job'])
    finally:
        engine.runner = None
        engine.resume()
        if started_here:
            await engine.shutdown()


@pytest.mark.asyncio
async def test_submit_fanout_correlates_children():
    engine = get_engine()
    started_here = not engine.started
    if started_here:
        engine.start(workers=1)
    engine.pause()
    made = []
    try:
        children = await engine.submit_fanout(
            'j_20261007_9999', ['angle one', 'angle two', 'angle three'],
            priority='normal', source='text')
        made = [c['id'] for c in children]
        assert len(children) == 3
        assert [c['parent'] for c in children] == ['j_20261007_9999'] * 3
        assert [c['kind'] for c in children] == ['analysis'] * 3
        assert engine.parent_of(children[0]['id']) == 'j_20261007_9999'
        assert all(engine.kind_of(c['id']) == 'analysis' for c in children)
        # admission order preserved (same priority -> submission order)
        assert [c['text'] for c in children] == ['angle one', 'angle two',
                                                 'angle three']
        # invalid kind coerced to analysis; empty input -> no jobs
        c2 = await engine.submit_fanout('j_20261007_9998', ['x'],
                                        kind='bogus')
        assert engine.kind_of(c2[0]['id']) == 'analysis'
        made.append(c2[0]['id'])
        assert await engine.submit_fanout('j_x', []) == []
    finally:
        engine.resume()
        for rowid in made:
            engine.cancel(rowid)
        if started_here:
            await engine.shutdown()

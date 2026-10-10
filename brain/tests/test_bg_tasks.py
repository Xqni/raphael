"""Wave 5U task 7 — background task runtime (charter §5.1 P1).
Acceptance: a background task runs while an unrelated chat turn finishes at
normal latency; status intents return real stage/progress; cancel works;
checkpoint persists; watchdog stalls/deadlines fire; surfacing is
idle-gated; speak:false silences TTS but never subtitles; /history is
token-auth + redacted.
"""
import asyncio
import json
import os
import tempfile
import time

import pytest
from fastapi.testclient import TestClient

from brain import fastpath
from brain import orbstate
from brain.app import app
from brain.jobs import store
from brain.jobs.engine import get_engine

TEST_TOKEN = 'bg-task-token-5'


@pytest.fixture(scope='module', autouse=True)
def token_path():
    fd, path = tempfile.mkstemp(prefix='raphael-test-token-bg-')
    with os.fdopen(fd, 'w') as f:
        f.write(TEST_TOKEN)
    old = os.environ.get('RAPHAEL_TOKEN_PATH')
    os.environ['RAPHAEL_TOKEN_PATH'] = path
    yield path
    if old is None:
        os.environ.pop('RAPHAEL_TOKEN_PATH', None)
    else:
        os.environ['RAPHAEL_TOKEN_PATH'] = old
    try:
        os.remove(path)
    except OSError:
        pass


@pytest.fixture
def engine_env():
    """Engine handle: the engine starts INSIDE each async scenario (its
    asyncio primitives need a running loop); the fixture only resets the
    task seams."""
    eng = get_engine()
    eng.task_runner = None
    eng._task_surfaces.clear()
    eng._task_progress.clear()
    yield eng
    eng.pause()
    eng.task_runner = None
    eng._task_surfaces.clear()
    if '_workers_cfg' in eng.__dict__:
        del eng._workers_cfg      # never leak the instance override


def _stop(eng):
    """Defensive: no engine task may outlive a scenario's loop."""
    for t in (list(eng._tasks.values()) + list(eng._workers)
              + list(eng._housekeeping) + list(eng._parked.values())):
        if not t.done():
            t.cancel()


def _boot(eng):
    """The engine singleton outlives asyncio.run loops, but its tasks do
    not — rebind when the previous loop died with its workers."""
    if eng.started and (not eng._workers
                        or all(w.done() for w in eng._workers)):
        eng._running = False
        eng._workers = []
        eng._housekeeping = []
        eng._tasks.clear()
        eng._parked.clear()
        eng._queue = None
        eng._queue_loop = None
        eng._pause_event = None
    if not eng.started:
        eng.start(workers=4)
    eng.pause()


# ---- packet + checkpoint ---------------------------------------------------
def test_submit_task_persists_packet_checkpoint(engine_env):
    eng = engine_env

    async def go():
        return await eng.submit_task({'goal': 'summarize inbox',
                                      'allow_tools': ['web_fetch'],
                                      'deadline_s': 60,
                                      'budget': {'wall_s': 120}})
    snap = asyncio.run(go())
    assert eng.kind_of(snap['id']) == 'task'
    cp = store.get_checkpoint(snap['id'])
    assert cp['packet']['goal'] == 'summarize inbox'
    assert cp['packet']['allow_tools'] == ['web_fetch']
    eng.cancel(snap['job'])


# ---- the acceptance: chat is never blocked by a task -----------------------
def test_acceptance_task_runs_while_chat_stays_fast(engine_env, monkeypatch):
    eng = engine_env

    async def scenario():
        _boot(eng)
        release = asyncio.Event()
        ran_notes = []

        async def task_runner(packet, report):
            await report(progress=0.4, stage='fetching', note='step 1',
                         step=1)
            await asyncio.wait_for(release.wait(), timeout=10)
            await report(progress=1.0, stage='summarizing', note='step 2',
                         step=2)
            return f'Done with {packet.get("goal")}'

        eng.task_runner = task_runner

        async def chat_runner(job):
            await asyncio.sleep(0.01)
            store.transition(job['id'], 'done', stage='done', progress=1.0,
                             result='chat answer')

        eng.runner = chat_runner
        eng.resume()
        task = await eng.submit_task({'goal': 'long research', 'deadline_s': 60})
        # wait until the task is RUNNING and has reported step 1
        for _ in range(200):
            row = store.get_job(task['id']) or {}
            if row.get('stage') == 'fetching':
                break
            await asyncio.sleep(0.01)
        assert (store.get_job(task['id']) or {}).get('stage') == 'fetching'
        # unrelated chat turn while the task holds: finishes immediately
        t0 = time.monotonic()
        chat = await eng.submit('hello, what is 2+2?', priority='user_facing')
        for _ in range(200):
            if (store.get_job(chat['id']) or {}).get('status') == 'done':
                break
            await asyncio.sleep(0.01)
        assert (store.get_job(chat['id']) or {}).get('status') == 'done'
        assert (time.monotonic() - t0) < 3.0, 'chat must not wait on the task'
        # 'how is that task going' -> real stage/progress from the fast path
        res = fastpath.run_intent('how is that task going',
                                  fastpath.IntentCtx(engine=eng))
        assert res is not None and 'long research' in res.text
        assert 'fetching' in res.text and '40%' in res.text, res.text
        # 'cancel the research task' matches by goal substring
        res2 = fastpath.run_intent('cancel the research task',
                                   fastpath.IntentCtx(engine=eng))
        assert res2 is not None and 'Cancelled' in res2.text, res2.text
        for _ in range(200):
            if (store.get_job(task['id']) or {}).get('status') == 'cancelled':
                break
            await asyncio.sleep(0.01)
        assert (store.get_job(task['id']) or {}).get('status') == 'cancelled'
        release.set()
        _stop(eng)

    asyncio.run(scenario())
    eng.runner = None


# ---- background cap --------------------------------------------------------
def test_max_background_cap_holds(engine_env, monkeypatch):
    eng = engine_env
    monkeypatch.setattr(eng, '_workers_cfg', lambda: (1, 90.0))

    async def scenario():
        _boot(eng)
        gate = asyncio.Event()

        async def task_runner(packet, report):
            await asyncio.wait_for(gate.wait(), timeout=10)
            return 'ok'

        eng.task_runner = task_runner
        eng.resume()
        t1 = await eng.submit_task({'goal': 'one'})
        t2 = await eng.submit_task({'goal': 'two'})
        await asyncio.sleep(0.4)
        s1 = (store.get_job(t1['id']) or {}).get('status')
        s2 = (store.get_job(t2['id']) or {}).get('status')
        assert s1 == 'running' and s2 in ('queued', 'waiting_lock'), (s1, s2)
        gate.set()
        for t in (t1, t2):
            for _ in range(200):
                if (store.get_job(t['id']) or {}).get('status') == 'done':
                    break
                await asyncio.sleep(0.01)
            eng.cancel(t['job'])
        _stop(eng)

    asyncio.run(scenario())
    eng.task_runner = None


# ---- watchdog: stall + deadline (single tick, extracted) -------------------
def test_watchdog_tick_stalls_and_deadline_cancels(engine_env):
    eng = engine_env
    eng._workers_cfg = lambda: (2, 0.05)   # tiny stall window; no cap fight

    async def scenario():
        _boot(eng)
        try:
            async def stuck_runner(packet, report):
                await asyncio.sleep(30)      # never reports (until cancelled)
            eng.task_runner = stuck_runner
            eng.resume()
            task = await eng.submit_task({'goal': 'stuck thing',
                                          'deadline_s': 300})
            for _ in range(200):
                if (store.get_job(task['id']) or {}).get('status') == 'running':
                    break
                await asyncio.sleep(0.01)
            assert (store.get_job(task['id']) or {}).get('status') == 'running'
            # stall: heartbeat long stale -> one tick marks it stalled
            eng._task_progress[task['id']] = time.time() - 5.0
            await eng._task_watchdog_tick()
            assert (store.get_job(task['id']) or {}).get('status') == 'stalled'
            # deadline: fresh task, deadline long past -> tick cancels it
            task2 = await eng.submit_task({'goal': 'expired',
                                           'deadline_s': 300})
            for _ in range(200):
                if (store.get_job(task2['id']) or {}).get('status') == 'running':
                    break
                await asyncio.sleep(0.01)
            assert (store.get_job(task2['id']) or {}).get('status') == 'running'
            cp = store.get_checkpoint(task2['id']) or {}
            store.set_checkpoint(task2['id'],
                                 {**cp, 'started_ts': time.time() - 5,
                                  'packet': {**(cp.get('packet') or {}),
                                             'deadline_s': 0.01}})
            await eng._task_watchdog_tick()
            for _ in range(200):
                if (store.get_job(task2['id']) or {}).get('status') == 'cancelled':
                    break
                await asyncio.sleep(0.01)
            assert (store.get_job(task2['id']) or {}).get('status') == 'cancelled'
        finally:
            for jid in [task.get('job'), task2.get('job')] \
                    if 'task2' in dir() else [task.get('job')]:
                try:
                    eng.cancel(jid)
                except Exception:  # noqa: BLE001
                    pass
            _stop(eng)
            await asyncio.sleep(0.05)

    asyncio.run(scenario())
    eng.task_runner = None
    if '_workers_cfg' in eng.__dict__:
        del eng._workers_cfg


# ---- redirect: cancel + resubmit same packet -------------------------------
def test_redirect_task_keeps_packet(engine_env):
    eng = engine_env

    async def scenario():
        _boot(eng)
        task = await eng.submit_task({'goal': 'old goal', 'deadline_s': 60,
                                      'allow_tools': ['web_fetch']})
        res = eng.redirect_task(task['id'], 'new goal only last week')
        assert res and res['old'] == task['job']
        assert (store.get_job(task['id']) or {}).get('status') == 'cancelled'
        await asyncio.sleep(0.2)       # resubmit task lands
        rows = [j for j in store.list_jobs()
                if eng.kind_of(j['id']) == 'task'
                and j['id'] != task['id']
                and j['status'] != 'cancelled']
        assert rows, store.list_jobs()
        cp = store.get_checkpoint(rows[-1]['id'])
        assert cp['packet']['goal'] == 'new goal only last week'
        assert cp['packet']['allow_tools'] == ['web_fetch']  # packet survived
        for j in rows:
            eng.cancel(j['job'])
        _stop(eng)

    asyncio.run(scenario())


# ---- surfacing is idle-gated ----------------------------------------------
def test_task_surfaces_queue_and_voice_idle_gate(engine_env):
    eng = engine_env

    async def scenario():
        _boot(eng)
        async def quick_runner(packet, report):
            await report(progress=1.0, note='all done')
            return 'Finished the archive sweep'
        eng.task_runner = quick_runner
        eng.resume()
        task = await eng.submit_task({'goal': 'quick sweep'})
        for _ in range(200):
            if (store.get_job(task['id']) or {}).get('status') == 'done':
                break
            await asyncio.sleep(0.01)
        assert eng._task_surfaces, 'done task must queue a surface'
        assert 'archive sweep' in eng._task_surfaces[0]['summary']
        # gate: speaking -> NOT idle -> pump must hold
        orbstate._speaking = 1
        assert orbstate.voice_idle() is False
        orbstate._speaking = 0
        orbstate._listening = False
        assert orbstate.voice_idle() is True
        eng._task_surfaces.clear()
        _stop(eng)

    asyncio.run(scenario())
    eng.task_runner = None


# ---- speak:false -----------------------------------------------------------
def test_speaker_muted_streams_subtitles_only():
    class _Voice:
        class interrupts:
            @staticmethod
            def register(job_id):
                return lambda: None

            @staticmethod
            def done(job_id):
                return None

        async def speak(self, *a, **kw):
            raise AssertionError('muted speaker must never speak')

    async def scenario():
        from brain import loop as loop_mod
        from brain.ws import get_hub
        hub = get_hub()

        class _Ws:
            def __init__(self):
                self.texts = []

            async def send_text(self, data):
                self.texts.append(json.loads(data))

            async def send_bytes(self, data):
                pass

            async def close(self):
                pass

        ws = _Ws()
        from brain.ws import Session
        s = Session(ws, '127.0.0.1')
        s.authed = True
        s.role = 'cli'
        hub._sessions[s.sid] = s
        try:
            async with loop_mod._SentenceSpeaker(hub, 'j_mute', _Voice(),
                                                 muted=True) as spk:
                spk.push('First sentence.')
                spk.push('Second sentence.')
                spk.finish() if hasattr(spk, 'finish') else None
                await asyncio.sleep(0.05)
            subs = [t for t in ws.texts if t.get('type') == 'subtitle']
            speaks = [t for t in ws.texts if t.get('type') == 'speak']
            assert len(subs) == 2, ws.texts          # text still streams
            assert speaks == []                      # TTS never called
        finally:
            hub._sessions.pop(s.sid, None)

    asyncio.run(scenario())


def test_engine_mute_roundtrip(engine_env):
    eng = engine_env
    snap = store.create_job(text='mute me', priority='normal')
    eng.set_muted(snap['id'], True)
    assert eng.is_muted(snap['job']) is True
    eng.set_muted(snap['id'], False)
    assert eng.is_muted(snap['job']) is False
    store.transition(snap['id'], 'cancelled', stage='done', progress=1.0)


# ---- /history (G) ----------------------------------------------------------
def test_history_requires_token_and_redacts(monkeypatch):
    h = {'X-Raphael-Token': TEST_TOKEN}
    with TestClient(app) as client:
        assert client.get('/history').status_code == 401
        from brain.memory import conversation as _conv
        monkeypatch.setattr(
            _conv, 'recent_turns',
            lambda limit=20: [{'user': 'my password: hunter2',
                               'assistant': 'Understood — not stored.',
                               'ts': 'now', 'job': 'j_1', 'task_kind': 'chat'}])
        r = client.get('/history?limit=5', headers=h)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body['ok'] is True and body['count'] == 1
        assert 'hunter2' not in json.dumps(body), body

"""Proactive Notice events (PROTOCOL §3 — APPROVED 2026-10-07, scope:
frame as proposed, roles ui+cli ONLY, emitters 1 restart-recovery and 2
ratelimited provider outage/recovery; emitter 3 DEFERRED)."""
import asyncio
import json
import os
import tempfile
import time

import pytest
from fastapi.testclient import TestClient

from brain import notice
from brain.ws import Session, get_hub


class FakeWs:
    def __init__(self):
        self.texts = []

    async def send_text(self, data):
        self.texts.append(json.loads(data))

    async def send_bytes(self, data):
        pass

    async def close(self):
        pass


def attach(role):
    hub = get_hub()
    ws = FakeWs()
    s = Session(ws, '127.0.0.1')
    s.authed = True
    s.role = role
    hub._sessions[s.sid] = s
    return s


def notices(sess):
    return [t for t in sess.ws.texts if t.get('type') == 'notice']


async def drain(n=6):
    for _ in range(n):
        await asyncio.sleep(0)


@pytest.fixture(autouse=True)
def _clean_notice_state():
    notice.reset_for_tests()
    yield
    hub = get_hub()
    for sid in [k for k, v in hub._sessions.items()
                if isinstance(v.ws, FakeWs)]:
        hub._sessions.pop(sid, None)
    notice.reset_for_tests()


# ---- frame shape (exactly as approved) --------------------------------------
def test_frame_shape_exactly_as_approved():
    f = notice.build('Heads up.', level='warn', job='j_20261007_0001')
    assert set(f.keys()) == {'type', 'v', 'text', 'level', 'ts', 'job'}
    assert f == {'type': 'notice', 'v': 1, 'text': 'Heads up.',
                 'level': 'warn', 'ts': f['ts'], 'job': 'j_20261007_0001'}
    assert isinstance(f['ts'], int) and f['ts'] > 1_700_000_000_000
    # job is optional and omitted when absent
    f2 = notice.build('ok')
    assert set(f2.keys()) == {'type', 'v', 'text', 'level', 'ts'}
    assert notice.build('x', level='bogus')['level'] == 'info'


# ---- roles: ui + cli ONLY (body does not render text) -----------------------
@pytest.mark.asyncio
async def test_roles_are_ui_and_cli_only():
    ui, cli, body = attach('ui'), attach('cli'), attach('body')
    assert notice.emit('Recovered.', level='warn')
    await drain()
    assert len(notices(ui)) == 1 and len(notices(cli)) == 1
    assert notices(body) == [], 'body must never receive notice frames'
    assert notices(ui)[0]['text'] == 'Recovered.'


# ---- ratelimit --------------------------------------------------------------
@pytest.mark.asyncio
async def test_ratelimit_per_key_cooldown():
    ui = attach('ui')
    assert notice.emit('first', key='k1', cooldown_s=60) is True
    assert notice.emit('second', key='k1', cooldown_s=60) is False  # cooled down
    assert notice.emit('other key fires', key='k2', cooldown_s=60) is True
    assert notice.emit('no key always fires') is True
    await drain()
    texts = [n['text'] for n in notices(ui)]
    assert texts == ['first', 'other key fires', 'no key always fires']


# ---- emitter 2: provider outage / recovery ----------------------------------
@pytest.mark.asyncio
async def test_provider_outage_pair_is_ratelimited():
    ui = attach('ui')
    assert notice.provider_down() is True          # warn emitted, state=down
    assert notice.provider_down() is False         # still down -> silent
    assert notice.provider_up() is True            # recovery info emitted
    assert notice.provider_up() is False           # already up -> silent
    # a new outage WITHIN 10 min is suppressed -> max 1 pair / 10 min
    assert notice.provider_down() is False
    await drain()
    levels = [(n['level'], n['text']) for n in notices(ui)]
    assert levels == [('warn', 'Cloud providers unreachable — retrying.'),
                      ('info', 'Cloud providers reachable again.')], levels


@pytest.mark.asyncio
async def test_provider_notice_carries_no_details():
    """Presence-only: no codes, no provider names, no key/log data."""
    ui = attach('ui')
    notice.provider_down()
    await drain()
    f = notices(ui)[0]
    assert set(f.keys()) == {'type', 'v', 'text', 'level', 'ts'}
    assert 'E_' not in f['text'] and 'groq' not in f['text'].lower()


@pytest.mark.asyncio
async def test_provider_cooldown_expires_then_new_pair(monkeypatch):
    ui = attach('ui')
    t = {'now': 0.0}
    monkeypatch.setattr(notice.time, 'monotonic', lambda: t['now'])
    assert notice.provider_down() is True
    assert notice.provider_up() is True
    t['now'] = notice.PROVIDER_COOLDOWN_S + 1        # window passed
    assert notice.provider_down() is True            # new pair allowed
    await drain()
    assert len(notices(ui)) == 3


# ---- llm seam wiring ---------------------------------------------------------
@pytest.mark.asyncio
async def test_llm_facade_wires_provider_hooks(monkeypatch):
    import brain.router as router
    from brain import llm as llm_mod
    calls = {'up': 0, 'down': 0}
    monkeypatch.setattr(notice, 'provider_up',
                        lambda: calls.__setitem__('up', calls['up'] + 1))
    monkeypatch.setattr(notice, 'provider_down',
                        lambda: calls.__setitem__('down', calls['down'] + 1))
    monkeypatch.delenv('RAPHAEL_DISABLE_ROUTER', raising=False)

    async def ok_chat(messages, tools=None, stream=False, purpose='chat'):
        if stream:
            async def gen():
                yield {'delta': 'hi'}
                yield {'finish': 'stop', 'provider': 'p', 'model': 'm'}
            return gen()
        return {'text': 'ok', 'finish': 'stop'}

    async def down_chat(messages, tools=None, stream=False, purpose='chat'):
        if stream:
            async def gen():
                yield {'finish': 'error', 'code': 'E_OFFLINE',
                       'error': 'no net'}
            return gen()
        return {'error': 'no net', 'code': 'E_OFFLINE'}

    monkeypatch.setattr(router, 'chat', ok_chat, raising=False)
    res = await llm_mod.chat([{'role': 'user', 'content': 'x'}])
    assert res.ok and calls['up'] == 1 and calls['down'] == 0

    monkeypatch.setattr(router, 'chat', down_chat, raising=False)
    res = await llm_mod.chat([{'role': 'user', 'content': 'x'}])
    assert not res.ok and calls['down'] == 1

    stream = await llm_mod.chat([{'role': 'user', 'content': 'x'}], stream=True)
    frames = [f async for f in stream]
    assert frames[-1]['finish'] == 'error' and calls['down'] == 2
    assert calls['up'] == 1


@pytest.mark.asyncio
async def test_disabled_router_is_not_an_outage(monkeypatch):
    """RAPHAEL_DISABLE_ROUTER is a deliberate switch, not a provider outage."""
    from brain import llm as llm_mod
    calls = {'up': 0, 'down': 0}
    monkeypatch.setattr(notice, 'provider_up',
                        lambda: calls.__setitem__('up', calls['up'] + 1))
    monkeypatch.setattr(notice, 'provider_down',
                        lambda: calls.__setitem__('down', calls['down'] + 1))
    monkeypatch.setenv('RAPHAEL_DISABLE_ROUTER', '1')
    res = await llm_mod.chat([{'role': 'user', 'content': 'x'}])
    assert not res.ok
    assert calls == {'up': 0, 'down': 0}


# ---- emitter 1: boot recovery reaches the first ui/cli client ---------------
def test_boot_recovery_notice_flushed_to_first_ui_client():
    # a non-terminal job left behind -> lifespan marks it interrupted.
    # Count dynamically: earlier suites may leave orphans that this boot
    # also marks (they are all legitimately interrupted).
    from brain.jobs import store
    leftovers = [j for j in store.list_jobs()
                 if j['status'] not in store.TERMINAL]
    stale = store.create_job('stale job from previous run', source='text')
    assert stale['status'] == 'queued'

    token_fd, token_path = tempfile.mkstemp(prefix='raphael-tok-notice-')
    with os.fdopen(token_fd, 'w') as f:
        f.write('notice-token-321')
    old_tok = os.environ.get('RAPHAEL_TOKEN_PATH')
    os.environ['RAPHAEL_TOKEN_PATH'] = token_path

    def recv(ws, timeout=5.0):
        import anyio

        async def inner():
            with anyio.fail_after(timeout):
                return await ws._send_rx.receive()

        m = ws.portal.call(inner)
        t = m.get('text')
        if t is None:
            t = m.get('bytes', b'').decode()
        return json.loads(t)

    def recv_until(ws, pred, limit=40, timeout=5):
        for _ in range(limit):
            m = recv(ws, timeout=timeout)
            if m.get('type') == 'ping':
                continue
            if pred(m):
                return m
        raise AssertionError('not found')

    try:
        from brain.app import app
        with TestClient(app) as client:
            # engine marked the stale job + queued the boot notice
            assert store.get_job(stale['id'])['status'] == 'interrupted'
            assert notice.pending_count() == 1
            with client.websocket_connect('/ws') as ws_ui:
                ws_ui.send_text(json.dumps({'type': 'auth', 'v': 1,
                                            'token': 'notice-token-321',
                                            'role': 'ui', 'client': 't',
                                            'client_v': '1'}))
                auth = recv(ws_ui, timeout=5)
                assert auth['type'] == 'auth_ok'
                n = recv_until(ws_ui, lambda m: m.get('type') == 'notice')
                assert n['level'] == 'warn'
                assert n['v'] == 1
                expected_n = len(leftovers) + 1
                assert f'Interrupted tasks: {expected_n}.' in n['text']
                assert 'Recovered from an unexpected shutdown' in n['text']
                assert notice.pending_count() == 0   # drained on first auth
            # a body session never receives it (already drained; roles rule)
            with client.websocket_connect('/ws') as ws_body:
                ws_body.send_text(json.dumps({'type': 'auth', 'v': 1,
                                              'token': 'notice-token-321',
                                              'role': 'body', 'client': 't',
                                              'client_v': '1'}))
                assert recv(ws_body, timeout=5)['type'] == 'auth_ok'
                # any further frame for body must not be a notice
                body_frames = []
                try:
                    for _ in range(3):
                        body_frames.append(recv(ws_body, timeout=1.0))
                except Exception:  # noqa: BLE001 — timeout = no more frames
                    pass
                assert all(f.get('type') != 'notice' for f in body_frames)
    finally:
        if old_tok is None:
            os.environ.pop('RAPHAEL_TOKEN_PATH', None)
        else:
            os.environ['RAPHAEL_TOKEN_PATH'] = old_tok
        try:
            os.remove(token_path)
        except OSError:
            pass


# ---- Wave-4: outage-storm drill ---------------------------------------------
def test_outage_storm_bounded_single_warn_pair():
    """1000 rapid provider failures + a recovery storm: at most ONE warn and
    ONE info within the 10-min window; state never grows unbounded."""
    notice.reset_for_tests()
    warns = infos = 0
    for _ in range(1000):
        if notice.provider_down():
            warns += 1
    for _ in range(1000):
        if notice.provider_up():
            infos += 1
    # storms AFTER the pair (still in cooldown) are fully suppressed
    for _ in range(1000):
        if notice.provider_down():
            warns += 1
    assert warns == 1 and infos == 1, (warns, infos)
    assert notice.pending_count() == 0     # none of these were pending
    notice.reset_for_tests()


def test_emit_without_running_loop_is_fail_silent():
    """A notice fired while no event loop is running (shutdown races) must
    neither raise nor corrupt state."""
    notice.reset_for_tests()
    assert notice.emit('during teardown') is True      # no loop -> no-op fanout
    assert notice.provider_down() is True
    assert notice.provider_up() is True
    notice.reset_for_tests()


def test_pending_queue_is_bounded():
    notice.reset_for_tests()
    for i in range(20):
        notice.emit(f'boot {i}', pending=True)
    assert notice.pending_count() <= notice._PENDING_CAP
    notice.reset_for_tests()


@pytest.mark.asyncio
async def test_storm_during_stream_failure_emits_once(monkeypatch):
    """A stream that dies mid-answer 50 times in a row: exactly one outage
    notice through the real llm seam."""
    import brain.router as router
    from brain import llm as llm_mod
    notice.reset_for_tests()
    ui = attach('ui')

    async def dying_chat(messages, tools=None, stream=False, purpose='chat'):
        async def gen():
            yield {'delta': 'partial'}
            yield {'finish': 'error', 'code': 'E_PROVIDER_5XX',
                   'error': 'boom'}
        return gen()

    monkeypatch.setattr(router, 'chat', dying_chat, raising=False)
    monkeypatch.delenv('RAPHAEL_DISABLE_ROUTER', raising=False)
    for _ in range(50):
        stream = await llm_mod.chat([{'role': 'user', 'content': 'x'}],
                                    stream=True)
        _ = [f async for f in stream]
    await drain()
    warns = [n for n in notices(ui) if n['level'] == 'warn']
    assert len(warns) == 1, len(warns)
    notice.reset_for_tests()

"""orb_state emission tests (INTERFACES §e): EVERY transition emits a frame
carrying state/jobs_active/mode/shape_hint/task_kind (+ provider/model once
known), asserted against a FAKE ui client that records the exact sequence.

No network, no providers, no mic — the fake ui client is a recording stand-in
for the orb.
"""
import asyncio
import json
import os
import tempfile
import time

import pytest
from fastapi.testclient import TestClient

from brain import orbstate
from brain.app import app
from brain.jobs.engine import get_engine
from brain.ws import Session, get_hub

TEST_TOKEN = 'orb-state-token-789'


# ---- fake ui client ---------------------------------------------------------
class FakeWs:
    def __init__(self):
        self.texts = []
        self.binary = []
        self.closed = False

    async def send_text(self, data):
        self.texts.append(json.loads(data))

    async def send_bytes(self, data):
        self.binary.append(data)

    async def close(self):
        self.closed = True


def make_fake_ui(hub):
    """Inject an authed role=ui session that records every frame."""
    ws = FakeWs()
    s = Session(ws, '127.0.0.1')
    s.authed = True
    s.role = 'ui'
    s.client = 'fake-orb'
    hub._sessions[s.sid] = s
    return s


async def drain(n=6):
    """Let broadcast tasks (loop.create_task) run."""
    for _ in range(n):
        await asyncio.sleep(0)


def orb_frames(sess):
    return [t for t in sess.ws.texts if t.get('type') == 'orb_state']


@pytest.fixture
def fake_ui():
    hub = get_hub()
    orbstate.reset_for_tests()
    sess = make_fake_ui(hub)
    engine = get_engine()
    engine.sink = lambda frame: hub.broadcast(frame)
    engine.on_state = lambda frame: hub.refresh_orb_state()
    hub.engine = engine
    orbstate.attach(hub)
    orbstate.finish_boot()
    orbstate.build(engine=engine)   # consume the settle baseline like the
    #                                  lifespan refresh does (this fixture's
    #                                  tests derive states directly)
    yield sess, hub, engine
    hub._sessions.pop(sess.sid, None)
    orbstate.reset_for_tests()
    orbstate.finish_boot()   # never leave the app "booting" for later tests


@pytest.mark.asyncio
async def test_sequence_boot_idle_listening_idle(fake_ui):
    sess, hub, engine = fake_ui
    # 1. boot snapshot while engine not ready (§e)
    orbstate.emit('starting', hub=hub, engine=engine)
    # 2. initial snapshot after boot: jobs_active==0 -> idle
    orbstate.finish_boot()
    orbstate.refresh(hub=hub, engine=engine)
    # 3. mic audio_start(wake) -> listening ; audio_end with no job -> idle
    orbstate.listening_on()
    orbstate.emit('listening', hub=hub, engine=engine)
    orbstate.listening_off()
    orbstate.refresh(hub=hub, engine=engine)
    await drain()

    states = [f['state'] for f in orb_frames(sess)]
    assert states == ['starting', 'idle', 'listening', 'idle'], states


@pytest.mark.asyncio
async def test_every_frame_carries_the_contract_fields(fake_ui):
    sess, hub, engine = fake_ui
    orbstate.finish_boot()
    orbstate.set_task('llm')
    orbstate.set_provider('groq', 'llama-x')
    orbstate.refresh(hub=hub, engine=engine)
    orbstate.set_task('gui')
    orbstate.emit('acting', hub=hub, engine=engine)
    orbstate.listening_on()
    orbstate.emit('listening', hub=hub, engine=engine)
    await drain()

    frames = orb_frames(sess)
    assert frames, 'no orb_state frames recorded'
    for f in frames:
        assert f['state'] in orbstate.VALID_STATES, f
        assert isinstance(f['jobs_active'], int), f
        assert f['mode'] in ('normal', 'private', 'paused'), f
        assert f['shape_hint'] in ('circle', 'triangle', 'square', 'pentagon',
                                   'hexagon', 'octagram'), f
        assert f['task_kind'] in ('system', 'files', 'web', 'media', 'llm',
                                  'gui', 'none'), f
        assert f['provider'] == 'groq' and f['model'] == 'llama-x', f
    # CIRCLE-ONLY hold (integrator decision 2026-10-07): task_kind still
    # varies, shape_hint is pinned to circle while the hold is on
    assert frames[0]['task_kind'] == 'llm' and frames[0]['shape_hint'] == 'circle'
    assert frames[1]['task_kind'] == 'gui' and frames[1]['shape_hint'] == 'circle'


@pytest.mark.asyncio
async def test_error_is_transient_then_idle(fake_ui):
    sess, hub, engine = fake_ui
    orbstate.finish_boot()
    orbstate.refresh(hub=hub, engine=engine)          # idle
    orbstate.mark_error()
    orbstate.refresh(hub=hub, engine=engine)          # error
    orbstate._error_until = time.monotonic() - 1      # simulate linger expiry
    orbstate.refresh(hub=hub, engine=engine)          # back to idle
    await drain()
    states = [f['state'] for f in orb_frames(sess)]
    assert states == ['idle', 'error', 'idle'], states


@pytest.mark.asyncio
async def test_private_is_a_mode_overlay_not_a_state(fake_ui):
    from brain.mode import get_mode
    sess, hub, engine = fake_ui
    orbstate.finish_boot()
    get_mode().set('private_on', persist=False)
    try:
        orbstate.refresh(hub=hub, engine=engine)
        await drain()
        f = orb_frames(sess)[-1]
        assert f['state'] == 'idle'          # overlay, not a state (§e)
        assert f['mode'] == 'private'
        assert f['private'] is True
    finally:
        get_mode().set('private_off', persist=False)


# ---- end-to-end: real loop, real WS ui client -------------------------------
@pytest.fixture(scope='module')
def token_path():
    fd, path = tempfile.mkstemp(prefix='raphael-test-token-orb-')
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


def _recv_json(ws, timeout=5.0):
    import anyio
    from starlette.websockets import WebSocketDisconnect

    async def _inner():
        with anyio.fail_after(timeout):
            return await ws._send_rx.receive()

    message = ws.portal.call(_inner)
    if message['type'] == 'websocket.close':
        raise WebSocketDisconnect(code=message.get('code', 1000),
                                   reason=message.get('reason', ''))
    text = message.get('text')
    if text is None:
        text = message.get('bytes', b'').decode()
    return json.loads(text)


def _recv_until(ws, pred, skip=('ping',), limit=60, timeout=8):
    frames = []
    for _ in range(limit):
        msg = _recv_json(ws, timeout=timeout)
        frames.append(msg)
        if msg.get('type') in skip:
            continue
        if pred(msg):
            return msg, frames
    raise AssertionError(f'predicate not met; types={[f.get("type") for f in frames]}')


def _auth(ws, role):
    ws.send_text(json.dumps({'type': 'auth', 'v': 1, 'token': TEST_TOKEN,
                             'role': role, 'client': 'test', 'client_v': '1.0'}))
    return _recv_json(ws, timeout=5)


def test_e2e_sequence_thinking_speaking_idle_reaches_ui(token_path):
    """A real job's orb sequence as seen by a ui client: thinking -> speaking
    -> idle, with the §e fields on every frame."""
    orbstate.reset_for_tests()
    orbstate.finish_boot()
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as ws_ui:
            assert _auth(ws_ui, 'ui')['type'] == 'auth_ok'
            with client.websocket_connect('/ws') as ws_cli:
                assert _auth(ws_cli, 'cli')['type'] == 'auth_ok'
                ws_cli.send_text(json.dumps({'type': 'command', 'v': 1,
                                             'text': 'echo orb sequence',
                                             'source': 'text'}))
                ack, _ = _recv_until(ws_cli, lambda m: m.get('type') == 'ack')
                seen = []
                done_seen = False
                speak_seen = False
                idle_after_speak = False
                for _ in range(120):
                    msg, _ = _recv_until(
                        ws_ui,
                        lambda m: m.get('type') in ('orb_state', 'job_event'),
                        limit=100, timeout=10)
                    if msg.get('type') == 'job_event':
                        if msg.get('status') in ('done', 'failed'):
                            done_seen = True
                        continue
                    seen.append(msg)
                    if msg['state'] == 'speaking':
                        speak_seen = True
                    elif msg['state'] == 'idle' and speak_seen:
                        idle_after_speak = True
                    if done_seen and speak_seen and idle_after_speak:
                        break
                # contract fields on every frame
                for f in seen:
                    assert f['jobs_active'] >= 0 and f['mode'] in (
                        'normal', 'private', 'paused'), f
                    assert 'shape_hint' in f and 'task_kind' in f, f
                states = [f['state'] for f in seen]
                assert 'thinking' in states, states
                assert 'speaking' in states, states
                assert states.index('thinking') < states.index('speaking'), states
                assert done_seen and idle_after_speak, states
    orbstate.reset_for_tests()
    orbstate.finish_boot()


def test_e2e_state_req_returns_full_frame(token_path):
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as ws:
            _auth(ws, 'ui')
            ws.send_text(json.dumps({'type': 'state_req', 'v': 1}))
            msg, _ = _recv_until(ws, lambda m: m.get('type') == 'orb_state'
                                  and 'server_v' in m)   # state_req reply
            assert msg['state'] in orbstate.VALID_STATES, msg
            assert isinstance(msg['jobs_active'], int)
            assert msg['mode'] in ('normal', 'private', 'paused')
            assert msg['shape_hint'] and msg['task_kind']
            assert msg['server_v'].startswith('brain-')


# ---- Bug E (Wave-3 P0): speaking must HOLD over listening mid-utterance ----
@pytest.mark.asyncio
async def test_boot_settle_first_frame_is_idle_then_activity(fake_ui):
    """USER DIRECTIVE (2026-10-07): after finish_boot() the FIRST derived
    frame is the settled idle baseline — never thinking/confirm from leftover
    jobs; the next frame may then show activity."""
    from brain.jobs import store
    sess, hub, engine = fake_ui
    # leftover from a crash: a job whose status would derive CONFIRM
    leftover = store.create_job('crashed while confirming', source='text')
    store.transition(leftover['id'], 'awaiting_confirm', stage='routing',
                     progress=0.1)
    try:
        # arm the settle (as lifespan does after boot)
        orbstate.finish_boot()
        # sanity: derivation WOULD show activity right now...
        assert orbstate.derive_state(engine) == 'confirm'
        # ...but the first emitted frame is the idle baseline
        orbstate.refresh(hub=hub, engine=engine)
        # the next frame derives normally from reality (activity may show)
        orbstate.refresh(hub=hub, engine=engine)
        await drain()
        states = [f['state'] for f in orb_frames(sess)]
        assert states[0] == 'idle', states
        assert states[1] == 'confirm', states
    finally:
        store.transition(leftover['id'], 'cancelled', stage='done',
                         progress=1.0)


@pytest.mark.asyncio
async def test_shape_hint_circle_only_hold(fake_ui):
    """Integrator decision 2026-10-07: EVERY task_kind emits shape_hint
    'circle' while the central hold is on — task_kind itself still varies,
    the config map stays intact for future re-enable."""
    sess, hub, engine = fake_ui
    orbstate.finish_boot()
    for kind in ('llm', 'gui', 'system', 'web', 'analysis', 'simulation',
                 'none'):
        orbstate.set_task(kind)
        orbstate.refresh(hub=hub, engine=engine)
    await drain()
    frames = orb_frames(sess)
    kinds = [f['task_kind'] for f in frames]
    shapes = [f['shape_hint'] for f in frames]
    assert kinds == ['llm', 'gui', 'system', 'web', 'analysis', 'simulation',
                     'none'], kinds
    assert shapes == ['circle'] * len(kinds), shapes   # hold: circle ONLY
    # the map itself is untouched (future re-enable) and the hold flag is on
    from brain import config as appcfg
    shape_map = appcfg.cfg_get(appcfg.get_config(), 'orb.shape_map', {})
    assert shape_map.get('llm') == 'octagram' and shape_map.get('gui') == 'circle'
    assert orbstate._SHAPE_CIRCLE_ONLY is True
    orbstate.clear_task()


@pytest.mark.asyncio
async def test_bug_e_no_flicker_speaking_holds_over_listening(fake_ui):
    """Exact renderer sequence from docs/BUGS-WAVE2.md Bug E: the always-listen
    mic opening BETWEEN sentence chunks (audio_start) must never flip her to
    `listening` before speak_end — the frame sequence must go
    idle -> speaking -> (mic opens: STILL speaking) -> listening -> idle."""
    sess, hub, engine = fake_ui
    orbstate.finish_boot()
    orbstate.refresh(hub=hub, engine=engine)              # idle
    orbstate.speak_start()                                # utterance begins
    orbstate.refresh(hub=hub, engine=engine)              # speaking
    # Bug E: mic opens mid-utterance (the live flicker's first half)
    orbstate.listening_on()
    orbstate.emit('listening', hub=hub, engine=engine)    # ws audio_start path
    orbstate.refresh(hub=hub, engine=engine)              # derived again
    # utterance ends (all sentence chunks spoken)
    orbstate.speak_end()
    orbstate.refresh(hub=hub, engine=engine)              # mic still open
    orbstate.listening_off()                              # audio_end
    orbstate.refresh(hub=hub, engine=engine)              # idle
    await drain()
    states = [f['state'] for f in orb_frames(sess)]
    assert states == ['idle', 'speaking', 'speaking', 'speaking',
                      'listening', 'idle'], states


@pytest.mark.asyncio
async def test_bug_e_barge_in_still_reaches_listening(fake_ui):
    """Barge-in semantics preserved: interrupt stops the utterance
    (speak_end) -> listening shows, because the hold is keyed on the speak
    pipeline, not on the mic flag."""
    sess, hub, engine = fake_ui
    orbstate.finish_boot()
    orbstate.build(engine=engine)   # baseline consumed: this test is about
    #                                  speak/listen precedence, not boot
    orbstate.speak_start()
    orbstate.listening_on()
    orbstate.emit('listening', hub=hub, engine=engine)    # held -> speaking
    orbstate.speak_end()                                  # barge-in killed it
    orbstate.refresh(hub=hub, engine=engine)
    await drain()
    states = [f['state'] for f in orb_frames(sess)]
    assert states == ['speaking', 'listening'], states


@pytest.mark.asyncio
async def test_bug_e_confirm_still_beats_speaking(fake_ui):
    """The spoken confirm question keeps showing `confirm` (unchanged §e)."""
    from brain.jobs import store as job_store
    sess, hub, engine = fake_ui
    orbstate.finish_boot()
    snap = job_store.create_job('risk check')
    job_store.transition(snap['id'], 'awaiting_confirm', stage='routing',
                         progress=0.1)
    orbstate.finish_boot()
    orbstate.build(engine=engine)   # baseline consumed: precedence test
    orbstate.speak_start()                                # question is spoken
    orbstate.refresh(hub=hub, engine=engine)
    await drain()
    assert orb_frames(sess)[-1]['state'] == 'confirm'
    job_store.transition(snap['id'], 'cancelled', stage='done', progress=1.0)

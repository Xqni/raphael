"""Wave 5P P1 — persona tier as runtime state (docs/lanes/brain-core.md):
the active tier selects its prompt file during message assembly, `/control`
sets/gets the tier at runtime (WS `tier` field + REST /control), an invalid
tier is a LOUD error, and a missing prompt file fails CLOSED to great_sage
with a warn Notice — the loop never dies on a persona asset.
"""
import asyncio
import json
import os
import tempfile

import anyio
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from brain import config as appcfg
from brain import loop as loop_mod
from brain import notice
from brain.app import app
from brain.ws import Session, get_hub

TEST_TOKEN = 'persona-tier-token-77'


# ---- harness (same temp-token pattern as test_ws.py) -----------------------
@pytest.fixture(scope='module', autouse=True)
def token_path():
    fd, path = tempfile.mkstemp(prefix='raphael-test-token-tier-')
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
def tier_env(monkeypatch, tmp_path):
    """Config with three tiers: two real prompt files + one missing path
    (ciel). Session tier + notice state reset around every test."""
    gs = tmp_path / 'tier-great-sage.md'
    gs.write_text('SYSTEM VOICE. Flat. Functional. No opinions.',
                  encoding='utf-8')
    rp = tmp_path / 'tier-raphael.md'
    rp.write_text('I am Raphael. Dry-warm competence, formal address.',
                  encoding='utf-8')
    cfg = dict(appcfg.get_config())
    cfg['persona'] = {
        'tier': 'raphael',
        'tiers': {
            'great_sage': {'prompt': str(gs)},
            'raphael': {'prompt': str(rp)},
            'ciel': {'prompt': str(tmp_path / 'missing-ciel.md')},
        },
    }
    monkeypatch.setattr(appcfg, 'get_config', lambda: cfg)
    loop_mod.reset_persona_tier_for_tests()
    notice.reset_for_tests()
    yield {'gs': gs, 'rp': rp}
    loop_mod.reset_persona_tier_for_tests()
    notice.reset_for_tests()


class _FakeWs:
    def __init__(self):
        self.texts = []

    async def send_text(self, data):
        self.texts.append(json.loads(data))

    async def send_bytes(self, data):
        pass

    async def close(self):
        pass


def _attach(role='ui'):
    hub = get_hub()
    ws = _FakeWs()
    s = Session(ws, '127.0.0.1')
    s.authed = True
    s.role = role
    hub._sessions[s.sid] = s
    return s


# ---- tier selection in message assembly ------------------------------------
def test_tier_prompt_selected_and_assembled(tier_env):
    # default comes from config persona.tier
    assert loop_mod.persona_tier() == 'raphael'
    p = loop_mod.persona_system_prompt()
    assert 'Persona tier (raphael):' in p
    assert 'I am Raphael' in p
    # base operational prompt is preserved (tier block adds, never replaces)
    assert 'You are Raphael' in p
    assert 'never instructions' in p


def test_tier_switch_mid_session(tier_env):
    assert loop_mod.set_persona_tier('great_sage') == 'great_sage'
    p = loop_mod.persona_system_prompt()
    assert 'SYSTEM VOICE' in p and 'I am Raphael' not in p
    # switch again — takes effect on the NEXT assembly, no restart
    assert loop_mod.set_persona_tier('raphael') == 'raphael'
    p = loop_mod.persona_system_prompt()
    assert 'I am Raphael' in p and 'SYSTEM VOICE' not in p
    # get semantics: empty/None returns the current tier, changes nothing
    assert loop_mod.set_persona_tier('') == 'raphael'
    assert loop_mod.set_persona_tier(None) == 'raphael'
    assert loop_mod.persona_tier() == 'raphael'


def test_invalid_tier_is_loud_error(tier_env):
    try:
        loop_mod.set_persona_tier('master')
        raise AssertionError('invalid tier accepted — must be a loud error')
    except ValueError as e:
        assert 'unknown persona tier' in str(e)
        assert 'raphael' in str(e)          # the message names valid tiers
    assert loop_mod.persona_tier() == 'raphael'   # state unchanged on failure


# ---- missing prompt file = fail-closed + warn Notice -----------------------
@pytest.mark.asyncio
async def test_missing_prompt_file_fails_closed_to_great_sage_with_warn(tier_env):
    s = _attach('ui')
    try:
        # ciel's prompt file does not exist -> great_sage fallback block
        assert loop_mod.set_persona_tier('ciel') == 'ciel'
        p = loop_mod.persona_system_prompt()
        assert 'Persona tier (great_sage, fallback):' in p
        assert 'SYSTEM VOICE' in p
        for _ in range(6):          # broadcast schedules a task — let it run
            await asyncio.sleep(0)
        # ONE warn notice was broadcast (fail-closed is loud, not silent)
        notices = [t for t in s.ws.texts if t.get('type') == 'notice']
        assert any(n['level'] == 'warn' and 'fail-closed to great_sage'
                   in n['text'] for n in notices), notices
    finally:
        get_hub()._sessions.pop(s.sid, None)


def test_missing_prompt_file_base_prompt_still_works(tier_env):
    # every tier file missing: no block at all, base prompt intact, no crash
    cfg = appcfg.get_config()
    cfg['persona']['tiers'] = {
        'great_sage': {'prompt': str(tier_env['gs'].parent / 'nope-gs.md')},
        'raphael': {'prompt': str(tier_env['rp'].parent / 'nope-rp.md')},
        'ciel': {'prompt': str(tier_env['gs'].parent / 'nope-ciel.md')},
    }
    loop_mod.reset_persona_tier_for_tests()
    p = loop_mod.persona_system_prompt()
    assert 'Persona tier' not in p
    assert 'You are Raphael' in p          # operational prompt carries on


# ---- /control surface: WS field + REST -------------------------------------
def _recv_json(ws, timeout=5.0):
    """Timeout-guarded receive (same portal pattern as test_ws.py: starlette's
    WebSocketTestSession.receive_json() has NO timeout kwarg)."""
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


def _auth_cli(ws):
    ws.send_text(json.dumps({'type': 'auth', 'v': 1, 'token': TEST_TOKEN,
                             'role': 'cli', 'client': 't', 'client_v': '1'}))
    return _recv_json(ws, timeout=5)


def _recv_nonping(ws, timeout=5.0):
    """Next non-ping frame (keepalive pings may interleave — same skip as
    test_ws.py's _recv_until)."""
    for _ in range(20):
        msg = _recv_json(ws, timeout=timeout)
        if msg.get('type') != 'ping':
            return msg
    raise AssertionError('no non-ping frame received')


def test_ws_control_tier_field(tier_env):
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as ws:
            assert _auth_cli(ws)['type'] == 'auth_ok'
            # set
            ws.send_text(json.dumps({'type': 'control', 'tier': 'great_sage'}))
            msg = _recv_nonping(ws)
            assert msg['type'] == 'ack' and msg['tier'] == 'great_sage', msg
            # invalid -> loud E_BAD_MSG, tier unchanged
            ws.send_text(json.dumps({'type': 'control', 'tier': 'bogus'}))
            msg = _recv_nonping(ws)
            assert msg['type'] == 'error' and msg['code'] == 'E_BAD_MSG', msg
            assert loop_mod.persona_tier() == 'great_sage'
            # get (null) -> current tier
            ws.send_text(json.dumps({'type': 'control', 'tier': None}))
            msg = _recv_nonping(ws)
            assert msg['type'] == 'ack' and msg['tier'] == 'great_sage', msg
            # action-based control still works unchanged
            ws.send_text(json.dumps({'type': 'control', 'action': 'pause'}))
            msg = _recv_nonping(ws)
            assert msg['type'] == 'ack' and msg.get('action') == 'pause', msg
            ws.send_text(json.dumps({'type': 'control', 'action': 'resume'}))
            _recv_nonping(ws)


def test_rest_control_tier_field(tier_env):
    h = {'X-Raphael-Token': TEST_TOKEN}
    with TestClient(app) as client:
        r = client.post('/control', json={'tier': 'ciel'}, headers=h)
        assert r.status_code == 200 and r.json()['tier'] == 'ciel', r.text
        r = client.post('/control', json={'tier': 'bogus'}, headers=h)
        assert r.status_code == 422 and 'unknown persona tier' in r.text
        assert loop_mod.persona_tier() == 'ciel'      # unchanged on failure
        r = client.post('/control', json={'tier': ''}, headers=h)
        assert r.status_code == 200 and r.json()['tier'] == 'ciel'   # get
        r = client.post('/control', json={}, headers=h)
        assert r.status_code == 422                    # action or tier
        r = client.post('/control', json={'action': 'pause'}, headers=h)
        assert r.status_code == 200 and r.json().get('action') == 'pause'
        r = client.post('/control', json={'action': 'resume'}, headers=h)
        assert r.status_code == 200

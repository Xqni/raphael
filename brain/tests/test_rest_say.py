"""REST endpoints for the CLI (Wave 2 task 5): status/jobs/cancel/control
already existed — this covers the added POST /say (+ auth/validation).
No Fish spawn assertions: TTS falls back (voice tests own the engine)."""
import json
import os
import tempfile

import pytest
from fastapi.testclient import TestClient

from brain.app import app

TEST_TOKEN = 'say-endpoint-token-654'


@pytest.fixture(scope='module')
def token_path():
    fd, path = tempfile.mkstemp(prefix='raphael-test-token-say-')
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


def _recv_json(ws, timeout=8.0):
    import anyio

    async def _inner():
        with anyio.fail_after(timeout):
            return await ws._send_rx.receive()

    message = ws.portal.call(_inner)
    text = message.get('text')
    if text is None:
        text = message.get('bytes', b'').decode()
    return json.loads(text)


def _recv_until(ws, pred, skip=('ping',), limit=60, timeout=8):
    for _ in range(limit):
        msg = _recv_json(ws, timeout=timeout)
        if msg.get('type') in skip:
            continue
        if pred(msg):
            return msg
    raise AssertionError('predicate not met')


def test_say_requires_token(token_path):
    with TestClient(app) as client:
        r = client.post('/say', json={'text': 'hi'})
        assert r.status_code == 401
        r = client.post('/say', json={'text': 'hi'},
                        headers={'X-Raphael-Token': 'wrong'})
        assert r.status_code == 401


def test_say_validates_text(token_path):
    h = {'X-Raphael-Token': TEST_TOKEN}
    with TestClient(app) as client:
        assert client.post('/say', json={'text': '   '}, headers=h).status_code == 422
        assert client.post('/say', json={}, headers=h).status_code == 422
        assert client.post('/say', json={'text': 'x' * 4001}, headers=h).status_code == 422


def test_say_202_and_broadcasts_subtitle_and_speak(token_path):
    h = {'X-Raphael-Token': TEST_TOKEN}
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as ws:
            ws.send_text(json.dumps({'type': 'auth', 'v': 1, 'token': TEST_TOKEN,
                                     'role': 'ui', 'client': 'test',
                                     'client_v': '1.0'}))
            assert _recv_json(ws, timeout=5)['type'] == 'auth_ok'
            r = client.post('/say', json={'text': 'Systems nominal.'}, headers=h)
            assert r.status_code == 202
            body = r.json()
            assert body['ok'] is True and body['job'].startswith('say_')
            assert body['chars'] == len('Systems nominal.')
            # sync subtitle carries the line
            sub = _recv_until(ws, lambda m: m.get('type') == 'subtitle'
                              and 'Systems nominal.' in m.get('text', ''))
            assert sub['job'] == body['job']
            # speech fanout follows (speak JSON reaches role=ui too, §4)
            spk = _recv_until(ws, lambda m: m.get('type') == 'speak'
                              and m.get('event') == 'start')
            assert 'Systems nominal.' in spk['text']


def test_status_jobs_control_still_work(token_path):
    """The other CLI endpoints from the brief (regression guard)."""
    h = {'X-Raphael-Token': TEST_TOKEN}
    with TestClient(app) as client:
        st = client.get('/status', headers=h)
        assert st.status_code == 200
        assert st.json()['ok'] is True and 'mode' in st.json()
        assert client.get('/jobs', headers=h).status_code == 200
        ctl = client.post('/control', json={'action': 'pause'}, headers=h)
        assert ctl.status_code == 200 and ctl.json()['mode'] == 'paused'
        client.post('/control', json={'action': 'resume'}, headers=h)


def test_status_includes_router_usage_block(token_path, monkeypatch):
    """Router request APPROVED 2026-10-07 (surface-usage-in-status): additive
    'router' key on GET /status — empty until the router lane's usage_status
    merges, populated after, {'error': 'unavailable'} if it misbehaves (the
    endpoint itself never goes down)."""
    h = {'X-Raphael-Token': TEST_TOKEN}
    import brain.router as router
    with TestClient(app) as client:
        # facade not merged yet -> key present, empty (or populated on merge)
        r = client.get('/status', headers=h)
        assert r.status_code == 200
        assert 'router' in r.json()
        # populated once usage_status exists
        async def _fake_usage_status():
            return {'window_hours': 24, 'calls': {'total': 3, 'ok': 3,
                                                  'errors': 0}}

        monkeypatch.setattr(router, 'usage_status', _fake_usage_status,
                            raising=False)
        r = client.get('/status', headers=h)
        assert r.json()['router']['calls']['total'] == 3
        assert r.json()['ok'] is True and 'jobs_active' in r.json()
        # a raising facade degrades the block only — /status stays up
        async def _boom():
            raise RuntimeError('log corrupt')

        monkeypatch.setattr(router, 'usage_status', _boom, raising=False)
        r = client.get('/status', headers=h)
        assert r.status_code == 200
        assert r.json()['router'] == {'error': 'unavailable'}
        assert r.json()['ok'] is True

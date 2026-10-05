"""WebSocket protocol tests (PROTOCOL.md §1–§4): auth accept/reject, role
negotiation + capability enforcement, ping/pong keepalive, command → job_event
round trip, speak fanout to role=body, confirm deny/timeout cancellation,
cancel frames, REST /control + /jobs shapes.

SAFETY: RAPHAEL_TOKEN_PATH temp fixture (same pattern as test_health.py) —
the real ~/.raphael/token is never written or deleted.
"""
import json
import os
import tempfile

import anyio
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from brain.app import app

TEST_TOKEN = 'ws-test-token-456'


@pytest.fixture(scope='module')
def token_path():
    # SAFETY: point the app at a TEMP token file — the real ~/.raphael/token
    # must never be written or deleted by tests.
    fd, path = tempfile.mkstemp(prefix='raphael-test-token-ws-')
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
def ping_env():
    old = os.environ.get('RAPHAEL_WS_PING_INTERVAL_S')
    os.environ['RAPHAEL_WS_PING_INTERVAL_S'] = '0.5'
    yield
    if old is None:
        os.environ.pop('RAPHAEL_WS_PING_INTERVAL_S', None)
    else:
        os.environ['RAPHAEL_WS_PING_INTERVAL_S'] = old


def _recv_json(ws, timeout=5.0):
    """starlette 1.7's WebSocketTestSession.receive_json() has NO timeout kwarg;
    wrap the underlying anyio stream receive with fail_after inside the portal
    so a hung server fails the test instead of hanging pytest forever."""
    async def _inner():
        with anyio.fail_after(timeout):
            return await ws._send_rx.receive()

    message = ws.portal.call(_inner)
    if message['type'] == 'websocket.close':
        raise WebSocketDisconnect(code=message.get('code', 1000),
                                  reason=message.get('reason', ''))
    if message['type'] == 'websocket.http.response.start':
        raise AssertionError(f'WS denial response: {message["status"]}')
    text = message.get('text')
    if text is None:
        text = message.get('bytes', b'').decode()
    return json.loads(text)


def _auth(ws, role='cli', token=TEST_TOKEN):
    ws.send_text(json.dumps({'type': 'auth', 'v': 1, 'token': token,
                             'role': role, 'client': 'test-client', 'client_v': '1.0'}))
    return _recv_json(ws, timeout=5)


def _recv_until(ws, pred, skip=('ping',), limit=40, timeout=5):
    frames = []
    for _ in range(limit):
        msg = _recv_json(ws, timeout=timeout)
        frames.append(msg)
        if msg.get('type') in skip:
            continue
        if pred(msg):
            return msg, frames
    raise AssertionError(
        f'predicate not met; types={[f.get("type") for f in frames]}')


def test_ws_auth_accept(token_path):
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as ws:
            msg = _auth(ws, 'cli')
            assert msg['type'] == 'auth_ok', msg
            assert msg['v'] == 1
            assert msg['session']
            assert msg['server_v'].startswith('brain-')


def test_ws_auth_reject_bad_token(token_path):
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as ws:
            msg = _auth(ws, 'cli', token='wrong-token')
            assert msg['type'] == 'auth_fail', msg
            assert msg['code'] == 'E_AUTH'


def test_ws_auth_reject_bad_role(token_path):
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as ws:
            msg = _auth(ws, 'hacker')
            assert msg['type'] == 'auth_fail', msg
            assert msg['code'] == 'E_PROTO'


def test_ws_auth_reject_proto_version(token_path):
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as ws:
            ws.send_text(json.dumps({'type': 'auth', 'v': 2, 'token': TEST_TOKEN,
                                     'role': 'cli', 'client': 't', 'client_v': '1'}))
            msg = _recv_json(ws, timeout=5)
            assert msg['type'] == 'auth_fail', msg
            assert msg['code'] == 'E_PROTO'


def test_ws_upgrade_wrong_token_refused(token_path):
    with TestClient(app) as client:
        with client.websocket_connect('/ws',
                                      headers={'X-Raphael-Token': 'wrong'}) as ws:
            msg = _recv_json(ws, timeout=5)
            assert msg['type'] == 'auth_fail', msg
            assert msg['code'] == 'E_AUTH'


def test_ws_frame_before_auth_refused(token_path):
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as ws:
            ws.send_text(json.dumps({'type': 'command', 'v': 1, 'text': 'sneak'}))
            msg = _recv_json(ws, timeout=5)
            assert msg['type'] == 'error', msg
            assert msg['code'] == 'E_PROTO'


def test_ws_role_capability_enforced(token_path):
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as ws:
            msg = _auth(ws, 'ui')
            assert msg['type'] == 'auth_ok'
            # role=ui must not send act_res / audio (PROTOCOL §4)
            ws.send_text(json.dumps({'type': 'act_res', 'v': 1, 'job': 'j_x',
                                     'ok': True}))
            msg = _recv_until(ws, lambda m: m.get('type') == 'error')
            assert msg['code'] == 'E_UNSUPPORTED'
            ws.send_text(json.dumps({'type': 'audio_start', 'v': 1,
                                     'sample_rate': 16000}))
            msg = _recv_until(ws, lambda m: m.get('type') == 'error')
            assert msg['code'] == 'E_UNSUPPORTED'
            # unknown type → non-fatal E_UNSUPPORTED warning
            ws.send_text(json.dumps({'type': 'warp_drive', 'v': 1}))
            msg = _recv_until(ws, lambda m: m.get('type') == 'error')
            assert msg['code'] == 'E_UNSUPPORTED'


def test_ws_ping_pong_keepalive(token_path, ping_env):
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as ws:
            msg = _auth(ws, 'cli')
            assert msg['type'] == 'auth_ok'
            # server sends an immediate ping after auth_ok (keepalive kick-off)
            msg, _ = _recv_until(ws, lambda m: m.get('type') == 'ping', skip=())
            ws.send_text(json.dumps({'type': 'pong', 'v': 1}))
            # periodic ping also arrives (0.5s interval in this test)
            msg, _ = _recv_until(ws, lambda m: m.get('type') == 'ping', skip=())
            ws.send_text(json.dumps({'type': 'pong', 'v': 1}))
            # session still alive after answering pings → state_req round trip
            ws.send_text(json.dumps({'type': 'state_req', 'v': 1}))
            msg, _ = _recv_until(ws, lambda m: m.get('type') == 'orb_state')
            assert msg['state'] in ('idle', 'thinking', 'confirm',
                                    'private_overlay'), msg
            assert 'mode' in msg and 'jobs_active' in msg


def test_ws_command_roundtrip_speak_and_subtitle(token_path):
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as ws_cli:
            msg = _auth(ws_cli, 'cli')
            assert msg['type'] == 'auth_ok'
            with client.websocket_connect('/ws') as ws_body:
                msg = _auth(ws_body, 'body')
                assert msg['type'] == 'auth_ok'
                ws_cli.send_text(json.dumps({'type': 'command', 'v': 1,
                                             'text': 'echo hello world',
                                             'source': 'text'}))
                ack, _ = _recv_until(ws_cli, lambda m: m.get('type') == 'ack')
                job = ack['job']
                assert job.startswith('j_')
                # job lifecycle: running → done, canonical §5 shape
                done, frames = _recv_until(
                    ws_cli,
                    lambda m: m.get('type') == 'job_event'
                    and m.get('status') == 'done' and m.get('job') == job,
                    timeout=8)
                assert done['text'] == 'Echo: hello world'
                assert done['v'] == 1 and isinstance(done['seq'], int)
                assert done['progress'] == 1.0
                events = [f for f in frames if f.get('type') == 'job_event'
                          and f.get('job') == job]
                statuses = [e['status'] for e in events]
                assert 'queued' in statuses and 'done' in statuses, statuses
                assert any(f.get('type') == 'subtitle' and f.get('job') == job
                           for f in frames), [f.get('type') for f in frames]
                # role=body receives speak frames (PROTOCOL §4: body only)
                speak, _ = _recv_until(
                    ws_body,
                    lambda m: m.get('type') == 'speak'
                    and m.get('event') == 'start' and m.get('job') == job,
                    timeout=8)
                assert speak['text'] == 'Echo: hello world'
                assert speak['sample_rate'] == 24000
                _recv_until(ws_body,
                            lambda m: m.get('type') == 'speak'
                            and m.get('event') == 'end' and m.get('job') == job,
                            timeout=8)


def test_ws_confirm_deny_cancels_job(token_path):
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as ws:
            _auth(ws, 'cli')
            ws.send_text(json.dumps({'type': 'command', 'v': 1,
                                     'text': 'delete all my files in downloads'}))
            ack, _ = _recv_until(ws, lambda m: m.get('type') == 'ack')
            job = ack['job']
            conf, _ = _recv_until(ws, lambda m: m.get('type') == 'needs_confirm'
                                  and m.get('job') == job)
            assert conf['question'] and conf['actions'] == ['yes', 'no']
            assert conf['expires_at'] > 0
            ws.send_text(json.dumps({'type': 'confirm_resp', 'v': 1,
                                     'job': job, 'answer': 'no'}))
            ack2, _ = _recv_until(ws, lambda m: m.get('type') == 'ack'
                                  and m.get('cancelled') is not True)
            assert ack2['answer'] == 'no'
            msg, _ = _recv_until(ws, lambda m: m.get('type') == 'job_event'
                                 and m.get('status') == 'cancelled'
                                 and m.get('job') == job, timeout=8)
            assert msg['text'] == 'Aborted.'
            assert msg['error_code'] == 'E_CANCELLED'


def test_ws_confirm_timeout_aborts_never_auto_approves(token_path):
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as ws:
            _auth(ws, 'cli')
            ws.send_text(json.dumps({'type': 'command', 'v': 1,
                                     'text': 'purchase a new laptop on amazon'}))
            ack, _ = _recv_until(ws, lambda m: m.get('type') == 'ack')
            job = ack['job']
            _recv_until(ws, lambda m: m.get('type') == 'needs_confirm'
                        and m.get('job') == job)
            # no reply → timeout (RAPHAEL_CONFIRM_TIMEOUT_S=2 in conftest)
            msg, _ = _recv_until(ws, lambda m: m.get('type') == 'job_event'
                                 and m.get('status') == 'cancelled'
                                 and m.get('job') == job,
                                 skip=(), timeout=10, limit=60)
            assert msg['error_code'] == 'E_CONFIRM_TIMEOUT'


def test_ws_confirm_yes_grants_scoped_job(token_path):
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as ws:
            _auth(ws, 'cli')
            ws.send_text(json.dumps({'type': 'command', 'v': 1,
                                     'text': 'echo run rm test after yes'}))
            ack, _ = _recv_until(ws, lambda m: m.get('type') == 'ack')
            job = ack['job']
            _recv_until(ws, lambda m: m.get('type') == 'needs_confirm'
                        and m.get('job') == job)
            ws.send_text(json.dumps({'type': 'confirm_resp', 'v': 1,
                                     'job': job, 'answer': 'yes'}))
            done, _ = _recv_until(ws, lambda m: m.get('type') == 'job_event'
                                  and m.get('status') == 'done'
                                  and m.get('job') == job, timeout=8)
            assert done['text'] == 'Echo: run rm test after yes'


def test_ws_cancel_frame_on_awaiting_confirm(token_path):
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as ws:
            _auth(ws, 'cli')
            ws.send_text(json.dumps({'type': 'command', 'v': 1,
                                     'text': 'delete the project folder'}))
            ack, _ = _recv_until(ws, lambda m: m.get('type') == 'ack')
            job = ack['job']
            _recv_until(ws, lambda m: m.get('type') == 'needs_confirm'
                        and m.get('job') == job)
            ws.send_text(json.dumps({'type': 'cancel', 'v': 1,
                                     'job': job, 'scope': 'full'}))
            ack2, _ = _recv_until(ws, lambda m: m.get('type') == 'ack'
                                  and m.get('cancelled') is True)
            assert ack2['job'] == job
            msg, _ = _recv_until(ws, lambda m: m.get('type') == 'job_event'
                                 and m.get('status') == 'cancelled'
                                 and m.get('job') == job, timeout=8)
            assert msg['error_code'] == 'E_CANCELLED'


def test_ws_disconnect_cancels_session_jobs(token_path):
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as ws:
            _auth(ws, 'cli')
            ws.send_text(json.dumps({'type': 'command', 'v': 1,
                                     'text': 'delete stuff now'}))
            ack, _ = _recv_until(ws, lambda m: m.get('type') == 'ack')
            job = ack['job']
            _recv_until(ws, lambda m: m.get('type') == 'needs_confirm'
                        and m.get('job') == job)
            # drop the connection mid-confirm → server cancels session tasks
        from brain.jobs import store
        for _ in range(100):
            j = store.get_job(job)
            if j and j['status'] in ('cancelled', 'interrupted', 'done', 'failed'):
                break
            import time as _t
            _t.sleep(0.02)
        assert j['status'] == 'cancelled', j


def test_rest_control_and_status(token_path):
    with TestClient(app) as client:
        h = {'X-Raphael-Token': TEST_TOKEN}
        r = client.post('/control', json={'action': 'private_on'}, headers=h)
        assert r.status_code == 200 and r.json()['ok'] is True
        assert r.json()['mode'] == 'private'
        r = client.get('/status', headers=h)
        assert r.status_code == 200
        assert r.json()['mode'] == 'private'
        assert 'jobs_active' in r.json() and 'input_lock' in r.json()
        r = client.post('/control', json={'action': 'private_off'}, headers=h)
        assert r.json()['mode'] == 'normal'
        r = client.post('/control', json={'action': 'bogus_action'}, headers=h)
        assert r.status_code == 422
        r = client.post('/control', json={'action': 'pause'}, headers=h)
        assert r.json()['mode'] == 'paused'
        r = client.post('/control', json={'action': 'resume'}, headers=h)
        assert r.json()['mode'] == 'normal'


def test_rest_jobs_shapes_and_cancel(token_path):
    with TestClient(app) as client:
        h = {'X-Raphael-Token': TEST_TOKEN}
        # pause so the queued job stays queued deterministically
        assert client.post('/control', json={'action': 'pause'}, headers=h
                           ).json()['mode'] == 'paused'
        try:
            r = client.post('/jobs', json={'text': 'queued job', 'source': 'text',
                                           'priority': 'normal'}, headers=h)
            assert r.status_code == 200
            body = r.json()
            jid = body['job_id']
            assert jid.startswith('j_')
            assert body['job']['status'] == 'queued'
            r = client.get(f'/jobs/{jid}', headers=h)
            assert r.json()['status'] == 'queued'
            assert r.json()['text'] == 'queued job'
            r = client.get('/jobs', headers=h)
            assert any(j['job'] == jid for j in r.json())
            r = client.post(f'/jobs/{jid}/cancel', json={'scope': 'full'}, headers=h)
            assert r.status_code == 200 and r.json()['cancelled'] is True
            assert client.get(f'/jobs/{jid}', headers=h).json()['status'] == 'cancelled'
            # terminal → 400 (immutable)
            r = client.post(f'/jobs/{jid}/cancel', headers=h)
            assert r.status_code == 400
        finally:
            client.post('/control', json={'action': 'resume'}, headers=h)


def test_rest_jobs_missing_text_422(token_path):
    with TestClient(app) as client:
        h = {'X-Raphael-Token': TEST_TOKEN}
        r = client.post('/jobs', json={'task': ''}, headers=h)
        assert r.status_code == 422
        r = client.post('/jobs', json={}, headers=h)
        assert r.status_code == 422

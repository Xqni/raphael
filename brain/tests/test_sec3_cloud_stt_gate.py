"""SEC-3 tripwire (Wave-5H audit, P0 co-owner): NO cloud STT without a local
wake/PTT decision. The local decision = body's audio_start; the gate is asked
BEFORE upload (fail-closed); every actual cloud upload surfaces a visible
notice frame (ui+cli). Evidence quotes live in docs/status/brain-core.md."""
import json
import os
import struct
import tempfile

import pytest
from fastapi.testclient import TestClient

from brain.app import app

TEST_TOKEN = 'sec3-gate-token-117'


@pytest.fixture(scope='module')
def token_path():
    fd, path = tempfile.mkstemp(prefix='raphael-tok-sec3-')
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

    m = ws.portal.call(_inner)
    t = m.get('text')
    if t is None:
        t = m.get('bytes', b'').decode()
    return json.loads(t)


def _recv_until(ws, pred, skip=('ping',), limit=80, timeout=8):
    for _ in range(limit):
        msg = _recv_json(ws, timeout=timeout)
        if msg.get('type') in skip:
            continue
        if pred(msg):
            return msg
    raise AssertionError('predicate not met')


def _auth(ws, role):
    ws.send_text(json.dumps({'type': 'auth', 'v': 1, 'token': TEST_TOKEN,
                             'role': role, 'client': 't', 'client_v': '1'}))
    return _recv_json(ws, timeout=5)


def _send_audio(ws, *, with_start=True, reason='wake', silent=False):
    if with_start:
        ws.send_text(json.dumps({'type': 'audio_start', 'v': 1,
                                 'reason': reason}))
        _recv_json(ws, timeout=5)                       # ack
    payload = (b'\x00\x00' * 8000 if silent
               else struct.pack('<h', 2500) * 8000)      # 0.5 s non-silent
    ws.send_bytes(b'RAPH' + struct.pack('>BI', 1, 1) + payload)
    ws.send_text(json.dumps({'type': 'audio_end', 'v': 1}))


@pytest.fixture
def cloud_counter(monkeypatch):
    """Count calls that would reach the CLOUD STT (router.transcribe)."""
    import brain.router as router
    calls = []

    def fake_transcribe(audio, language=None, **kw):
        calls.append(len(audio))
        return {'text': 'Raphael, hello there', 'rtf': 0.1,
                'provider': 'groq'}

    monkeypatch.setattr(router, 'transcribe', fake_transcribe, raising=False)
    return calls


def test_audio_end_without_local_decision_zero_cloud_calls(token_path,
                                                           cloud_counter):
    """Tripwire (SEC-3 exit criterion): a segment with NO audio_start — no
    local wake/PTT decision — produces ZERO router.transcribe calls."""
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as ws_body:
            assert _auth(ws_body, 'body')['type'] == 'auth_ok'
            # binary frames fill the buffer, but audio_start never fired
            payload = struct.pack('<h', 2500) * 8000
            ws_body.send_bytes(b'RAPH' + struct.pack('>BI', 1, 1) + payload)
            ws_body.send_text(json.dumps({'type': 'audio_end', 'v': 1}))
            ack = _recv_until(ws_body, lambda m: m.get('type') == 'ack'
                              and m.get('audio') == 'end')
            assert ack['audio'] == 'end'      # graceful, not an error
    assert cloud_counter == [], 'cloud STT reached without a local decision'


def test_silent_segment_never_uploads(token_path, cloud_counter):
    """Local gate first: silence (and ptt-only suppression) never upload."""
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as ws_body:
            assert _auth(ws_body, 'body')['type'] == 'auth_ok'
            _send_audio(ws_body, silent=True)
            _recv_until(ws_body, lambda m: m.get('type') == 'ack'
                        and m.get('audio') == 'end')
    assert cloud_counter == [], 'silent segment reached the cloud'


def test_decision_present_uploads_and_surfaces_visible_notice(token_path,
                                                              cloud_counter):
    """The other half of SEC-3: when audio IS sent to the cloud, ui+cli see
    the indicator notice (presence-only text)."""
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as ws_ui:
            assert _auth(ws_ui, 'ui')['type'] == 'auth_ok'
            with client.websocket_connect('/ws') as ws_body:
                assert _auth(ws_body, 'body')['type'] == 'auth_ok'
                _send_audio(ws_body, silent=False)
                _recv_until(ws_body, lambda m: m.get('type') == 'ack'
                            and m.get('audio') == 'end')
                notice = _recv_until(
                    ws_ui, lambda m: m.get('type') == 'notice'
                    and 'cloud STT' in m.get('text', ''))
                assert notice['level'] == 'info'
                assert set(notice.keys()) >= {'type', 'v', 'text', 'level', 'ts'}
    assert len(cloud_counter) == 1, cloud_counter


def test_unknown_reason_with_local_decision_is_wake_semantics(token_path,
                                                              cloud_counter):
    """Determination (SEC-3 audit question): an audio_start with an unknown
    reason label still counts as a LOCAL decision (the body opened the
    segment); the label falls back to wake, whose post-STT gate governs —
    and in this always_listen profile the upload is allowed exactly like
    reason=wake."""
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as ws_body:
            assert _auth(ws_body, 'body')['type'] == 'auth_ok'
            _send_audio(ws_body, reason='banana', silent=False)
            _recv_until(ws_body, lambda m: m.get('type') == 'ack'
                        and m.get('audio') == 'end')
    assert len(cloud_counter) == 1, 'audio_start present = local decision'

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


# ---- AUD-17: slow STT must not block the receive loop -----------------------
def test_slow_stt_heartbeat_and_cancellation(token_path, monkeypatch):
    """>30s mocked STT: pings keep arriving while the segment is in flight
    (receive loop free), and disconnecting cancels the in-flight work without
    hanging the session teardown."""
    import threading
    import time as _time
    from brain.voice import get_voice

    gate = threading.Event()

    def slow_transcribe(buf, sample_rate=None, reason=None):
        gate.wait(35)               # >30s mocked STT (released at test end)
        from types import SimpleNamespace
        return SimpleNamespace(text='Raphael, hello', lang='en', rtf=0.1)

    monkeypatch.setattr(get_voice(), 'transcribe_result', slow_transcribe)
    old_ping = os.environ.get('RAPHAEL_WS_PING_INTERVAL_S')
    os.environ['RAPHAEL_WS_PING_INTERVAL_S'] = '0.3'
    try:
        with TestClient(app) as client:
            with client.websocket_connect('/ws') as ws_body:
                assert _auth(ws_body, 'body')['type'] == 'auth_ok'
                kick = _recv_json(ws, timeout=5) if False else _recv_json(ws_body, timeout=5)
                assert kick['type'] == 'ping'      # post-auth kickoff ping
                _send_audio(ws_body, silent=False) # audio_end -> queued work
                # heartbeat continues WHILE STT is pending: next frame is a
                # server ping (not blocked behind a 35s transcribe)
                t0 = _time.monotonic()
                nxt = _recv_json(ws_body, timeout=2.5)
                elapsed = _time.monotonic() - t0
                assert nxt['type'] == 'ping', nxt
                assert elapsed < 2.5, 'receive loop was blocked by STT'
                # no audio ack yet — the worker is still in flight
                # (disconnect now: cancellation must not hang teardown)
            # leaving the context disconnects mid-STT -> worker cancelled
    finally:
        gate.set()                    # release the blocked thread promptly
        if old_ping is None:
            os.environ.pop('RAPHAEL_WS_PING_INTERVAL_S', None)
        else:
            os.environ['RAPHAEL_WS_PING_INTERVAL_S'] = old_ping


# ---- AUD-24: exact audio byte cap + global session bound --------------------
def test_audio_buffer_never_exceeds_exact_cap(token_path, monkeypatch):
    import struct
    import brain.ws as ws_mod
    from brain.ws import get_hub
    monkeypatch.setattr(ws_mod, 'AUDIO_MAX_BYTES', 1000)   # small cap
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as ws_body:
            assert _auth(ws_body, 'body')['type'] == 'auth_ok'
            _send_audio(ws_body, silent=False)             # 8000 B tone
            _recv_until(ws_body, lambda m: m.get('type') == 'ack'
                        and m.get('audio') == 'end')
            body = next(s for s in get_hub()._sessions.values()
                        if s.role == 'body')
            assert len(body.audio_buf) <= 1000, len(body.audio_buf)


def test_max_sessions_refused_loudly(token_path, monkeypatch):
    import brain.ws as ws_mod
    monkeypatch.setattr(ws_mod, 'MAX_SESSIONS', 1)
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as ws1:
            assert _auth(ws1, 'ui')['type'] == 'auth_ok'
            with client.websocket_connect('/ws') as ws2:
                ws2.send_text(json.dumps({'type': 'auth', 'v': 1,
                                          'token': TEST_TOKEN, 'role': 'ui',
                                          'client': 't', 'client_v': '1'}))
                first = _recv_json(ws2, timeout=5)
                assert first['type'] == 'auth_fail'
                assert first['code'] == 'E_RATE_LIMIT'

"""AUD-05 data source (dispatch 2026-10-08): pc-control push -> brain cache ->
router hook. Cache-first (<5s), vision ring second, else UNKNOWN."""
import json
import os
import tempfile
import time

import pytest
from fastapi.testclient import TestClient

from brain import foreground
from brain.app import app

TEST_TOKEN = 'fg-cache-token-246'


@pytest.fixture(autouse=True)
def _clean():
    foreground.reset_for_tests()
    yield
    foreground.reset_for_tests()


@pytest.fixture(scope='module')
def token_path():
    fd, path = tempfile.mkstemp(prefix='raphael-tok-fg-')
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


def _recv_until(ws, pred, skip=('ping',), limit=40, timeout=5):
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


# ---- unit: cache-first, ring second, unknown last ---------------------------
def test_cache_fresh_wins_then_ring_then_unknown():
    from brain.vision import context as ring
    # 1) push-cache fresh (<5s) wins over everything
    foreground.set_foreground('KeePass - Password Safe')
    assert foreground.cached() == 'KeePass - Password Safe'
    assert foreground.provider() == 'KeePass - Password Safe'
    # 2) stale push falls back to the vision ring (fresh <60s)
    foreground._ts = time.monotonic() - 10.0     # > FRESH_S
    ring.reset_history()
    ring.record_foreground('Obsidian - vault')
    assert foreground.cached() is None
    assert foreground.provider() == 'Obsidian - vault'
    # 3) both stale -> UNKNOWN (None) = router fails closed; never raises
    foreground._ts = time.monotonic() - 30.0
    hist = ring.recent_history(1)
    if hist:
        ring._history[-1] = (hist[-1][0] - 120.0, hist[-1][1])
    assert foreground.provider() is None
    # blank/garbage pushes never poison the cache
    assert foreground.set_foreground('   ') is False
    assert foreground.set_foreground(None) is False
    ring.reset_history()


def test_set_foreground_normalizes_whitespace_and_caps():
    assert foreground.set_foreground('  My   Window  Title  ') is True
    assert foreground.cached() == 'My Window Title'
    assert foreground.set_foreground('x' * 500) is True
    assert len(foreground.cached()) <= 160


# ---- ws push consumption ----------------------------------------------------
def test_body_pushes_foreground_and_it_feeds_the_router(token_path):
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as ws_body:
            assert _auth(ws_body, 'body')['type'] == 'auth_ok'
            ws_body.send_text(json.dumps({'type': 'foreground', 'v': 1,
                                          'value': 'Windows Terminal'}))
            ack, _ = None, None
            ack = _recv_until(ws_body, lambda m: m.get('type') == 'ack'
                              and m.get('kind') == 'foreground')
            assert ack['cached'] is True
            # cache-first provider now answers (fresh <5s)
            assert foreground.provider() == 'Windows Terminal'
            from brain.router import privacy as rpriv
            assert rpriv.foreground_window() == 'Windows Terminal'
            # shape tolerance: window dict form
            ws_body.send_text(json.dumps({'type': 'foreground', 'v': 1,
                                          'window': {'title': 'Banking App',
                                                     'process': 'bank.exe'}}))
            ack2 = _recv_until(ws_body, lambda m: m.get('type') == 'ack'
                               and m.get('cached') is True)
            # exact gateway.py:134 identity shape: "title | process"
            assert foreground.provider() == 'Banking App | bank.exe'
            # ...and it warmed the vision ring too (probe shape)
            from brain.vision import context as ring
            assert ring.recent_history(1)[0][1] == 'Banking App | bank.exe'
        # after disconnect the value ages out of the 5s window eventually
        foreground._ts = time.monotonic() - 99.0
        assert foreground.cached() is None


def test_null_window_records_nothing(token_path):
    """window:null = unverifiable → nothing recorded (ring stays clean)."""
    from brain.vision import context as ring
    ring.reset_history()
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as ws_body:
            assert _auth(ws_body, 'body')['type'] == 'auth_ok'
            ws_body.send_text(json.dumps({'type': 'foreground', 'v': 1,
                                          'window': None}))
            ack = _recv_until(ws_body, lambda m: m.get('type') == 'ack'
                              and m.get('kind') == 'foreground')
            assert ack['cached'] is False
    assert foreground.cached() is None
    assert ring.recent_history(1) == []
    ring.reset_history()


def test_private_mode_does_not_record(token_path):
    """Private Mode: pushes are not recorded (mirrors probes, which stop)."""
    from brain.mode import get_mode
    from brain.vision import context as ring
    ring.reset_history()
    get_mode().set('private_on', persist=False)
    try:
        with TestClient(app) as client:
            with client.websocket_connect('/ws') as ws_body:
                assert _auth(ws_body, 'body')['type'] == 'auth_ok'
                ws_body.send_text(json.dumps({'type': 'foreground', 'v': 1,
                                              'window': {'title': 'Secret',
                                                         'process': 's.exe'}}))
                ack = _recv_until(ws_body, lambda m: m.get('type') == 'ack'
                                  and m.get('kind') == 'foreground')
                assert ack['cached'] is False
    finally:
        get_mode().set('private_off', persist=False)
    assert foreground.cached() is None
    assert ring.recent_history(1) == []
    ring.reset_history()


def test_foreground_push_restricted_to_body(token_path):
    """Only the body may push foreground (capability table)."""
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as ws_ui:
            assert _auth(ws_ui, 'ui')['type'] == 'auth_ok'
            ws_ui.send_text(json.dumps({'type': 'foreground', 'v': 1,
                                        'value': 'sneaky'}))
            err = _recv_until(ws_ui, lambda m: m.get('type') == 'error')
            assert err['code'] == 'E_UNSUPPORTED'
            assert foreground.cached() is None      # nothing cached

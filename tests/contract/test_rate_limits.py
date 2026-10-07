"""PROTOCOL §1 message limits: 8 MiB max, 40 text msgs/s per connection,
125 binary audio frames/s, malformed-frame strikes (3 → close),
server closes on violation with E_RATE_LIMIT / E_BAD_MSG.
"""
import pytest
from starlette.websockets import WebSocketDisconnect

from harness.wssession import (WSSession, recv_frame, wait_frame, ws_auth,
                               ws_send)


def test_text_rate_limit_40_per_s(client, qa_token):
    with WSSession(client, qa_token, role='cli') as s:
        # `pong` frames have no side effects — pure rate-limiter fodder
        for i in range(60):
            try:
                s.send({'type': 'pong', 'v': 1, 'seq': i})
            except Exception:  # noqa: BLE001 — server may close mid-burst
                break
        reply = s.wait(lambda m: m.get('type') == 'error', timeout=5)
        assert reply['code'] == 'E_RATE_LIMIT'
        with pytest.raises(WebSocketDisconnect):
            recv_frame(s._ws, timeout=5)


def test_rate_limit_resets_after_window(client, qa_token):
    """The limiter is a 1 s sliding window, not a lifetime budget."""
    import time
    with WSSession(client, qa_token, role='cli') as s:
        for _ in range(35):
            s.send({'type': 'pong', 'v': 1})
        s.drain(quiet=0.2, cap=1.0)          # consume nothing but pings/quiet
        time.sleep(1.2)                       # window rolls over
        for _ in range(35):
            s.send({'type': 'pong', 'v': 1})
        # if a second full burst triggered the limiter, an error frame would
        # arrive; drain waits past any straggler window
        frames = s.drain(quiet=0.3, cap=1.6)
        assert not [f for f in frames if f.get('type') == 'error'], frames
        # connection still usable
        s.send({'type': 'state_req', 'v': 1})
        s.wait(lambda m: m.get('type') == 'orb_state', timeout=5)


def test_max_message_8mib(client, qa_token):
    with WSSession(client, qa_token, role='cli') as s:
        try:
            s.send_raw_text('x' * (8 * 1024 * 1024 + 1))
        except Exception:  # noqa: BLE001 — close may race the send
            pass
        reply = s.wait(lambda m: m.get('type') == 'error', timeout=5)
        assert reply['code'] == 'E_BAD_MSG'
        with pytest.raises(WebSocketDisconnect):
            recv_frame(s._ws, timeout=5)


def test_malformed_json_two_strikes_then_close(client, qa_token):
    with WSSession(client, qa_token, role='cli') as s:
        s.send_raw_text('[1, 2, 3]')          # non-object frame = strike 1
        reply = s.wait(lambda m: m.get('type') == 'error', timeout=5)
        assert reply['code'] == 'E_BAD_MSG'
        # still alive after one strike: a valid frame still works
        s.send({'type': 'state_req', 'v': 1})
        s.wait(lambda m: m.get('type') == 'orb_state', timeout=5)

        s.send_raw_text('not json at all')     # strike 2
        reply = s.wait(lambda m: m.get('type') == 'error', timeout=5)
        assert reply['code'] == 'E_BAD_MSG'

        s.send_raw_text('{broken')              # strike 3 → close
        reply = s.wait(lambda m: m.get('type') == 'error', timeout=5)
        assert reply['code'] == 'E_BAD_MSG'
        with pytest.raises(WebSocketDisconnect):
            recv_frame(s._ws, timeout=5)


def test_unknown_type_is_nonfatal_warning(client, qa_token):
    """§3: unknown `type` → E_UNSUPPORTED (warning), NOT a close."""
    with WSSession(client, qa_token, role='cli') as s:
        s.send({'type': 'warp_drive', 'v': 1})
        reply = s.wait(lambda m: m.get('type') == 'error', timeout=5)
        assert reply['code'] == 'E_UNSUPPORTED'
        s.send({'type': 'state_req', 'v': 1})
        s.wait(lambda m: m.get('type') == 'orb_state', timeout=5)

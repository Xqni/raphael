"""PROTOCOL §6 binary frames: [4-byte magic "RAPH"][u8 kind][u32 seq][payload].

Covers: encoder layout (big-endian seq), kind=1 mic PCM accumulation into the
audio buffer + audio_end → STT (mocked) → stt_final broadcast, bad magic →
E_BAD_MSG + close, wrong-role kind → E_UNSUPPORTED, pre-auth binary → close,
125 frames/s binary rate limit.
"""
import struct

import pytest
from starlette.websockets import WebSocketDisconnect

from harness import voicespy
from harness.wssession import (SessionTimeout, WSSession, recv_frame,
                               wait_frame)


def _pcm_frame(kind: int, seq: int, payload: bytes) -> bytes:
    return b'RAPH' + struct.pack('>BI', kind, seq) + payload


def test_encoder_layout_matches_protocol_s6():
    from brain.voice import encode_binary_frame
    frame = encode_binary_frame(2, 0x01020304, b'abc')
    assert frame[:4] == b'RAPH'
    assert frame[4] == 2
    assert frame[5:9] == struct.pack('>I', 0x01020304)   # documented BE u32
    assert frame[9:] == b'abc'
    assert len(frame) == 9 + 3


def test_kind1_mic_pcm_accumulates_and_transcribes(client, qa_token):
    """body sends audio_start + N kind=1 chunks + audio_end → the exact PCM
    bytes reach STT (mocked recorder) and stt_final is broadcast to body+ui."""
    payload_a = bytes(range(256)) * 8
    payload_b = b'\x01\x02' * 100
    with WSSession(client, qa_token, role='body') as body:
        body.send({'type': 'audio_start', 'v': 1, 'sample_rate': 16000,
                   'channels': 1, 'encoding': 'pcm_s16le', 'reason': 'wake'})
        body.wait(lambda m: m.get('type') == 'ack'
                  and m.get('audio') == 'start', timeout=5)
        body.send_bytes(_pcm_frame(1, 0, payload_a))
        body.send_bytes(_pcm_frame(1, 1, payload_b))
        body.send({'type': 'audio_end', 'v': 1})
        # both the ack and the broadcast stt_final must arrive (order is not
        # contract-guaranteed: broadcast is scheduled, ack is awaited)
        seen = []
        for _ in range(12):
            frame = recv_frame(body._ws, timeout=5)
            if isinstance(frame, bytes) or frame.get('type') == 'ping':
                continue
            seen.append(frame)
            has_ack = any(f.get('type') == 'ack' and f.get('audio') == 'end'
                          for f in seen)
            has_stt = any(f.get('type') == 'stt_final' for f in seen)
            if has_ack and has_stt:
                break
        stt = [f for f in seen if f['type'] == 'stt_final']
        acks = [f for f in seen if f['type'] == 'ack']
        assert stt, seen
        assert stt[0]['text'] == voicespy.CANNED_TRANSCRIPT
        assert any(a.get('audio') == 'end' for a in acks), seen
        assert voicespy.STT_CALLS, 'STT was never invoked'
        assert voicespy.STT_CALLS[-1] == payload_a + payload_b


def test_bad_binary_magic_error_and_close(client, qa_token):
    with WSSession(client, qa_token, role='body') as s:
        try:
            s.send_bytes(b'NOPE\x01' + b'\x00' * 8)
        except Exception:  # noqa: BLE001 — close may race the send
            pass
        reply = s.wait(lambda m: m.get('type') == 'error', timeout=5)
        assert reply['code'] == 'E_BAD_MSG'
        with pytest.raises(WebSocketDisconnect):
            recv_frame(s._ws, timeout=5)


def test_short_binary_frame_rejected(client, qa_token):
    with WSSession(client, qa_token, role='body') as s:
        try:
            s.send_bytes(b'RAPH')               # < 9 bytes
        except Exception:  # noqa: BLE001
            pass
        reply = s.wait(lambda m: m.get('type') == 'error', timeout=5)
        assert reply['code'] == 'E_BAD_MSG'


def test_binary_kind_wrong_role_unsupported(client, qa_token):
    """§6: kind=1 is body→brain; ui sending it gets E_UNSUPPORTED (and the
    frame must NOT be accepted into any audio buffer)."""
    with WSSession(client, qa_token, role='ui') as s:
        s.send_bytes(_pcm_frame(1, 0, b'\x00' * 16))
        reply = s.wait(lambda m: m.get('type') == 'error', timeout=5)
        assert reply['code'] == 'E_UNSUPPORTED'
        # still alive (warning, not a close)
        s.send({'type': 'state_req', 'v': 1})
        s.wait(lambda m: m.get('type') == 'orb_state', timeout=5)


def test_binary_before_auth_closes(client, qa_token):
    with client.websocket_connect('/ws') as ws:
        try:
            ws.send_bytes(_pcm_frame(1, 0, b'\x00' * 4))
        except Exception:  # noqa: BLE001
            pass
        with pytest.raises((WebSocketDisconnect, SessionTimeout)):
            frame = recv_frame(ws, timeout=5)
            if isinstance(frame, dict):
                # any response frame must be a refusal, never acceptance
                assert frame.get('type') in ('error', 'auth_fail')
                recv_frame(ws, timeout=5)


def test_binary_rate_limit_125_per_s(client, qa_token):
    with WSSession(client, qa_token, role='body') as s:
        for i in range(140):
            try:
                s.send_bytes(_pcm_frame(1, i, b'\x00' * 4))
            except Exception:  # noqa: BLE001 — server may close mid-burst
                break
        reply = s.wait(lambda m: m.get('type') == 'error', timeout=5)
        assert reply['code'] == 'E_RATE_LIMIT'
        with pytest.raises(WebSocketDisconnect):
            recv_frame(s._ws, timeout=5)

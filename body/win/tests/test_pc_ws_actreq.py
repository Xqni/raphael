"""ws_client.handle_message integration: act_req -> dispatcher -> act_res
envelope (PROTOCOL §3/§7), ping/pong, malformed frames never crash."""
import asyncio
import base64
import json

import pytest

from body.win import automation, ws_client

pytestmark = pytest.mark.asyncio


class FakeWS:
    def __init__(self):
        self.sent = []

    async def send(self, raw):
        self.sent.append(json.loads(raw) if isinstance(raw, str) else raw)


async def _act(ws, action, args=None, lock=False, job='j1', timeout_ms=None):
    frame = {'type': 'act_req', 'v': 1, 'job': job, 'action': action,
             'args': args or {}, 'lock': lock}
    if timeout_ms is not None:
        frame['timeout_ms'] = timeout_ms
    await ws_client.handle_message(json.dumps(frame), ws, None)
    return ws.sent[-1]


async def test_act_req_envelope_and_result(actlog, fake):
    ws = FakeWS()
    res = await _act(ws, 'screenshot', {'max_px': 640}, job='j_e2e')
    assert res['type'] == 'act_res' and res['v'] == 1
    assert res['job'] == 'j_e2e' and res['ok'] is True
    assert base64.b64decode(res['result']['b64'])[:2] == b'\xff\xd8'


async def test_act_req_clipboard_legacy_string_result(actlog, fake):
    ws = FakeWS()
    await _act(ws, 'clipboard', {'op': 'write', 'text': 'phase3-ok'},
               job='j_w')
    await _act(ws, 'clipboard', {'op': 'read'}, job='j_r')
    assert ws.sent[-1]['ok'] is True
    assert ws.sent[-1]['result'] == 'phase3-ok'


async def test_unknown_action_honest_error(actlog, fake):
    ws = FakeWS()
    await _act(ws, 'teleport', job='j_bad')
    res = ws.sent[-1]
    assert res['ok'] is False and 'E_UNSUPPORTED' in res['error']


async def test_lock_busy_envelope(actlog, fake):
    ws = FakeWS()
    assert await automation.acquire_input_lock(0.05)
    try:
        res = await _act(ws, 'input', {'keys': ['enter']}, lock=True,
                         job='j_busy')
    finally:
        automation.release_input_lock()
    assert res['ok'] is False and res['error'] == 'E_LOCK_BUSY'
    assert res['queued'] is True and res['job'] == 'j_busy'


async def test_ping_gets_pong(actlog, fake):
    ws = FakeWS()
    await ws_client.handle_message(json.dumps({'type': 'ping', 'v': 1}), ws, None)
    assert ws.sent == [{'type': 'pong', 'v': 1}]


async def test_non_json_frame_never_crashes(actlog, fake):
    ws = FakeWS()
    await ws_client.handle_message('\udcff binary junk', ws, None)
    await ws_client.handle_message(b'\x00\x01garbage', ws, None)
    assert ws.sent == [], 'malformed frames must be dropped silently'


async def test_act_req_with_non_dict_args(actlog, fake):
    ws = FakeWS()
    await _act(ws, 'volume', args=['not', 'a', 'dict'], job='j_odd')
    assert ws.sent[-1]['ok'] is False
    assert ws.sent[-1]['error'].startswith('E_BAD_MSG')

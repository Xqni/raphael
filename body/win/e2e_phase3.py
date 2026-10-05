"""E2E phase-3 harness (orchestrator): act_req round trip + 1s mic capture.

Run:  python body/win/e2e_phase3.py        (Windows python, script mode)
Exit 0 = PASS. No brain needed (handle_message is called directly).
"""
import asyncio
import base64
import json
import sys
import time

sys.path.insert(0, __file__.rsplit('\\', 1)[0].replace('\\', '/').rsplit('/', 1)[0])

try:
    import ws_client
    import audio_in
except ImportError:
    sys.path.insert(0, 'body/win')
    import ws_client
    import audio_in


class FakeWS:
    def __init__(self):
        self.sent = []

    async def send(self, raw):
        self.sent.append(json.loads(raw) if isinstance(raw, str) else raw)


async def test_act() -> int:
    ws = FakeWS()

    # 1. screenshot (real screen capture -> b64)
    await ws_client.handle_message(json.dumps({
        "type": "act_req", "v": 1, "job": "j_test1",
        "action": "screenshot", "args": {"max_px": 640}, "lock": False}), ws, None)
    r = ws.sent[-1]
    assert r["type"] == "act_res" and r["job"] == "j_test1", r
    assert r["ok"] is True, r
    raw = base64.b64decode(r["result"]["b64"])
    assert len(raw) > 1000 and raw[:2] in (b'\xff\xd8', b'\x89P'), "not jpeg/png"
    print(f"PASS screenshot: {r['result']['bytes']} bytes, magic={raw[:2]!r}")

    # 2. clipboard write -> read
    await ws_client.handle_message(json.dumps({
        "type": "act_req", "v": 1, "job": "j_test2",
        "action": "clipboard", "args": {"op": "write", "text": "phase3-ok"}, "lock": False}), ws, None)
    assert ws.sent[-1]["ok"] is True, ws.sent[-1]
    await ws_client.handle_message(json.dumps({
        "type": "act_req", "v": 1, "job": "j_test3",
        "action": "clipboard", "args": {"op": "read"}, "lock": False}), ws, None)
    r = ws.sent[-1]
    assert r["ok"] and r["result"] == "phase3-ok", r
    print("PASS clipboard: write->read round trip")

    # 3. unsupported action -> honest error, no crash
    await ws_client.handle_message(json.dumps({
        "type": "act_req", "v": 1, "job": "j_test4",
        "action": "teleport", "args": {}, "lock": False}), ws, None)
    r = ws.sent[-1]
    assert r["ok"] is False and "error" in r, r
    print(f"PASS unsupported: {r['error']}")

    # 4. lock busy path (hold lock, request with lock=true)
    import automation
    await automation.acquire_input_lock(timeout=0.1)
    try:
        await ws_client.handle_message(json.dumps({
            "type": "act_req", "v": 1, "job": "j_test5",
            "action": "screenshot", "args": {}, "lock": True}), ws, None)
        r = ws.sent[-1]
        assert r["ok"] is False and r.get("error") == "E_LOCK_BUSY", r
        print("PASS lock busy -> E_LOCK_BUSY")
    finally:
        automation.release_input_lock()
    return 0


async def test_mic() -> int:
    frames = []
    starts = []

    async def on_frame(b):
        frames.append(b)

    async def on_start(d):
        starts.append(d)

    async def on_end():
        pass

    streamer = audio_in.MicStreamer(on_frame, on_start, on_end)
    task = asyncio.create_task(streamer.start_capture(reason='ptt'))
    await asyncio.sleep(1.2)
    await streamer.stop_capture()
    try:
        await asyncio.wait_for(task, timeout=3)
    except asyncio.TimeoutError:
        task.cancel()
    assert starts and starts[0]["sample_rate"] == 16000, starts
    assert starts[0]["encoding"] == "pcm_s16le" and starts[0]["reason"] == "ptt", starts
    total = sum(len(f) for f in frames)
    assert total > 16000, f"only {total} bytes for ~1.2s of 16k mono s16le"
    for f in frames[:3]:
        assert f[:4] == b'RAPH' and f[4] == 1, f"bad hdr {f[:9]!r}"
    # seq is BE u32 at [5:9]
    import struct as _st
    seqs = [_st.unpack('>I', f[5:9])[0] for f in frames[:4]]
    assert seqs == sorted(seqs) and seqs[0] == 0, seqs
    print(f"PASS mic: {len(frames)} frames, {total} bytes, seqs={seqs}, "
          f"start={starts[0]}")
    return 0


async def main() -> int:
    await test_act()
    try:
        await test_mic()
    except ImportError as e:
        print(f"SKIP mic (dependency): {e}")
    print("E2E-PHASE3: PASS")
    return 0


if __name__ == '__main__':
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(0)

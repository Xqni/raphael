"""Wave-2 live E2E: ui session + body sessions + fish TTS + act pipeline.

Orchestrator harness (run manually, mirrors runbook §18-19):
  1. connects an observer ui session + a fake body session
  2. submits `echo hello raphael`  -> fastpath -> narrate -> Fish TTS ->
     speak frames to ui (JSON) + binary kind=2 to body sessions
  3. closes the fake body, submits `screenshot` -> gui tool -> act_req to the
     REAL supervisor-managed body -> act_res -> job done
  4. polls both jobs to terminal state and prints an event histogram

MUTE THE WINDOWS AUDIO FIRST (scripts/win/mute.ps1 -Action On) — the real
body plays TTS out of the speakers.

Exit 0 = PASS.
"""
import asyncio
import base64
import json
import pathlib
import sys
import time
import urllib.request

BRAIN = 'http://127.0.0.1:8765'
WS = 'ws://127.0.0.1:8765/ws'
TOK = pathlib.Path.home().joinpath('.raphael/token').read_text().strip()

import websockets  # brain/.venv has it


def post_job(task: str) -> str:
    req = urllib.request.Request(
        f'{BRAIN}/jobs',
        data=json.dumps({'task': task, 'priority': 1}).encode(),
        headers={'X-Raphael-Token': TOK, 'Content-Type': 'application/json'},
        method='POST')
    return json.loads(urllib.request.urlopen(req, timeout=5).read())['job_id']


def job_state(jid: str) -> dict:
    req = urllib.request.Request(f'{BRAIN}/jobs/{jid}',
                                 headers={'X-Raphael-Token': TOK})
    return json.loads(urllib.request.urlopen(req, timeout=5).read())


async def ui_observer(stats: dict, stop: asyncio.Event):
    async with websockets.connect(WS) as ws:
        await ws.send(json.dumps({'type': 'auth', 'v': 1, 'token': TOK,
                                  'role': 'ui', 'client': 'e2e-ui',
                                  'client_v': '1.0'}))
        stats['ui_connected'] = True
        try:
            while not stop.is_set():
                raw = await asyncio.wait_for(ws.recv(), timeout=2)
                if isinstance(raw, bytes):
                    stats['ui_binary'] = stats.get('ui_binary', 0) + 1
                    continue
                m = json.loads(raw)
                t = m.get('type', '?')
                stats['ui_' + t] = stats.get('ui_' + t, 0) + 1
                if t == 'ping':
                    await ws.send(json.dumps({'type': 'pong', 'v': 1}))
                if t == 'speak' and 'speak_sample' not in stats:
                    stats['speak_sample'] = m
                if t == 'subtitle' and 'subtitle_sample' not in stats:
                    stats['subtitle_sample'] = m
        except asyncio.TimeoutError:
            pass


async def fake_body(stats: dict, stop: asyncio.Event):
    async with websockets.connect(WS) as ws:
        await ws.send(json.dumps({'type': 'auth', 'v': 1, 'token': TOK,
                                  'role': 'body', 'client': 'e2e-body',
                                  'client_v': '1.0'}))
        stats['body_connected'] = True
        try:
            while not stop.is_set():
                raw = await asyncio.wait_for(ws.recv(), timeout=2)
                if isinstance(raw, bytes):
                    stats['bin_frames'] = stats.get('bin_frames', 0) + 1
                    stats['bin_bytes'] = stats.get('bin_bytes', 0) + len(raw)
                    if raw[:4] != b'RAPH':
                        stats['bin_BAD_MAGIC'] = True
                    if raw[4] != 2:
                        stats['bin_BAD_KIND'] = True
                    if 'bin_first' not in stats:
                        stats['bin_first'] = raw[:9].hex()
                    continue
                m = json.loads(raw)
                t = m.get('type', '?')
                stats['body_' + t] = stats.get('body_' + t, 0) + 1
                if t == 'ping':
                    await ws.send(json.dumps({'type': 'pong', 'v': 1}))
        except asyncio.TimeoutError:
            pass


async def wait_job(jid: str, want: str, timeout: float) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = job_state(jid)
        if st.get('status') in (want, 'failed', 'cancelled'):
            return st
        await asyncio.sleep(1)
    return st


async def main() -> int:
    stats: dict = {}
    stop = asyncio.Event()
    ui_task = asyncio.create_task(ui_observer(stats, stop))
    body_task = asyncio.create_task(fake_body(stats, stop))
    await asyncio.sleep(1.5)
    assert stats.get('ui_connected') and stats.get('body_connected'), stats

    # --- speak E2E (Fish TTS; real body plays into MUTED speakers) --------
    echo_id = post_job('echo hello raphael')
    echo = await wait_job(echo_id, 'done', 30)
    print(f"echo job: {echo.get('status')} result={str(echo.get('result'))[:60]}")
    assert echo.get('status') == 'done', echo
    await asyncio.sleep(10)  # let the speak stream finish (async narration)

    # --- close fake body so act routes to the REAL body -------------------
    stop.set()
    await asyncio.gather(ui_task, body_task, return_exceptions=True)
    stop2 = asyncio.Event()
    ui2 = asyncio.create_task(ui_observer(stats, stop2))  # keep observing
    await asyncio.sleep(1)

    shot_id = post_job('screenshot')
    shot = await wait_job(shot_id, 'done', 30)
    print(f"screenshot job: {shot.get('status')} "
          f"result_keys={list((shot.get('result') or {}).keys()) if isinstance(shot.get('result'), dict) else str(shot.get('result'))[:40]}")
    assert shot.get('status') == 'done', shot
    if isinstance(shot.get('result'), dict) and 'b64' in shot['result']:
        raw = base64.b64decode(shot['result']['b64'])
        assert raw[:2] in (b'\xff\xd8', b'\x89P'), 'act result not an image'
        print(f"act result image: {len(raw)} bytes magic={raw[:2]!r}")
    await asyncio.sleep(3)
    stop2.set()
    await ui2

    print("EVENTS:", json.dumps({k: v for k, v in sorted(stats.items())
                                 if not k.endswith('_sample')}, indent=1))
    print("speak_sample:", json.dumps(stats.get('speak_sample'))[:200])
    print("subtitle_sample:", json.dumps(stats.get('subtitle_sample'))[:160])

    # PROTOCOL §4: speak is body-only (ui copies are dropped by capability
    # enforcement) — require body-side speak instead of ui-side.
    ok = (stats.get('ui_subtitle', 0) >= 1
          and stats.get('ui_job_event', 0) >= 3
          and stats.get('body_speak', 0) >= 2
          and stats.get('bin_frames', 0) >= 1
          and not stats.get('bin_BAD_MAGIC')
          and not stats.get('bin_BAD_KIND')
          and shot.get('status') == 'done')
    print("E2E-WAVE2:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))

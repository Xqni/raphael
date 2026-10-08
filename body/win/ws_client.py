"""Async WebSocket client for the Windows Body.
Responsibilities:
- Connect to ws://127.0.0.1:<port>/ws (port/token/lock derive from
  RAPHAEL_INSTANCE — body/win/instance.py, INTERFACES §d; unset = main = 8765).
- Perform token‑based auth handshake.
- Handle act_req frames (delegated to body/win/actions.py, PROTOCOL §7) and
  stream mic audio.

Import discipline: this module is stdlib-only at import time. Heavy deps
(websockets, audio_in/audio_out, hotkeys) load lazily inside the functions
that need them so unit tests and the mock e2e harness can import it on any OS
without side effects (AGENT_RULES §5: prefer mocks).
"""
import asyncio
import json
import pathlib
import sys
import time
from typing import Any

try:
    from . import instance, actions, depfail
except ImportError:
    # Script mode (supervisor runs `python body/win/main.py`) has no package
    # context — fall back to absolute imports via sys.path[0] (body/win).
    import instance
    import actions
    import depfail

_current_ws = None


def _import_late(name: str):
    """Import a body/win module lazily (package or script mode).

    hotkeys/audio_in/audio_out stay OUT of module import: they pull in the
    `keyboard`/`sounddevice` stacks (and their pinned pip fallbacks), which
    unit tests and the mock e2e harness must never trigger (AGENT_RULES §5).
    """
    import importlib
    if __package__:
        return importlib.import_module('.' + name, __package__)
    return importlib.import_module(name)


def _websockets():
    """websockets from the PRE-INSTALLED hash-pinned env only — SEC-9: no
    runtime pip fallback; missing dep fails loud with the requirements hint."""
    depfail.require('websockets')
    import websockets
    return websockets


def read_token() -> str:
    # Per-instance candidates (INTERFACES §d) — never crosses instances.
    for p in instance.token_candidates():
        if p.is_file():
            return p.read_text().strip()
    raise FileNotFoundError(
        'Raphael token not found in any known location: %s'
        % ', '.join(str(p) for p in instance.token_candidates()))


async def send_auth(ws):
    token = read_token()
    auth_msg = {
        "type": "auth",
        "v": 1,
        "token": token,
        "role": "body",
        "client": "body-win",
        "client_v": "1.0",
    }
    await ws.send(json.dumps(auth_msg))


async def handle_message(msg: Any, ws, mic_streamer):
    if isinstance(msg, bytes):
        if len(msg) < 9: return
        if msg[:4] != b'RAPH': return
        kind = msg[4]
        payload = msg[9:]
        if kind == 2: # speak audio
            try:
                audio_out = _import_late('audio_out')
            except ImportError as e:
                print(f"[body-win] TTS chunk dropped (audio_out unavailable: {e})",
                      flush=True)
                return
            await audio_out.play_tts_chunk(payload)
        return

    try:
        data = json.loads(msg)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        # Never die on a non-JSON frame: the pre-phase-3 body CRASHED on the
        # brain's binary kind=2 TTS payloads (UnicodeDecodeError byte 0xfd).
        print(f"[body-win] dropped non-JSON frame ({len(msg)} bytes)", flush=True)
        return

    msg_type = data.get('type')
    if msg_type == 'ping':
        await ws.send(json.dumps({"type": "pong", "v": 1}))
    elif msg_type == 'speak':
        # lifecycle for the continuous player (binary kind=2 carries PCM;
        # these JSON events delimit utterances — old player had no lifecycle
        # and opened a fresh device stream PER CHUNK = the stutter).
        try:
            audio_out = _import_late('audio_out')
        except ImportError as e:
            print(f"[body-win] speak event ignored (audio_out unavailable: {e})",
                  flush=True)
            return
        ev = data.get('event')
        if ev == 'start':
            audio_out.speak_start()
        elif ev == 'end':
            asyncio.get_running_loop().create_task(audio_out.speak_end())
        return

    elif msg_type == 'act_req':
        job = data.get('job')
        action = data.get('action')
        args = data.get('args', {})
        lock_req = bool(data.get('lock', False))
        timeout_ms = data.get('timeout_ms')

        print(f"[body-win] act_req: {action} for job {job}", flush=True)
        # PROTOCOL §7: allow-list, input-lock etiquette (E_LOCK_BUSY),
        # timeout and action-log all live in actions.dispatch().
        # BUG B (docs/BUGS-WAVE2.md): an act_res MUST go out for EVERY
        # act_req — a dispatcher crash used to tear down the receive loop
        # and the Brain sat on an unanswered request until its 30 s timeout.
        t0 = time.monotonic()
        try:
            outcome = await actions.dispatch(
                action, args, lock=lock_req, job=job, timeout_ms=timeout_ms)
        except asyncio.CancelledError:
            raise                      # connection closing — nothing to answer
        except Exception as e:         # noqa: BLE001 — never lose the response
            print(f"[body-win] act_req CRASH {action}: {type(e).__name__}: {e}",
                  flush=True)
            outcome = {"ok": False,
                       "error": "E_INTERNAL: %s: %s"
                                % (type(e).__name__, str(e)[:180])}
        res = {"type": "act_res", "v": 1, "job": job}
        res.update(outcome)
        try:
            await ws.send(json.dumps(res))
        except Exception as e:         # noqa: BLE001 — socket gone with the job
            print(f"[body-win] act_res send failed {action}: {e}", flush=True)
            return
        # Greppable evidence line (the Wave-2 gate greps body.log for act_res).
        print(f"[body-win] act_res: {action} job={job} ok={res.get('ok')} "
              f"ms={int((time.monotonic() - t0) * 1000)}", flush=True)
        return

async def client_once(mic_streamer):
    global _current_ws
    websockets = _websockets()
    async with websockets.connect(instance.ws_url()) as ws:
        _current_ws = ws
        control_task = asyncio.create_task(_drain_control_queue(ws))
        try:
            await asyncio.wait_for(send_auth(ws), timeout=5)
            async for message in ws:
                await handle_message(message, ws, mic_streamer)
        finally:
            _current_ws = None
            control_task.cancel()
            try:
                await control_task
            except (asyncio.CancelledError, Exception):
                pass

async def _drain_control_queue(ws):
    hotkeys = _import_late('hotkeys')
    while True:
        item = await hotkeys._control_queue.get()
        tries = 0
        if isinstance(item, list):
            item, tries = item[0], int(item[1])
        try:
            await ws.send(json.dumps(item))
            print(f"[body-win] control -> {json.dumps(item)}", flush=True)
        except Exception as e:
            if tries < 3:
                try:
                    hotkeys._control_queue.put_nowait([item, tries + 1])
                except asyncio.QueueFull:
                    pass
            else:
                print(f"[body-win] control frame dropped: {e}", flush=True)

def _load_config() -> dict:
    try:
        import yaml
        cfg_path = pathlib.Path(__file__).resolve().parents[2] / 'config.yaml'
        return yaml.safe_load(cfg_path.read_text()) if cfg_path.is_file() else {}
    except Exception:
        return {}

async def start_client():
    global _current_ws
    # Fail fast on a bad instance/port instead of spinning in reconnect
    # (AGENT_RULES §5: never silently fall back to a default port).
    try:
        url = instance.ws_url()
    except ValueError as e:
        print(f"[body-win] instance isolation error: {e}", flush=True)
        return
    print(f"[body-win] instance={instance.instance_name()} -> {url}", flush=True)

    _websockets()  # availability check before the retry loop
    hotkeys = _import_late('hotkeys')
    audio_in = _import_late('audio_in')

    hotkeys.set_loop(asyncio.get_running_loop())
    try:
        hotkeys.register_hotkeys(_load_config())
    except Exception as e:
        print(f'[body-win] hotkey registration failed: {e}', flush=True)
    
    async def on_mic_frame(frame):
        if _current_ws: await _current_ws.send(frame)
    async def on_mic_start(start_frame):
        if _current_ws: await _current_ws.send(json.dumps(start_frame))
    async def on_mic_end(end_frame=None):  # WakeStream/MicStreamer call with 0 args
        if _current_ws: await _current_ws.send(json.dumps({"type": "audio_end", "v": 1}))

    mic_streamer = await audio_in.start_mic_stream(on_mic_frame, on_mic_start, on_mic_end)
    
    # PTT wiring (fixed: the old code compared a single-key event name against
    # the chord string 'ctrl+alt+space' — never matched — AND called
    # get_running_loop() inside the keyboard library's thread, which always
    # raises. Chord hold handled by add_hotkey + trigger_on_release; the loop
    # is captured HERE, on the asyncio side.)
    cfg = _load_config()
    always = bool((cfg.get('voice', {}) or {}).get('always_listen', True))
    ptt_hk = (cfg.get('voice', {}) or {}).get('ptt_hotkey')
    if always:
        # Always-on wake listening (user request 2026-10-05): body streams
        # voice-activity segments with reason='wake'; brain's WakeGate
        # requires the wake word. PTT is skipped (one mic consumer at a time).
        wake = audio_in.WakeStream(on_mic_frame, on_mic_start, on_mic_end)

        async def _run_wake_guarded():
            try:
                await wake.run()
            except Exception as e:  # noqa: BLE001 — silent task death = no mic
                print(f"[body-win] wake task died: {type(e).__name__}: {e}",
                      flush=True)

        asyncio.get_running_loop().create_task(_run_wake_guarded())
        print("[body-win] always-listening ON — say 'Raphael, <command>'",
              flush=True)
    elif ptt_hk:
        import keyboard
        loop = asyncio.get_running_loop()

        def _ptt_press():
            try:
                asyncio.run_coroutine_threadsafe(
                    mic_streamer.start_capture('ptt'), loop)
            except Exception as e:
                print(f"[body-win] PTT press failed: {e}", flush=True)

        def _ptt_release():
            try:
                asyncio.run_coroutine_threadsafe(
                    mic_streamer.stop_capture(), loop)
            except Exception as e:
                print(f"[body-win] PTT release failed: {e}", flush=True)

        keyboard.add_hotkey(ptt_hk, _ptt_press)
        keyboard.add_hotkey(ptt_hk, _ptt_release, trigger_on_release=True)
        print(f"[body-win] PTT '{ptt_hk}' armed — hold to talk", flush=True)
        
    backoff = 5
    max_backoff = 30
    while True:
        try:
            await client_once(mic_streamer)
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[body-win] Connection error: {e}; retrying in {backoff}s", flush=True)
            await asyncio.sleep(backoff)
            backoff = min(max_backoff, backoff * 2)

if __name__ == "__main__":
    asyncio.run(start_client())

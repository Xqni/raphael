"""Async WebSocket client for the Windows Body.
Responsibilities:
- Connect to ws://127.0.0.1:8765/ws (URL from config.yaml).
- Perform token‑based auth handshake.
- Handle act_req frames and stream mic audio.
"""
import asyncio
import json
import os
import random
import pathlib
import sys
import struct
from typing import Any

try:
    from . import hotkeys
    from . import audio_in
    from . import audio_out
    from . import automation
except ImportError:
    import hotkeys
    import audio_in
    import audio_out
    import automation

try:
    import websockets
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--quiet', 'websockets==16.1.1'])
    import websockets

CONFIG_URL = "ws://127.0.0.1:8765/ws"
TOKEN_PATHS = [
    pathlib.Path(os.getenv('APPDATA', ''), 'Raphael', 'token'),
    pathlib.Path.home() / '.raphael' / 'token',
]

_current_ws = None

def read_token() -> str:
    for p in TOKEN_PATHS:
        if p.is_file():
            return p.read_text().strip()
    raise FileNotFoundError('Raphael token not found in any known location')

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
    
    elif msg_type == 'act_req':
        job = data.get('job')
        action = data.get('action')
        args = data.get('args', {})
        lock_req = data.get('lock', False)
        
        print(f"[body-win] act_req: {action} for job {job}", flush=True)
        res = {"type": "act_res", "v": 1, "job": job, "ok": False}
        
        try:
            if lock_req:
                if not await automation.acquire_input_lock(timeout=0.1):
                    res["error"] = "E_LOCK_BUSY"
                    await ws.send(json.dumps(res))
                    return

            if action == 'launch_url':
                import webbrowser
                webbrowser.open(args.get('url', ''))
                res["ok"] = True
            elif action == 'open_app':
                await automation.launch_app(args.get('name', ''))
                res["ok"] = True
            elif action == 'screenshot':
                # script mode: relative import fails (orchestrator fix); the
                # real API is capture_screenshot() -> bytes (not async, not
                # take_screenshot) and bytes are not JSON-serializable.
                try:
                    from . import capture
                except ImportError:
                    import capture
                shot = capture.capture_screenshot(int(args.get('max_px', 1280)))
                res["result"] = {"b64": __import__('base64').b64encode(shot).decode(),
                                 "bytes": len(shot)}
                res["ok"] = True
            elif action == 'uia':
                await automation.perform_uia(args.get('op'), args.get('target', {}), args.get('args', {}))
                res["ok"] = True
            elif action == 'clipboard':
                # pyperclip is NOT a dependency here (phantom dep — never
                # installed); body already has a pywin32-based clipboard.
                try:
                    from . import clipboard as _clip
                except ImportError:
                    import clipboard as _clip
                op = args.get('op')
                if op == 'read':
                    res["result"] = _clip.get_clipboard_text()
                    res["ok"] = True
                elif op == 'write':
                    _clip.set_clipboard_text(args.get('text', ''))
                    res["ok"] = True
            else:
                res["error"] = f"Unsupported action: {action}"
        except Exception as e:
            res["error"] = str(e)
        finally:
            if lock_req:
                automation.release_input_lock()
        
        await ws.send(json.dumps(res))

async def client_once(mic_streamer):
    global _current_ws
    async with websockets.connect(CONFIG_URL) as ws:
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
    hotkeys.set_loop(asyncio.get_running_loop())
    try:
        hotkeys.register_hotkeys(_load_config())
    except Exception as e:
        print(f'[body-win] hotkey registration failed: {e}', flush=True)
    
    async def on_mic_frame(frame):
        if _current_ws: await _current_ws.send(frame)
    async def on_mic_start(start_frame):
        if _current_ws: await _current_ws.send(json.dumps(start_frame))
    async def on_mic_end(end_frame):
        if _current_ws: await _current_ws.send(json.dumps({"type": "audio_end", "v": 1}))

    mic_streamer = await audio_in.start_mic_stream(on_mic_frame, on_mic_start, on_mic_end)
    
    # PTT Wiring
    cfg = _load_config()
    ptt_hk = (cfg.get('voice', {}) or {}).get('ptt_hotkey')
    if ptt_hk:
        import keyboard
        # Use keyboard.on_press/on_release for proper PTT hold behavior
        def on_press(e):
            if e.name == ptt_hk: # Simplified; assumes ptt_hk is a single key name
                asyncio.run_coroutine_threadsafe(mic_streamer.start_capture('ptt'), asyncio.get_running_loop())
        def on_release(e):
            if e.name == ptt_hk:
                asyncio.run_coroutine_threadsafe(mic_streamer.stop_capture(), asyncio.get_running_loop())
        keyboard.on_press(on_press)
        keyboard.on_release(on_release)
        
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

"""Async WebSocket client for the Windows Body.

Responsibilities:
- Connect to ws://127.0.0.1:8765/ws (URL from config.yaml).
- Perform token‑based auth handshake (token read from Windows or fallback to Linux path).
- Respond to server 'ping' frames with a 'pong'.
- Auto‑reconnect with exponential back‑off (5 s → 30 s max, jitter ±20%).
- Expose a single coroutine `start_client()` used by main.py.
"""
import asyncio
import json
import asyncio
try:
    from . import hotkeys
except ImportError:
    import hotkeys  # script mode (supervisor runs `python body/win/main.py`)
import os
import random
import pathlib
import sys

# Attempt to import websockets, install if missing.
try:
    import websockets
except ImportError:
    # Install into the Windows‑side interpreter (the same interpreter running this code).
    import subprocess
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--quiet', 'websockets'])
    import websockets

CONFIG_URL = "ws://127.0.0.1:8765/ws"
TOKEN_PATHS = [
    pathlib.Path(os.getenv('APPDATA', ''), 'Raphael', 'token'),  # Windows default
    pathlib.Path.home() / '.raphael' / 'token',                # Linux fallback (for CI)
]

def read_token() -> str:
    for p in TOKEN_PATHS:
        if p.is_file():
            return p.read_text().strip()
    # If not found, raise – the caller will handle gracefully.
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
    # No explicit timeout here – the server is expected to reply quickly.

async def handle_message(msg: str, ws):
    try:
        data = json.loads(msg)
    except json.JSONDecodeError:
        return  # ignore malformed frames
    msg_type = data.get('type')
    if msg_type == 'ping':
        await ws.send(json.dumps({"type": "pong", "v": 1}))  # envelope per PROTOCOL §3
    # Additional handling (auth_ok, orb_state, etc.) can be added later.

async def client_once():
    async with websockets.connect(CONFIG_URL) as ws:
        # Drain must die WITH the connection (else tasks pile up across
        # reconnects, all holding a reference to a closed ws).
        control_task = asyncio.create_task(_drain_control_queue(ws))
        try:
            await asyncio.wait_for(send_auth(ws), timeout=5)
            async for message in ws:
                await handle_message(message, ws)
        finally:
            control_task.cancel()
            try:
                await control_task
            except (asyncio.CancelledError, Exception):
                pass


async def _drain_control_queue(ws):
    """Continuously send control frames queued by hotkeys."""
    while True:
        item = await hotkeys._control_queue.get()
        try:
            await ws.send(json.dumps(item))
            print(f"[body-win] control -> {json.dumps(item)}", flush=True)
        except Exception as e:
            print(f"[body-win] Failed to send control frame: {e}", flush=True)
            # Re-queue once (bounded: queue is hotkey-rate, never a flood).
            try:
                hotkeys._control_queue.put_nowait(item)
            except asyncio.QueueFull:
                pass

def _load_config() -> dict:
    """repo config.yaml (script-relative) — hotkey bindings; {} if absent."""
    try:
        import subprocess as _sp
        try:
            import yaml  # noqa
        except ImportError:
            _sp.check_call([sys.executable, '-m', 'pip', 'install', '--quiet', 'PyYAML'])
            import yaml  # noqa
        cfg_path = pathlib.Path(__file__).resolve().parents[2] / 'config.yaml'
        return yaml.safe_load(cfg_path.read_text()) or {}
    except Exception as e:
        print(f'[body-win] config load failed ({e}) — hotkeys use defaults only', flush=True)
        return {}


async def start_client():
    """Run the client with reconnection logic.

    The function never returns unless the process is terminating.
    """
    # Hotkeys need the running loop (keyboard fires on its own thread) and
    # must be registered exactly once, before any connection.
    hotkeys.set_loop(asyncio.get_running_loop())
    try:
        hotkeys.register_hotkeys(_load_config())
    except Exception as e:
        print(f'[body-win] hotkey registration failed: {e}', flush=True)
    backoff = 5
    max_backoff = 30
    while True:
        try:
            await client_once()
        except asyncio.CancelledError:
            print('[body-win] Shutdown requested, exiting client loop.', flush=True)
            break
        except (OSError, websockets.exceptions.WebSocketException) as e:
            print(f"[body-win] Connection error: {e}; retrying in {backoff}s", flush=True)
        except asyncio.TimeoutError as e:
            print(f"[body-win] Timeout during handshake: {e}; retrying in {backoff}s", flush=True)
        except FileNotFoundError as e:
            print(f"[body-win] {e}; cannot proceed without token.", flush=True)
            return
        jitter = random.uniform(-0.2, 0.2) * backoff
        wait = max(1, backoff + jitter)
        await asyncio.sleep(wait)
        backoff = min(max_backoff, backoff * 2)


# Entry point for debugging (not used by main.py which calls start_client)
if __name__ == "__main__":
    asyncio.run(start_client())

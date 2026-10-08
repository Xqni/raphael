"""AUD-05 (my half): push foreground-window facts to the Brain.

Why: the router's chat egress gate reads a 60 s-fresh foreground ring
(`brain.vision.context.record_foreground` → app lifespan provider →
`router.set_foreground_check`), whose ONLY feeder was the vision probe ring —
nobody probed while idle, so the gate starved at night (chat permanently
E_OFFLINE). This module keeps the ring fed:

* **connect snapshot** — pushed by ws_client right after `auth_ok`;
* **focus-change push** — primary: a Win32 `SetWinEventHook`
  (EVENT_SYSTEM_FOREGROUND, out-of-context) on a dedicated message-pump
  thread (event-driven, detection latency ~ms); fallback (non-Windows /
  hook failure): 1 s poll; plus a 30 s safety resync in both modes;
* **lock-free** — `foreground_info`/`backend.foreground()` is `needs_lock:
  False` (read-only query), so no input lock is ever taken here (AUD-05
  latency budget: push-to-cache < 100 ms local — measured in tests).

Frame (PROTOCOL §3, declared under the AUD-05 grant):
  {"type": "foreground", "v": 1, "ts": <ms>, "window": {hwnd, title,
   process, pid} | null}
Brain-core's consumer (docs/requests/pc-control__to__brain-core__
foreground-frame-consumer.md) folds it into the ring as `"title | process"`
— the exact identity shape the computer-use gateway already produces
(brain/tools/computer_use/gateway.py:134).

Body-side only: dumb pipe, deduped (same hwnd+title+process = no frame),
force=True on connect. Never raises into the client loop; a failed send
clears the dedupe key so the next tick retries.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable, Dict, Optional

try:
    from . import winlayer
except ImportError:          # script mode (body/win on sys.path)
    import winlayer

POLL_S = 1.0                # fallback poll (fallback only — lock-free read)
RESYNC_S = 30.0             # safety resync even when the hook is healthy
_EVENT_SYSTEM_FOREGROUND = 0x0003
_WINEVENT_OUTOFCONTEXT = 0x0000

_sender: Optional[Callable[[Dict[str, Any]], Awaitable[bool]]] = None
_loop: Optional[asyncio.AbstractEventLoop] = None
_last_key: Optional[tuple] = None
_started = False
_hook_ok = False
_hook_ref = None            # keeps the Win32 callback alive
_tasks: list = []


def set_sender(sender: Callable[[Dict[str, Any]], Awaitable[bool]]) -> None:
    """ws_client installs `async frame -> bool sent` (False = not connected)."""
    global _sender
    _sender = sender


def build_frame(force: bool = False) -> Optional[Dict[str, Any]]:
    """Query the foreground (lock-free) and build the push frame.

    Returns None when nothing changed (dedupe) — `force` bypasses dedupe
    (connect snapshot). Records the dedupe key ONLY on a successful send
    (caller clears it on failure via `invalidate()`)."""
    win = winlayer.get_backend().foreground()
    key = None
    if isinstance(win, dict):
        key = (win.get('hwnd'), win.get('title'), win.get('process'))
    if not force and key == _last_key:
        return None
    return {'type': 'foreground', 'v': 1, 'ts': int(time.time() * 1000),
            'window': (None if not isinstance(win, dict) else
                       {k: win.get(k) for k in
                        ('hwnd', 'title', 'process', 'pid')})}


def mark_sent(frame: Dict[str, Any]) -> None:
    """Remember what we pushed (dedupe key = window identity)."""
    global _last_key
    win = frame.get('window')
    _last_key = ((win or {}).get('hwnd'), (win or {}).get('title'),
                 (win or {}).get('process')) if isinstance(win, dict) else None


def invalidate() -> None:
    """A failed send must retry on the next tick."""
    global _last_key
    _last_key = None


def reset() -> None:
    """Tests: forget dedupe + start state."""
    global _last_key, _started, _hook_ok, _tasks
    for t in _tasks:
        t.cancel()
    _tasks = []
    _last_key = None
    _started = False
    _hook_ok = False


async def push(force: bool = False) -> Optional[Dict[str, Any]]:
    """Build + send one frame through the installed sender.

    Never raises: an unconnected sender (False), a backend failure or a
    closed sender leaves the dedupe cleared so the change is retried."""
    try:
        frame = build_frame(force=force)
    except Exception as e:  # noqa: BLE001 — backend issues are not fatal
        print('[foreground] build failed: %s' % e, flush=True)
        invalidate()
        return None
    if frame is None:
        return None
    if _sender is None:
        invalidate()
        return None
    try:
        sent = await _sender(frame)
    except Exception as e:  # noqa: BLE001 — push must never kill the loop
        print('[foreground] push failed: %s' % e, flush=True)
        invalidate()
        return None
    if sent:
        mark_sent(frame)
    else:
        invalidate()
    return frame if sent else None


async def check_once(force: bool = False) -> Optional[Dict[str, Any]]:
    """One detection cycle (event callback / poll tick / resync call it)."""
    try:
        return await push(force=force)
    except Exception as e:  # noqa: BLE001 — backend issues are not fatal
        print('[foreground] check failed: %s' % e, flush=True)
        return None


# ------------------------------------------------------------- transport ---
def _wake_scheduled() -> None:
    """Runs ON THE LOOP (scheduled from the hook thread)."""
    if _loop is not None:
        _loop.create_task(check_once())


def _hook_thread() -> None:
    """Win32 foreground hook + message pump (dedicated daemon thread)."""
    import ctypes
    from ctypes import wintypes

    CALLBACK = ctypes.WINFUNCTYPE(
        None, wintypes.HANDLE, wintypes.DWORD, wintypes.HWND,
        wintypes.LONG, wintypes.LONG, wintypes.DWORD, wintypes.DWORD)

    def _cb(_hook, _event, _hwnd, _obj, _child, _thread, _ms):
        if _loop is not None:
            try:
                _loop.call_soon_threadsafe(_wake_scheduled)
            except RuntimeError:
                pass                      # loop closed during shutdown

    _cb_ref = CALLBACK(_cb)               # keep alive for the hook's life
    global _hook_ref
    _hook_ref = _cb_ref
    user32 = ctypes.windll.user32
    hook = user32.SetWinEventHook(
        _EVENT_SYSTEM_FOREGROUND, _EVENT_SYSTEM_FOREGROUND, 0, _cb_ref,
        0, 0, _WINEVENT_OUTOFCONTEXT)
    if not hook:
        raise OSError('SetWinEventHook failed')

    class MSG(ctypes.Structure):
        _fields_ = [('hwnd', wintypes.HWND), ('message', wintypes.UINT),
                    ('wParam', wintypes.WPARAM), ('lParam', wintypes.LPARAM),
                    ('time', wintypes.DWORD),
                    ('pt', wintypes.POINT)]

    msg = MSG()
    while user32.GetMessageW(ctypes.byref(msg), 0, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))


async def _poll_loop() -> None:
    """Fallback / safety-resync sampler (lock-free read, cheap)."""
    while True:
        try:
            await asyncio.sleep(POLL_S)
            await check_once()
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 — sampler never dies
            print('[foreground] poll tick failed: %s' % e, flush=True)


async def _resync_loop() -> None:
    """Even a healthy hook can miss edges (hook loss, WS reconnect gap)."""
    while True:
        try:
            await asyncio.sleep(RESYNC_S)
            await check_once(force=True)   # force: refresh ring ts on idle
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            print('[foreground] resync failed: %s' % e, flush=True)


def start(loop: asyncio.AbstractEventLoop) -> Dict[str, Any]:
    """Idempotent: start the focus watcher (hook, fallback poll) + resync.

    Returns {'hook': bool, 'poll': bool} for diagnostics/tests."""
    global _started, _loop, _hook_ok
    if _started:
        return {'hook': _hook_ok, 'poll': not _hook_ok}
    _loop = loop
    _started = True
    if loop is not None and os_name() == 'nt':
        try:
            import threading
            t = threading.Thread(target=_hook_thread, name='fg-hook',
                                 daemon=True)
            t.start()
            _hook_ok = True
        except Exception as e:  # noqa: BLE001 — fall back to polling
            _hook_ok = False
            print('[foreground] hook unavailable, polling every %.1fs: %s'
                  % (POLL_S, e), flush=True)
    if not _hook_ok:
        _tasks.append(loop.create_task(_poll_loop()))
    _tasks.append(loop.create_task(_resync_loop()))
    return {'hook': _hook_ok, 'poll': not _hook_ok}


def os_name() -> str:
    import os
    return os.name

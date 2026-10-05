"""Global hotkeys for the Windows Body -> PROTOCOL `control` frames.

Bindings (config.yaml, all remappable):
  safety.kill_switch_hotkey  -> control action=kill_gui   (momentary, persist:false)
  safety.pause_hotkey        -> control action=pause/resume (toggle, persist:true)
  safety.private_hotkey      -> control action=private_on/off (toggle, persist:true)
  voice.ptt_hotkey           -> RESERVED for voice phase 3 (mic streaming; no
                                control frame exists for PTT in PROTOCOL §3)

Threading: the `keyboard` library fires callbacks on ITS OWN thread, so frames
are handed to the asyncio loop via run_coroutine_threadsafe() (calling
asyncio.create_task() from that thread would raise "no running event loop").
Envelope per PROTOCOL §3: {"type": "control", "v": 1, "action": ..., "persist": bool}.
"""
import asyncio
import sys
import subprocess

def _ensure_pkg(pkg: str, import_name: str = None, pin: str = ''):
    """Import-or-install, PINNED (security: unpinned runtime pip = supply chain)."""
    try:
        __import__(import_name or pkg)
    except ImportError:
        import subprocess, sys
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--quiet',
                               ('%s==%s' % (pkg, pin)) if pin else pkg])
        __import__(import_name or pkg)

_ensure_pkg('keyboard', pin='0.13.5')
import keyboard

# Frames queue drained by ws_client._drain_control_queue (async consumer).
_control_queue: asyncio.Queue = asyncio.Queue()

# Main event loop, captured by ws_client.start_client() — keyboard callbacks
# (other thread) post into it with run_coroutine_threadsafe().
_main_loop: asyncio.AbstractEventLoop | None = None
_registered = False
_private_state = False  # server-side mode is authoritative; this only toggles


def set_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _main_loop
    _main_loop = loop


def _post(action: str, persist: bool) -> None:
    """Thread-safe: queue one control frame onto the asyncio loop."""
    frame = {"type": "control", "v": 1, "action": action, "persist": persist}
    if _main_loop is None or not _main_loop.is_running():
        print(f"[hotkeys] dropped {action} (no event loop yet)", flush=True)
        return
    asyncio.run_coroutine_threadsafe(_control_queue.put(frame), _main_loop)
    print(f"[hotkeys] queued control: {action} (persist={persist})", flush=True)


def register_hotkeys(config: dict) -> None:
    """Wire config.yaml bindings. Safe to call once from the asyncio side."""
    global _registered, _private_state
    if _registered:
        return
    safety = config.get('safety', {}) or {}

    ks = safety.get('kill_switch_hotkey')
    if ks:
        keyboard.add_hotkey(ks, lambda: _post('kill_gui', False))

    pause_hk = safety.get('pause_hotkey')
    _paused = False

    def _pause_toggle():
        nonlocal _paused
        _paused = not _paused
        _post('pause' if _paused else 'resume', True)

    if pause_hk:
        keyboard.add_hotkey(pause_hk, _pause_toggle)

    priv_hk = safety.get('private_hotkey')

    def _private_toggle():
        global _private_state
        _private_state = not _private_state
        _post('private_on' if _private_state else 'private_off', True)

    if priv_hk:
        keyboard.add_hotkey(priv_hk, _private_toggle)

    ptt = (config.get('voice', {}) or {}).get('ptt_hotkey')
    if ptt:
        # PTT is wired where the mic lives (ws_client.start_client ->
        # audio_in.MicStreamer), not as a control frame — see its
        # "hold to talk" log line. This is only a visibility note.
        print(f"[hotkeys] PTT '{ptt}' wired via ws_client (mic lane)", flush=True)

    import atexit
    atexit.register(unregister_hotkeys)
    _registered = True
    bound = [b for b in (ks, pause_hk, priv_hk) if b]
    print(f"[hotkeys] registered: {', '.join(bound) or 'none'}", flush=True)


def unregister_hotkeys() -> None:
    try:
        keyboard.unhook_all_hotkeys()
    except Exception:
        pass


if __name__ == '__main__':
    # Manual debugging: python hotkeys.py  (prints frames; Ctrl+C to stop)
    import pathlib
    _ensure_pkg('yaml')
    import yaml
    cfg_path = pathlib.Path(__file__).resolve().parents[2] / 'config.yaml'
    cfg = yaml.safe_load(cfg_path.read_text()) if cfg_path.is_file() else {}
    asyncio.run(_selftest(cfg))


async def _selftest(cfg: dict):
    set_loop(asyncio.get_running_loop())
    register_hotkeys(cfg)
    print('Hotkeys active — press bindings; Ctrl+C exits.')
    try:
        while True:
            frame = await asyncio.wait_for(_control_queue.get(), timeout=1)
            print('FRAME:', frame, flush=True)
    except asyncio.TimeoutError:
        pass
    except KeyboardInterrupt:
        pass

"""Global hotkeys for the Windows Body -> PROTOCOL `control` frames.

Bindings (config.yaml, all remappable):
  safety.kill_switch_hotkey  -> control action=kill_gui   (momentary, persist:false)
  safety.pause_hotkey        -> control action=pause/resume (toggle, persist:true)
  safety.private_hotkey      -> control action=private_on/off (toggle, persist:true)
  voice.ptt_hotkey           -> RESERVED for voice phase 3 (mic streaming; no
                                control frame exists for PTT in PROTOCOL §3)

Contract-testable core: `build_bindings(config)` is PURE — it maps config to
binding descriptors without touching the `keyboard` library, so the envelope
and action enums are unit-tested WITHOUT registering real hotkeys (instance
rule: lanes never register global hotkeys — AGENT_RULES §5 / INTERFACES §d).
`register_hotkeys()` is the only place that touches `keyboard`, and it runs
only in the live body.

Threading: the `keyboard` library fires callbacks on ITS OWN thread, so frames
are handed to the asyncio loop via run_coroutine_threadsafe() (calling
asyncio.create_task() from that thread would raise "no running event loop").
Envelope per PROTOCOL §3: {"type": "control", "v": 1, "action": ..., "persist": bool}.
"""
import asyncio
import sys

# Frames queue drained by ws_client._drain_control_queue (async consumer).
_control_queue: asyncio.Queue = asyncio.Queue()

# Main event loop, captured by ws_client.start_client() — keyboard callbacks
# (other thread) post into it with run_coroutine_threadsafe().
_main_loop: asyncio.AbstractEventLoop | None = None
_registered = False
_private_state = False  # server-side mode is authoritative; this only toggles


def build_bindings(config: dict) -> list:
    """Pure config -> binding descriptors (no side effects).

    Each descriptor:
      {'chord': str, 'kind': 'once'|'toggle', 'persist': bool,
       'action': str}                       # kind 'once'
      {'chord': str, 'kind': 'toggle', 'persist': bool,
       'actions': [first_press, next_press]} # kind 'toggle'
    """
    safety = (config or {}).get('safety', {}) or {}
    bindings: list = []
    ks = safety.get('kill_switch_hotkey')
    if ks:
        bindings.append({'chord': str(ks), 'kind': 'once', 'persist': False,
                         'action': 'kill_gui'})
    pause = safety.get('pause_hotkey')
    if pause:
        bindings.append({'chord': str(pause), 'kind': 'toggle', 'persist': True,
                         'actions': ['pause', 'resume']})
    priv = safety.get('private_hotkey')
    if priv:
        bindings.append({'chord': str(priv), 'kind': 'toggle', 'persist': True,
                         'actions': ['private_on', 'private_off']})
    return bindings


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


def _toggler(actions: list, persist: bool):
    """Return a callback alternating between the two toggle actions."""
    state = {'n': 0}

    def _cb():
        action = actions[state['n'] % len(actions)]
        state['n'] += 1
        _post(action, persist)

    return _cb


def register_hotkeys(config: dict) -> None:
    """Wire config.yaml bindings via the keyboard library. Live body only —
    tests contract-check `build_bindings()` instead (never registers)."""
    global _registered
    if _registered:
        return
    import keyboard

    bindings = build_bindings(config)
    for b in bindings:
        if b['kind'] == 'once':
            action, persist = b['action'], b['persist']
            keyboard.add_hotkey(b['chord'],
                                lambda a=action, p=persist: _post(a, p))
        else:
            keyboard.add_hotkey(b['chord'], _toggler(b['actions'], b['persist']))

    ptt = ((config or {}).get('voice', {}) or {}).get('ptt_hotkey')
    if ptt:
        # PTT is wired where the mic lives (ws_client.start_client ->
        # audio_in.MicStreamer), not as a control frame — see its
        # "hold to talk" log line. This is only a visibility note.
        print(f"[hotkeys] PTT '{ptt}' wired via ws_client (mic lane)", flush=True)

    import atexit
    atexit.register(unregister_hotkeys)
    _registered = True
    bound = ', '.join(b['chord'] for b in bindings) or 'none'
    print(f"[hotkeys] registered: {bound}", flush=True)


def unregister_hotkeys() -> None:
    try:
        import keyboard
        keyboard.unhook_all_hotkeys()
    except Exception:  # noqa: BLE001 — keyboard may never have loaded
        pass


if __name__ == '__main__':
    # Manual debugging: python hotkeys.py  (prints frames; Ctrl+C to stop)
    import pathlib
    try:
        from . import depfail
    except ImportError:
        import depfail
    depfail.require('PyYAML', 'yaml')   # pre-installed env only (SEC-9)
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

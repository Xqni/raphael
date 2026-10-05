"""Hotkey registration for the Windows Body.

Defines the kill‑switch, PTT, private‑mode, and pause hotkeys as declared in
`config.yaml`. Uses the `keyboard` library for global hotkeys (installed on
first import). Each hotkey triggers a coroutine that sends a `control`
message to the Brain – the actual sending is delegated to ws_client via a
simple callback registry.
"""
import asyncio
import sys
import subprocess

def _ensure_pkg(name: str):
    try:
        __import__(name)
    except ImportError:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--quiet', name])
        __import__(name)

_ensure_pkg('keyboard')
import keyboard

# Placeholder: a global asyncio.Queue that the ws_client could consume to
# emit control frames. For the minimal wave we simply print actions.
_control_queue: asyncio.Queue = asyncio.Queue()

async def _send_control(action: str):
    await _control_queue.put({"type": "control", "action": action, "persist": False})
    print(f'[hotkeys] queued control action: {action}', flush=True)

def register_hotkeys(config: dict):
    # Expected keys in config['safety']: kill_switch_hotkey, pause_persist, etc.
    ks = config.get('safety', {}).get('kill_switch_hotkey')
    if ks:
        keyboard.add_hotkey(ks, lambda: asyncio.create_task(_send_control('kill_gui')))
    ptt = config.get('voice', {}).get('ptt_hotkey')
    if ptt:
        keyboard.add_hotkey(ptt, lambda: asyncio.create_task(_send_control('private_on')))
    # Additional hotkeys can be added similarly.

# For manual debugging – load config.yaml and register.
if __name__ == '__main__':
    import yaml, pathlib
    cfg_path = pathlib.Path('config.yaml')
    cfg = yaml.safe_load(cfg_path.read_text())
    register_hotkeys(cfg)
    print('Hotkeys registered. Press ESC to exit.')
    keyboard.wait('esc')

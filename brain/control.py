"""Shared control-action logic for REST /control and WS `control` frames
(PROTOCOL §3). kill_gui is momentary (never persisted); pause/resume/private/
watch persist across restarts.
"""
from typing import Any, Dict

from .jobs.engine import get_engine
from .mode import get_mode

CONTROL_ACTIONS = {
    'pause', 'resume', 'private_on', 'private_off',
    'kill_gui', 'watch_on', 'watch_off',
}


def apply_control(action: str, persist: bool = True) -> Dict[str, Any]:
    if action not in CONTROL_ACTIONS:
        raise ValueError(f'unknown control action: {action}')
    mode = get_mode()
    engine = get_engine()
    if action == 'kill_gui':
        # momentary: halt GUI-driving jobs now, release the input lock
        n = engine.cancel_gui()
        return {'ok': True, 'action': action, 'cancelled': n,
                'mode': mode.label(), 'persisted': False}
    if action == 'pause':
        engine.pause()
    elif action == 'resume':
        engine.resume()
    label = mode.set(action, persist=persist)
    return {'ok': True, 'action': action, 'mode': label, 'persisted': persist,
            **({'paused': engine.paused} if action in ('pause', 'resume') else {})}

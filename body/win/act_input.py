"""`input` action — atomic key/mouse units (PROTOCOL §7
`input{keys|mouse, dx, dy}`).

Guarantees:
* ONE action = one atomic unit: executed inline (no timeout cut — dispatch
  marks it `atomic`), so a chord/sequence can never be half-released;
* every chord releases its modifiers in `finally` (stuck-Ctrl impossible);
* mouse failsafe (config `safety.failsafe_corner`, default ON): the cursor
  sitting in the top-left corner aborts BEFORE each unit — same semantics
  as pyautogui's fail-safe;
* validation is strict: key names come from winlayer.KEYMAP only (no raw
  scan codes), mouse actions from a fixed enum.

Execution order within one action: mouse -> clear_first+text -> keys.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

try:
    from .actions import (ActionError, opt_bool, reject_extra, req_str,
                          register_action)
    from .winlayer import KEYMAP, MODIFIERS
except ImportError:  # script mode
    from actions import (ActionError, opt_bool, reject_extra, req_str,
                         register_action)
    from winlayer import KEYMAP, MODIFIERS

FAILSAFE_PX = 10          # cursor within (0..10, 0..10) => abort (pyautogui-style)
_MAX_KEYS = 32
_MAX_TEXT = 500
_MAX_COORD = 32767
_MAX_REL = 10000
_MOUSE_ACTIONS = {'move', 'click', 'dblclick', 'rightclick', 'scroll', 'drag'}
_BUTTONS = {'left', 'right', 'middle'}
# Lower-case lookup table (KEYMAP carries both cases; VK is identical).
_KEY_ALIASES = {k.lower(): v for k, v in KEYMAP.items()}

_FAILSAFE: Optional[bool] = None   # cached config read; tests can override


def failsafe_enabled() -> bool:
    """config safety.failsafe_corner (default True when unreadable)."""
    global _FAILSAFE
    if _FAILSAFE is None:
        enabled = True
        try:
            import pathlib
            import yaml
            cfg_path = pathlib.Path(__file__).resolve().parents[2] / 'config.yaml'
            if cfg_path.is_file():
                cfg = yaml.safe_load(cfg_path.read_text()) or {}
                enabled = bool((cfg.get('safety') or {}).get('failsafe_corner', True))
        except Exception:  # noqa: BLE001 — default to the safe reading
            enabled = True
        _FAILSAFE = enabled
    return _FAILSAFE


def _check_corner(backend) -> None:
    if not failsafe_enabled():
        return
    x, y = backend.mouse_position()
    if 0 <= x <= FAILSAFE_PX and 0 <= y <= FAILSAFE_PX:
        raise ActionError('E_INTERNAL',
                          'mouse failsafe triggered (cursor in the top-left '
                          'corner) — remaining input aborted')


def _validate_chord(chord: Any) -> str:
    if not isinstance(chord, str) or not chord or len(chord) > 60:
        raise ValueError("field 'keys' entries must be short strings")
    parts = [p.strip().lower() for p in chord.split('+')]
    if any(not p for p in parts) or len(parts) > 5:
        raise ValueError("field 'keys' has a malformed key chord")
    unknown = [p for p in parts if p not in _KEY_ALIASES]
    if unknown:
        raise ValueError("field 'keys' contains an unknown key name")
    final = parts[-1]
    if final in MODIFIERS:
        raise ValueError("field 'keys' chords must end with a non-modifier key")
    for mod in parts[:-1]:
        if mod not in MODIFIERS:
            raise ValueError("only ctrl/shift/alt/win may modify a chord")
    return '+'.join(parts)


def _validate_mouse(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("field 'mouse' must be a JSON object")
    reject_extra(raw, {'action', 'x', 'y', 'dx', 'dy', 'button', 'clicks',
                       'amount', 'steps'}, where="field 'mouse'")
    if 'action' not in raw:
        raise ValueError("field 'mouse' requires 'action'")
    action = raw['action']
    if not isinstance(action, str) or action not in _MOUSE_ACTIONS:
        raise ValueError("field 'mouse.action' must be one of: %s"
                         % ', '.join(sorted(_MOUSE_ACTIONS)))
    out: Dict[str, Any] = {'action': action}

    def coord(key, lo, hi):
        v = raw.get(key)
        if v is None:
            return None
        if isinstance(v, bool) or not isinstance(v, int):
            raise ValueError("field 'mouse.%s' must be an integer" % key)
        if not (lo <= v <= hi):
            raise ValueError("field 'mouse.%s' out of range" % key)
        return v

    x, y = coord('x', -_MAX_COORD, _MAX_COORD), coord('y', -_MAX_COORD, _MAX_COORD)
    dx, dy = coord('dx', -_MAX_REL, _MAX_REL), coord('dy', -_MAX_REL, _MAX_REL)
    if (x is None) != (y is None):
        raise ValueError("field 'mouse' needs x and y together")
    if (dx is None) != (dy is None):
        raise ValueError("field 'mouse' needs dx and dy together")

    if action == 'move':
        if (x is None) == (dx is None):
            raise ValueError("move needs either absolute x/y or relative dx/dy")
        if x is not None:
            out.update(x=x, y=y)
        else:
            out.update(dx=dx, dy=dy)
    elif action in ('click', 'dblclick', 'rightclick'):
        button = raw.get('button') or ('right' if action == 'rightclick'
                                       else 'left')
        if button not in _BUTTONS:
            raise ValueError("field 'mouse.button' must be left/right/middle")
        clicks = raw.get('clicks', 2 if action == 'dblclick' else 1)
        if isinstance(clicks, bool) or not isinstance(clicks, int) or not (1 <= clicks <= 3):
            raise ValueError("field 'mouse.clicks' must be 1..3")
        out.update(button=button, clicks=clicks)
        if x is not None:
            out.update(x=x, y=y)
    elif action == 'scroll':
        amount = raw.get('amount')
        if isinstance(amount, bool) or not isinstance(amount, int) or not (1 <= abs(amount) <= 120):
            raise ValueError("field 'mouse.amount' must be a wheel amount 1..120 (negative = down)")
        out['amount'] = amount
        if x is not None:
            out.update(x=x, y=y)
    elif action == 'drag':
        if x is None:
            raise ValueError("drag needs absolute x/y target")
        button = raw.get('button', 'left')
        if button not in _BUTTONS:
            raise ValueError("field 'mouse.button' must be left/right/middle")
        steps = raw.get('steps', 10)
        if isinstance(steps, bool) or not isinstance(steps, int) or not (1 <= steps <= 50):
            raise ValueError("field 'mouse.steps' must be 1..50")
        out.update(x=x, y=y, button=button, steps=steps)
    return out


def _validate_input(args: Dict[str, Any]) -> Dict[str, Any]:
    reject_extra(args, {'keys', 'text', 'mouse', 'clear_first'})
    has = [k for k in ('keys', 'text', 'mouse') if args.get(k) is not None]
    if not has:
        raise ValueError("input needs one of: keys, text, mouse")
    out: Dict[str, Any] = {}
    if args.get('keys') is not None:
        raw = args['keys']
        if not isinstance(raw, list) or not (1 <= len(raw) <= _MAX_KEYS):
            raise ValueError("field 'keys' must be a list of 1..%d chords" % _MAX_KEYS)
        out['keys'] = [_validate_chord(c) for c in raw]
    if args.get('text') is not None:
        text = req_str(args, 'text', max_len=_MAX_TEXT, min_len=1)
        if any(ord(ch) < 32 for ch in text):
            raise ValueError("field 'text' must not contain control characters")
        out['text'] = text
        out['clear_first'] = opt_bool(args, 'clear_first', default=False)
    if args.get('mouse') is not None:
        out['mouse'] = _validate_mouse(args['mouse'])
    if args.get('clear_first') and 'text' not in out:
        raise ValueError("field 'clear_first' only applies together with 'text'")
    return out


# ------------------------------------------------------------- execution ---
def _press(backend, name: str, pressed: List[str]) -> None:
    backend.key_down(_KEY_ALIASES[name])
    pressed.append(name)


def _release(backend, name: str) -> None:
    backend.key_up(_KEY_ALIASES[name])


def _chord(backend, chord: str) -> None:
    parts = chord.split('+')
    pressed: List[str] = []
    try:
        for mod in parts[:-1]:
            _press(backend, mod, pressed)
        _press(backend, parts[-1], pressed)
        time.sleep(0.01)
        _release(backend, parts[-1])
        pressed.pop()
    finally:
        for name in reversed(pressed):       # never leave a modifier stuck
            try:
                _release(backend, name)
            except Exception:  # noqa: BLE001 — best-effort release
                pass


def _mouse_unit(backend, m: Dict[str, Any]) -> None:
    action = m['action']
    if action == 'move':
        if 'x' in m:
            backend.mouse_move(m['x'], m['y'])
        else:
            backend.mouse_move_rel(m['dx'], m['dy'])
    elif action in ('click', 'dblclick', 'rightclick'):
        backend.mouse_click(m.get('button', 'left'), m.get('x'), m.get('y'),
                            m.get('clicks', 1))
    elif action == 'scroll':
        if 'x' in m:
            backend.mouse_move(m['x'], m['y'])
        backend.mouse_scroll(m['amount'])
    elif action == 'drag':
        x0, y0 = backend.mouse_position()
        tx, ty = m['x'], m['y']
        steps = m.get('steps', 10)
        backend.mouse_down(m.get('button', 'left'))
        try:
            for i in range(1, steps + 1):
                _check_corner(backend)
                backend.mouse_move(int(x0 + (tx - x0) * i / steps),
                                   int(y0 + (ty - y0) * i / steps))
        finally:
            backend.mouse_up(m.get('button', 'left'))


async def _run_input(args: Dict[str, Any], backend) -> Dict[str, Any]:
    # Atomic: NO awaits inside — dispatch runs this without a timeout cut.
    _check_corner(backend)
    if 'mouse' in args:
        _mouse_unit(backend, args['mouse'])
        _check_corner(backend)
    typed = 0
    if args.get('text'):
        if args.get('clear_first'):
            pressed: List[str] = []
            try:
                _press(backend, 'ctrl', pressed)
                _press(backend, 'a', pressed)
                _release(backend, 'a')
                pressed.pop()
                time.sleep(0.03)
            finally:
                for name in reversed(pressed):
                    _release(backend, name)
        backend.type_text(args['text'])
        typed = len(args['text'])
    n_keys = 0
    for chord in args.get('keys') or []:
        _check_corner(backend)
        _chord(backend, chord)
        n_keys += 1
    return {'units': (1 if 'mouse' in args else 0) + (1 if typed else 0) + n_keys,
            'keys': n_keys, 'typed_chars': typed}


register_action('input', _run_input, validate=_validate_input,
                needs_lock=True, confirm=None, atomic=True,
                describe='Inject one atomic input unit (key chords, text, '
                         'or a mouse action) with a mouse failsafe.')

"""Window actions (PROTOCOL §7 `window{op}`) plus the two window-inspection
additions requested in docs/requests/pc-control__to__integrator__protocol-act-req-enum.md:
`list_windows` and `foreground_info` (the latter feeds the privacy blocklist
check before any screenshot leaves the machine — PROTOCOL §7).

`window` covers list/focus/minimize/maximize/restore/snap. Focus-type ops
touch the foreground, so the action carries `needs_lock=True`.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

try:
    from .actions import (ActionError, opt_enum, reject_extra, req_str,
                          register_action)
except ImportError:  # script mode
    from actions import (ActionError, opt_enum, reject_extra, req_str,
                         register_action)

_OPS = {'list', 'focus', 'minimize', 'maximize', 'restore', 'snap'}
_ZONES = {'left', 'right', 'top', 'bottom', 'max'}
_TARGETED = {'focus', 'minimize', 'maximize', 'restore', 'snap'}
_MAX_WINDOWS = 200


def _validate_window(args: Dict[str, Any]) -> Dict[str, Any]:
    reject_extra(args, {'op', 'hwnd', 'title', 'zone'})
    op = opt_enum(args, 'op', _OPS)
    hwnd_raw = args.get('hwnd')
    title = args.get('title')
    zone = args.get('zone')

    if op == 'list':
        if hwnd_raw is not None or title is not None or zone is not None:
            raise ValueError("op 'list' takes no hwnd/title/zone")
        return {'op': 'list'}

    if zone is not None and op != 'snap':
        raise ValueError("field 'zone' is only valid with op 'snap'")
    if op == 'snap':
        opt_enum(args, 'zone', _ZONES)  # required when op == snap

    if hwnd_raw is None and title is None:
        raise ValueError("op '%s' needs hwnd or title (see list_windows)" % op)
    out: Dict[str, Any] = {'op': op}
    if hwnd_raw is not None:
        if isinstance(hwnd_raw, bool) or not isinstance(hwnd_raw, int) or hwnd_raw <= 0:
            raise ValueError("field 'hwnd' must be a positive integer")
        out['hwnd'] = hwnd_raw
    if title is not None:
        out['title'] = req_str(args, 'title', max_len=200)
    if op == 'snap':
        out['zone'] = zone
    return out


def _entry(w: Dict[str, Any], foreground_hwnd: Optional[int]) -> Dict[str, Any]:
    return {
        'hwnd': w.get('hwnd'),
        'title': w.get('title') or '',
        'process': w.get('process'),
        'pid': w.get('pid'),
        'rect': w.get('rect'),
        'foreground': w.get('hwnd') == foreground_hwnd,
    }


async def _resolve(args: Dict[str, Any], backend) -> Dict[str, Any]:
    windows = await asyncio.to_thread(backend.list_windows)
    fg = await asyncio.to_thread(backend.foreground)
    fg_hwnd = (fg or {}).get('hwnd')
    if 'hwnd' in args:
        matches = [w for w in windows if w.get('hwnd') == args['hwnd']]
    else:
        want = args['title'].lower()
        matches = [w for w in windows
                   if (w.get('title') or '').lower() == want]
        # Prefer the foreground window when several share a title.
        matches.sort(key=lambda w: 0 if w.get('hwnd') == fg_hwnd else 1)
    if not matches:
        raise ActionError('E_INTERNAL',
                          "window not found (%s — call list_windows first)"
                          % ('hwnd' if 'hwnd' in args else 'title'))
    return matches[0]


async def _run_window(args: Dict[str, Any], backend) -> Any:
    op = args['op']
    if op == 'list':
        return await _run_list(backend)
    target = await _resolve(args, backend)
    hwnd = target['hwnd']
    if op == 'focus':
        await asyncio.to_thread(backend.focus_window, hwnd)
        return {'focused': hwnd, 'title': target.get('title') or ''}
    if op == 'snap':
        rect = await asyncio.to_thread(backend.snap_window, hwnd, args['zone'])
        return {'snapped': hwnd, 'zone': args['zone'], 'rect': rect}
    mode = {'minimize': 'minimize', 'maximize': 'maximize',
            'restore': 'restore'}[op]
    await asyncio.to_thread(backend.show_window, hwnd, mode)
    return {'window': hwnd, 'op': op, 'title': target.get('title') or ''}


async def _run_list(backend) -> Dict[str, Any]:
    windows = await asyncio.to_thread(backend.list_windows)
    fg = await asyncio.to_thread(backend.foreground)
    fg_hwnd = (fg or {}).get('hwnd')
    entries = [_entry(w, fg_hwnd) for w in windows[:_MAX_WINDOWS]]
    return {'count': len(windows), 'windows': entries,
            **({'truncated': True} if len(windows) > len(entries) else {})}


async def _run_list_windows(args: Dict[str, Any], backend) -> Dict[str, Any]:
    reject_extra(args, set())
    return await _run_list(backend)


async def _run_foreground_info(args: Dict[str, Any], backend) -> Dict[str, Any]:
    """Foreground window facts — Brain applies privacy.blocklist_apps to
    these (title/process) BEFORE deciding a screenshot may leave the box."""
    reject_extra(args, set())
    fg = await asyncio.to_thread(backend.foreground)
    return {'window': _entry(fg, (fg or {}).get('hwnd')) if fg else None}


def _validate_inspect(args: Dict[str, Any]) -> Dict[str, Any]:
    reject_extra(args, set())
    return {}


register_action('window', _run_window, validate=_validate_window,
                needs_lock=True, confirm=None,
                describe='Manage windows: list/focus/minimize/maximize/'
                         'restore/snap (target by hwnd or exact title).')
register_action('list_windows', _run_list_windows,
                validate=_validate_inspect, needs_lock=False, confirm=None,
                describe='List visible top-level windows with title/process/'
                         'hwnd (needed to target window ops).')
register_action('foreground_info', _run_foreground_info,
                validate=_validate_inspect, needs_lock=False, confirm=None,
                describe='Describe the current foreground window (title/'
                         'process/pid) — used for privacy checks.')

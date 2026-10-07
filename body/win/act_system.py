"""System actions (PROTOCOL §7): clipboard{op}, media{op}, volume{level},
brightness{level}, notify{text}.

Only `media` injects input (synthesized media keystrokes) — it carries
needs_lock=True; volume/brightness go through Core Audio/WMI and clipboard
through the Win32 clipboard, so they need no lock.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict

try:
    from .actions import (opt_enum, reject_extra, register_action, req_int,
                          req_str)
    from .winlayer import MEDIA_KEYS
except ImportError:  # script mode
    from actions import (opt_enum, reject_extra, register_action, req_int,
                         req_str)
    from winlayer import MEDIA_KEYS

_MAX_CLIPBOARD = 100000
_MAX_NOTIFY = 500


# ---------------------------------------------------------------- clipboard
def _validate_clipboard(args: Dict[str, Any]) -> Dict[str, Any]:
    reject_extra(args, {'op', 'text'})
    op = opt_enum(args, 'op', {'read', 'write'})
    if op == 'write':
        text = req_str(args, 'text', max_len=_MAX_CLIPBOARD, min_len=0,
                       allow_empty=True)
        return {'op': op, 'text': text}
    if 'text' in args:
        raise ValueError("op 'read' does not take 'text'")
    return {'op': op}


async def _run_clipboard(args: Dict[str, Any], backend) -> Any:
    if args['op'] == 'read':
        # Legacy result shape: the raw string (e2e_phase3 asserts equality).
        return await asyncio.to_thread(backend.clipboard_get)
    await asyncio.to_thread(backend.clipboard_set, args['text'])
    return {'written': len(args['text'])}


# ------------------------------------------------------------------- media
def _validate_media(args: Dict[str, Any]) -> Dict[str, Any]:
    reject_extra(args, {'op'})
    op = opt_enum(args, 'op', set(MEDIA_KEYS))
    return {'op': op}


async def _run_media(args: Dict[str, Any], backend) -> Dict[str, Any]:
    await asyncio.to_thread(backend.media_key, args['op'])
    return {'sent': args['op']}


# ------------------------------------------------------- volume/brightness
def _validate_level(args: Dict[str, Any]) -> Dict[str, Any]:
    reject_extra(args, {'level'})
    return {'level': req_int(args, 'level', lo=0, hi=100)}


async def _run_volume(args: Dict[str, Any], backend) -> Dict[str, Any]:
    await asyncio.to_thread(backend.set_volume, args['level'])
    return {'level': args['level']}


async def _run_brightness(args: Dict[str, Any], backend) -> Dict[str, Any]:
    await asyncio.to_thread(backend.set_brightness, args['level'])
    return {'level': args['level']}


# ------------------------------------------------------------------ notify
def _validate_notify(args: Dict[str, Any]) -> Dict[str, Any]:
    reject_extra(args, {'text'})
    return {'text': req_str(args, 'text', max_len=_MAX_NOTIFY)}


async def _run_notify(args: Dict[str, Any], backend) -> Dict[str, Any]:
    await asyncio.to_thread(backend.notify, args['text'])
    return {'notified': True}


register_action('clipboard', _run_clipboard, validate=_validate_clipboard,
                needs_lock=False, confirm=None,
                describe='Read or write the Windows clipboard text.')
register_action('media', _run_media, validate=_validate_media,
                needs_lock=True, confirm=None,
                describe='Send a media key: play_pause/stop/next/prev/'
                         'vol_up/vol_down/mute.')
register_action('volume', _run_volume, validate=_validate_level,
                needs_lock=False, confirm=None,
                describe='Set master volume (0-100 percent).')
register_action('brightness', _run_brightness, validate=_validate_level,
                needs_lock=False, confirm=None,
                describe='Set display brightness (0-100 percent).')
register_action('notify', _run_notify, validate=_validate_notify,
                needs_lock=False, confirm=None,
                describe='Show a Windows toast notification with the text.')

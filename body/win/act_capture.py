"""Screenshot action (PROTOCOL §7): screenshot{max_px, quality}.

Privacy gates (blocklist, redaction, cloud-vs-local decision) live Brain-side
(PROTOCOL §7 note, computer-use lane); the Body only captures, downscales and
returns bytes. `debug_capture` stays false: nothing is written to disk here.
"""
from __future__ import annotations

import asyncio
import base64
from typing import Any, Dict

try:
    from .actions import offload, opt_int, reject_extra, register_action
except ImportError:  # script mode
    from actions import offload, opt_int, reject_extra, register_action


def _validate_screenshot(args: Dict[str, Any]) -> Dict[str, Any]:
    reject_extra(args, {'max_px', 'quality'})
    return {
        'max_px': opt_int(args, 'max_px', lo=64, hi=4096, default=1280),
        'quality': opt_int(args, 'quality', lo=10, hi=95, default=70),
    }


async def _run_screenshot(args: Dict[str, Any], backend) -> Dict[str, Any]:
    shot = await offload(backend.capture, args['max_px'],
                                   args['quality'])
    # Legacy result shape (e2e_phase3 / tests/e2e_wave2.py expect b64+bytes).
    return {'b64': base64.b64encode(shot).decode('ascii'),
            'bytes': len(shot)}


register_action('screenshot', _run_screenshot, validate=_validate_screenshot,
                needs_lock=False, confirm=None,
                describe='Capture the screen downscaled to max_px JPEG.')

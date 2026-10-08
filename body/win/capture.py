"""Screen capture utilities for the Windows Body.

- capture_screenshot(max_px=1280, quality=70) -> bytes
  Captures the primary monitor, resizes so the longer side <= max_px,
  encodes as JPEG with the given quality, and returns raw bytes.

Dependencies: mss, Pillow — from the PRE-INSTALLED hash-pinned environment
only (body/win/requirements.txt); a missing dep fails loud at import (SEC-9,
no runtime pip).
"""
import io
import pathlib
import sys

try:
    from . import depfail
except ImportError:          # script mode (body/win on sys.path)
    import depfail

depfail.require('mss')
depfail.require('Pillow', 'PIL')

import mss
from PIL import Image

def capture_screenshot(max_px: int = 1280, quality: int = 70) -> bytes:
    """Capture the primary monitor, downscale, and return JPEG bytes.

    Args:
        max_px: Maximum dimension (width or height) after downscaling.
        quality: JPEG quality (1‑95).
    Returns:
        JPEG image as bytes.
    """
    with mss.MSS() as sct:
        monitor = sct.monitors[1]  # primary monitor
        raw = sct.grab(monitor)
        img = Image.frombytes('RGB', (raw.width, raw.height), raw.rgb)
        # Downscale preserving aspect ratio.
        ratio = min(max_px / img.width, max_px / img.height, 1)
        if ratio < 1:
            new_size = (int(img.width * ratio), int(img.height * ratio))
            img = img.resize(new_size, Image.LANCZOS)
        out = io.BytesIO()
        img.save(out, format='JPEG', quality=quality)
        return out.getvalue()

# Simple CLI test when executed directly.
if __name__ == '__main__':
    data = capture_screenshot()
    pathlib.Path('screenshot_test.jpg').write_bytes(data)
    print('Wrote screenshot_test.jpg', len(data), 'bytes')

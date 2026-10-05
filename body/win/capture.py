"""Screen capture utilities for the Windows Body.

- capture_screenshot(max_px=1280, quality=70) -> bytes
  Captures the primary monitor, resizes so the longer side <= max_px,
  encodes as JPEG with the given quality, and returns raw bytes.

Dependencies: mss, Pillow. The function will attempt to import them and install
if missing.
"""
import io
import pathlib
import sys

def _ensure_pkg(pkg: str, import_name: str = None, pin: str = ''):
    """Import-or-install, PINNED (security: unpinned runtime pip = supply chain)."""
    try:
        __import__(import_name or pkg)
    except ImportError:
        import subprocess, sys
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--quiet',
                               ('%s==%s' % (pkg, pin)) if pin else pkg])
        __import__(import_name or pkg)

# Ensure required third‑party packages.
_ensure_pkg('mss', pin='10.2.0')
_ensure_pkg('Pillow', 'PIL', '12.3.0')

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

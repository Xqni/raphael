"""JPEG dimension probing for the PROTOCOL §7 downscale gate.

The Body captures with `screenshot{max_px, quality}` (its capture.py resizes),
but the gate must VERIFY what actually arrives before any cloud send — a
misbehaving or hostile Body must not be able to hand us a full-resolution
frame. Pure-Python SOF-marker parse (no PIL in the brain venv):

- unparseable / non-JPEG input  -> None  (gate FAILS CLOSED)
- dimensions must be <= config vision.max_px on the longer side
"""
from __future__ import annotations

from typing import Optional, Tuple

_SOF_MARKERS = frozenset(
    m for m in range(0xC0, 0xD0) if m not in (0xC4, 0xC8, 0xCC)  # DHT/JPG/DAC are not SOF
)
_STANDALONE = frozenset({0xD8, 0xD9}) | frozenset(range(0xD0, 0xD8))  # SOI/EOI/RSTn


def jpeg_dimensions(data: bytes) -> Optional[Tuple[int, int]]:
    """(width, height) of the primary frame, or None if not a parseable JPEG."""
    if not isinstance(data, (bytes, bytearray)) or len(data) < 4:
        return None
    data = bytes(data)
    if data[:2] != b"\xff\xd8":
        return None
    i = 2
    n = len(data)
    while i + 3 < n:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker == 0xFF:            # fill byte
            i += 1
            continue
        if marker in _STANDALONE:     # no length field
            i += 2
            continue
        seg_len = int.from_bytes(data[i + 2:i + 4], "big")
        if seg_len < 2:
            return None
        if marker in _SOF_MARKERS:
            if i + 9 > n:
                return None
            height = int.from_bytes(data[i + 5:i + 7], "big")
            width = int.from_bytes(data[i + 7:i + 9], "big")
            if width <= 0 or height <= 0:
                return None
            return width, height
        i += 2 + seg_len
    return None


def within_max_px(data: bytes, max_px: int) -> bool:
    """True only for a parseable JPEG whose longer side <= max_px (fail closed)."""
    dims = jpeg_dimensions(data)
    if dims is None:
        return False
    return max(dims) <= int(max_px)


def make_jpeg(width: int, height: int) -> bytes:
    """Minimal structurally-valid JPEG (SOI/APP0/SOF0/EOI) for tests/fixtures.
    Not decodable as a picture — dimension probing only."""
    out = bytearray(b"\xff\xd8")                                   # SOI
    out += b"\xff\xe0" + (16).to_bytes(2, "big") + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    out += b"\xff\xc0" + (17).to_bytes(2, "big")                   # SOF0, len 17
    out += b"\x08" + height.to_bytes(2, "big") + width.to_bytes(2, "big") + b"\x01"
    out += b"\x01\x11\x00" + b"\x02\x11\x01" + b"\x03\x11\x01"
    out += b"\xff\xd9"                                             # EOI
    return bytes(out)

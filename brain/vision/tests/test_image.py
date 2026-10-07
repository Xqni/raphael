"""Downscale verification helpers (PROTOCOL §7: caller verifies <= max_px)."""
from brain.vision.image import jpeg_dimensions, make_jpeg, within_max_px


def test_make_jpeg_dimensions_parse():
    data = make_jpeg(1280, 720)
    assert jpeg_dimensions(data) == (1280, 720)
    assert within_max_px(data, 1280) is True


def test_sof_before_app_segment_with_exif_like_header():
    # SOI + APP1(EXIF) + SOF2 (progressive) — parser must skip APP1 and read SOF2
    app1_body = b"Exif\x00\x00" + b"\x00" * 32
    app1 = b"\xff\xe1" + (len(app1_body) + 2).to_bytes(2, "big") + app1_body
    sof = (b"\xff\xc2" + (17).to_bytes(2, "big") + b"\x08"
           + (1000).to_bytes(2, "big") + (2000).to_bytes(2, "big") + b"\x01"
           + b"\x01\x11\x00" + b"\x02\x11\x01" + b"\x03\x11\x01")
    data = b"\xff\xd8" + app1 + sof + b"\xff\xd9"
    assert jpeg_dimensions(data) == (2000, 1000)


def test_non_jpeg_and_truncated_fail_closed():
    assert jpeg_dimensions(b"\x89PNG\r\n\x1a\n") is None
    assert jpeg_dimensions(b"") is None
    assert jpeg_dimensions(b"\xff\xd8\xff\xe0") is None      # header only
    assert within_max_px(b"not a jpeg", 1280) is False
    assert within_max_px(None, 1280) is False


def test_boundary_is_inclusive():
    assert within_max_px(make_jpeg(1280, 1280), 1280) is True
    assert within_max_px(make_jpeg(1281, 700), 1280) is False
    assert within_max_px(make_jpeg(700, 1281), 1280) is False

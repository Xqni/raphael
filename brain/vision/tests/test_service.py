"""see_screen service — the PROTOCOL §7 pipeline end-to-end (mocked seams).

Covers the lane's privacy asserts too: no image bytes logged/persisted,
Private Mode short-circuits before any capture or model call.
"""
import asyncio
from contextlib import contextmanager

import pytest

from brain.vision.config import VisionConfig
from brain.vision.gate import CloudVisionGate
from brain.vision.image import make_jpeg
from brain.vision.service import GateRefused, capture_screen, see_screen

IMG = make_jpeg(1280, 720)
BIG = make_jpeg(2000, 1500)


def cfg(**kw):
    base = dict(profile="cloud_temp", provider="cloud", max_px=1280, quality=70,
                blocklist_apps=("1Password", "KeePass", "Bitwarden", "Banking"),
                redact=("api_key", "token", "password", "card", "email", "phone"))
    base.update(kw)
    return VisionConfig(**base)


class FakeGateway:
    def __init__(self, title="Notepad - untitled", image=IMG, raise_on=None):
        self.title = title
        self.image = image
        self.raise_on = raise_on
        self.screenshot_calls = 0
        self.foreground_calls = 0

    async def foreground_window(self):
        self.foreground_calls += 1
        if self.raise_on == "foreground":
            raise RuntimeError("window op unsupported")
        return self.title

    async def screenshot(self, max_px, quality):
        self.screenshot_calls += 1
        if self.raise_on == "screenshot":
            raise RuntimeError("capture failed")
        assert (max_px, quality) == (1280, 70)
        return self.image


def vision_ok(text):
    def _v(image, question, purpose="vision"):
        assert image is IMG or isinstance(image, (bytes, bytearray))
        assert "briefly" in question or "one or two" in question
        return {"text": text, "provider": "mock", "model": "m"}
    return _v


def run(coro):
    return asyncio.run(coro)


@contextmanager
def deny_file_writes():
    """Privacy assert: the pipeline must never open files for writing."""
    import builtins
    import io as _io
    real_open, real_io_open = builtins.open, _io.open

    def guard(file, mode="r", *a, **k):
        if any(c in mode for c in "wxa+"):
            raise AssertionError(f"file WRITE attempted: {file!r}")
        return real_open(file, mode, *a, **k)

    builtins.open = guard
    _io.open = guard
    try:
        yield
    finally:
        builtins.open = real_open
        _io.open = real_io_open


def test_happy_path_returns_vision_answer_without_touching_disk():
    gw = FakeGateway()
    with deny_file_writes():
        out = run(see_screen("what app is this?", gateway=gw,
                             config=cfg(), gate=CloudVisionGate(cfg()),
                             vision_fn=vision_ok("You are in Notepad."),
                             is_private=lambda: False))
    assert out == "You are in Notepad."
    assert gw.screenshot_calls == 1


def test_answer_is_redacted_before_return():
    out = run(see_screen("any accounts?", gateway=FakeGateway(),
                         config=cfg(), gate=CloudVisionGate(cfg()),
                         vision_fn=vision_ok("user mail me@example.com card 4111 1111 1111 1111"),
                         is_private=lambda: False))
    assert "me@example.com" not in out
    assert "4111" not in out
    assert "[REDACTED:email]" in out


def test_private_mode_short_circuits_before_anything():
    class ExplodingGateway:
        async def foreground_window(self):
            raise AssertionError("must not capture/inspect in private mode")

        async def screenshot(self, *a, **k):
            raise AssertionError("must not capture in private mode")

    def exploding_vision(*a, **k):
        raise AssertionError("must not call the model in private mode")

    out = run(see_screen("what is this?", gateway=ExplodingGateway(),
                         config=cfg(), gate=CloudVisionGate(cfg()),
                         vision_fn=exploding_vision, is_private=lambda: True))
    assert "Private mode" in out


def test_blocklist_refusal_never_captures():
    gw = FakeGateway(title="1Password - Browser")

    def no_vision(*a, **k):
        raise AssertionError("vision must not run for a blocked window")

    out = run(see_screen("what is this?", gateway=gw, config=cfg(),
                         gate=CloudVisionGate(cfg()), vision_fn=no_vision,
                         is_private=lambda: False))
    assert "1Password" in out
    assert gw.screenshot_calls == 0        # refused BEFORE capture
    assert gw.foreground_calls == 1


def test_unverifiable_foreground_fails_closed():
    gw = FakeGateway(raise_on="foreground")

    def no_vision(*a, **k):
        raise AssertionError("vision must not run without a verified foreground")

    out = run(see_screen("what is this?", gateway=gw, config=cfg(),
                         gate=CloudVisionGate(cfg()), vision_fn=no_vision,
                         is_private=lambda: False))
    assert "won't send" in out
    assert gw.screenshot_calls == 0


def test_profile_local_blocks_cloud_send():
    c = cfg(profile="local")

    def no_vision(*a, **k):
        raise AssertionError("cloud vision forbidden under profile local")
    out = run(see_screen("what is this?", gateway=FakeGateway(), config=c,
                         gate=CloudVisionGate(c), vision_fn=no_vision,
                         is_private=lambda: False))
    assert "stay on this machine" in out


def test_oversized_capture_refused():
    gw = FakeGateway(image=BIG)

    def no_vision(*a, **k):
        raise AssertionError("oversized image must never reach vision")

    out = run(see_screen("what is this?", gateway=gw, config=cfg(),
                         gate=CloudVisionGate(cfg()), vision_fn=no_vision,
                         is_private=lambda: False))
    assert "larger than the size limit" in out


def test_capture_failure_is_speakable():
    gw = FakeGateway(raise_on="screenshot")
    out = run(see_screen("what is this?", gateway=gw, config=cfg(),
                         gate=CloudVisionGate(cfg()),
                         vision_fn=vision_ok("x"), is_private=lambda: False))
    assert "capture" in out.lower()


def test_vision_error_maps_to_code():
    class Err(Exception):
        code = "E_PROVIDER_429"

    def boom(*a, **k):
        raise Err("rate limited")

    out = run(see_screen("q", gateway=FakeGateway(), config=cfg(),
                         gate=CloudVisionGate(cfg()), vision_fn=boom,
                         is_private=lambda: False))
    assert out == "Vision is unavailable right now (E_PROVIDER_429)."


def test_missing_router_seam_degrades():
    out = run(see_screen("q", gateway=FakeGateway(), config=cfg(),
                         gate=CloudVisionGate(cfg()), vision_fn=None,
                         is_private=lambda: False))
    assert "E_OFFLINE" in out


def test_empty_answer_and_long_answer():
    out = run(see_screen("q", gateway=FakeGateway(), config=cfg(),
                         gate=CloudVisionGate(cfg()),
                         vision_fn=vision_ok("   "), is_private=lambda: False))
    assert "couldn't make out" in out

    long_text = "word " * 400
    out = run(see_screen("q", gateway=FakeGateway(), config=cfg(),
                         gate=CloudVisionGate(cfg()),
                         vision_fn=vision_ok(long_text), is_private=lambda: False))
    assert len(out) <= 701 and out.endswith("…")


def test_empty_question_is_answered_without_seeing():
    gw = FakeGateway()

    def no_vision(*a, **k):
        raise AssertionError("no question, no model call")
    out = run(see_screen("   ", gateway=gw, config=cfg(),
                         gate=CloudVisionGate(cfg()), vision_fn=no_vision,
                         is_private=lambda: False))
    assert "Ask me" in out
    assert gw.screenshot_calls == 0


def test_capture_screen_raises_gate_refused():
    gw = FakeGateway(title="KeePass - vault")
    with pytest.raises(GateRefused) as ei:
        run(capture_screen(gw, CloudVisionGate(cfg()), cfg()))
    assert ei.value.code == "E_BLOCKED"


def test_sync_vision_fn_supported():
    out = run(see_screen("q", gateway=FakeGateway(), config=cfg(),
                         gate=CloudVisionGate(cfg()),
                         vision_fn=lambda image, question, purpose="vision":
                             {"text": "sync seam works"},
                         is_private=lambda: False))
    assert out == "sync seam works"

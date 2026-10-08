"""Wave 5H audit item 1 — SCREENSHOT EGRESS TRIPWIRE.

One test per forbidden condition; every test watches ALL THREE sinks and
fails if a single image byte escapes:
  DISK  — builtins.open/io.open (write modes), os.open (write flags),
          Path.write_bytes/write_text patched DURING the call;
  LOG   — capsys stdout/stderr checked for the marker AND its base64 form
          (brain/vision uses no logging module — print is the only console
          surface);
  SEND  — the vision seam spy must stay untouched in denied scenarios.

The fake capture embeds a marker byte-string (after EOI, so dimensions still
parse) so escapes are detectable even if a sink formats/encodes them.
Composite 'title | process' identity (Wave-4 bypass fix) is used for the
blocklist scenario.
"""
import asyncio
import base64
import io
import os
import pathlib
from contextlib import contextmanager

from brain.vision.config import VisionConfig
from brain.vision.gate import CloudVisionGate
from brain.vision.image import make_jpeg
from brain.vision.service import see_screen

MARKER = b"TRIPWIRE_IMG_MARKER_7f3e9a"
FAKE_IMAGE = make_jpeg(1280, 720) + MARKER      # dims parse; bytes unique
B64_MARKER = base64.b64encode(MARKER)
WRITE_MASK = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC


def cfg(**kw):
    base = dict(profile="cloud_temp", provider="cloud", max_px=1280, quality=70,
                blocklist_apps=("1Password", "KeePass", "Bitwarden", "Banking"),
                redact=("api_key", "token", "password", "card", "email", "phone"))
    base.update(kw)
    return VisionConfig(**base)


@contextmanager
def disk_guard():
    """DISK sink: any write-mode open during the block raises."""
    import builtins
    real_open, real_os_open = builtins.open, os.open
    real_wb, real_wt = pathlib.Path.write_bytes, pathlib.Path.write_text

    def guard_open(file, mode="r", *a, **k):
        if any(c in mode for c in "wxa+"):
            raise AssertionError(f"DISK SINK: write attempted to {file!r}")
        return real_open(file, mode, *a, **k)

    def guard_os_open(path, flags, *a, **k):
        if flags & WRITE_MASK:
            raise AssertionError(f"DISK SINK: os.open write to {path!r}")
        return real_os_open(path, flags, *a, **k)

    def guard_wb(self, data):
        raise AssertionError("DISK SINK: Path.write_bytes")

    def guard_wt(self, *a, **k):
        raise AssertionError("DISK SINK: Path.write_text")

    builtins.open = guard_open
    os.open = guard_os_open
    pathlib.Path.write_bytes = guard_wb
    pathlib.Path.write_text = guard_wt
    try:
        yield
    finally:
        builtins.open = real_open
        os.open = real_os_open
        pathlib.Path.write_bytes = real_wb
        pathlib.Path.write_text = real_wt


class VisionSpy:
    def __init__(self):
        self.calls = []

    def __call__(self, image, question, purpose="vision"):
        self.calls.append((image, question))
        return {"text": "would-be answer", "provider": "mock"}


def assert_no_escape(out: str, spy: VisionSpy, capsys, *, expect_no_send: bool):
    console = capsys.readouterr()
    payload = console.out + console.err
    assert MARKER.decode() not in payload, "LOG SINK: raw marker in console"
    assert B64_MARKER.decode() not in payload, "LOG SINK: b64 marker in console"
    assert MARKER.decode() not in out, "SPOKEN SINK: marker in the answer"
    if expect_no_send:
        assert spy.calls == [], "SEND SINK: vision called in a denied scenario"


class GW:
    def __init__(self, fg):
        self.fg = fg
        self.screenshot_calls = 0

    async def foreground_window(self):
        return self.fg

    async def screenshot(self, max_px, quality):
        self.screenshot_calls += 1
        return FAKE_IMAGE


def see(gw, c, spy, private=False):
    return asyncio.run(see_screen("what is this?", gateway=gw, config=c,
                                  gate=CloudVisionGate(c), vision_fn=spy,
                                  is_private=lambda: private))


def test_tripwire_blocklist_composite_identity(capsys):
    """Composite 'title | process' on the blocklist: no capture, no send, no
    disk, no log — the refusal names the app (local speech), never bytes."""
    spy, gw = VisionSpy(), GW("Enter Master Key | KeePass.exe")
    with disk_guard():
        out = see(gw, cfg(), spy)
    assert "KeePass" in out
    assert gw.screenshot_calls == 0             # never even captured
    assert_no_escape(out, spy, capsys, expect_no_send=True)


def test_tripwire_private_mode(capsys):
    class NoProbe(GW):
        async def foreground_window(self):
            raise AssertionError("PROBE SINK: private mode must not probe")

    spy, gw = VisionSpy(), NoProbe("Notepad")
    with disk_guard():
        out = see(gw, cfg(), spy, private=True)
    assert "Private mode" in out
    assert_no_escape(out, spy, capsys, expect_no_send=True)


def test_tripwire_no_cloud_vision_policy(capsys):
    """provider neither 'cloud' nor 'local' = NO policy -> refuse (Wave 5H
    hardening: unknown providers used to slip through check_profile)."""
    for provider in ("none", "", "mistral", None):
        spy, gw = VisionSpy(), GW("Notepad - untitled")
        with disk_guard():
            out = see(gw, cfg(provider=provider), spy)
        assert "policy" in out, (provider, out)
        assert gw.screenshot_calls == 0
        capsys.readouterr()                     # drain per iteration
        assert_no_escape(out, spy, capsys, expect_no_send=True)


def test_tripwire_profile_local_denies_cloud(capsys):
    spy, gw = VisionSpy(), GW("Notepad - untitled")
    with disk_guard():
        out = see(gw, cfg(profile="local"), spy)
    assert "stay on this machine" in out
    assert gw.screenshot_calls == 0
    assert_no_escape(out, spy, capsys, expect_no_send=True)


def test_tripwire_control_happy_path_still_sends(capsys):
    """Control: the happy path DOES deliver (otherwise the tripwire proves
    nothing) — and even then, disk/log sinks stay silent."""
    spy, gw = VisionSpy(), GW("Notepad - untitled")
    with disk_guard():
        out = see(gw, cfg(), spy)
    assert out == "would-be answer"
    assert len(spy.calls) == 1 and spy.calls[0][0] is FAKE_IMAGE
    console = capsys.readouterr()
    assert MARKER.decode() not in console.out + console.err

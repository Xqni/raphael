"""Wave 4 observation hardening — vision-side: debug_capture gate (§7(4) /
qa-security vision-gate item 4), blocklist composite matching (process-field
bypass), foreground-probe failure matrix, redaction re-verify.

All mock seams; live stack untouched (RULE: no servers spawned)."""
import asyncio

import pytest

from brain.vision.config import VisionConfig
from brain.vision.gate import (E_BLOCKED, E_DEBUG_CAPTURE, E_NO_FOREGROUND,
                               CloudVisionGate)
from brain.vision.image import make_jpeg
from brain.vision.service import GateRefused, capture_screen, see_screen

IMG = make_jpeg(1280, 720)


def cfg(**kw):
    base = dict(profile="cloud_temp", provider="cloud", max_px=1280, quality=70,
                blocklist_apps=("1Password", "KeePass", "Bitwarden", "Banking"),
                redact=("api_key", "token", "password", "card", "email", "phone"))
    base.update(kw)
    return VisionConfig(**base)


class FgGateway:
    """fg probe controlled per test: value, exception, or None."""

    def __init__(self, fg="Notepad - untitled", fg_exc=None, image=IMG):
        self.fg, self.fg_exc, self.image = fg, fg_exc, image
        self.screenshot_calls = 0
        self.foreground_calls = 0

    async def foreground_window(self):
        self.foreground_calls += 1
        if self.fg_exc is not None:
            raise self.fg_exc
        return self.fg

    async def screenshot(self, max_px, quality):
        self.screenshot_calls += 1
        return self.image


def vision_ok(text):
    def _v(image, question, purpose="vision"):
        return {"text": text, "provider": "mock"}
    return _v


def run(coro):
    return asyncio.run(coro)


# ---- qa-security vision-gate item 4: debug_capture checked in code ---------
def test_debug_capture_blocks_cloud_send_before_capture():
    c = cfg(debug_capture=True)
    gw = FgGateway()

    def no_vision(*a, **k):
        raise AssertionError("no vision call while debug_capture is on")

    out = run(see_screen("what is this?", gateway=gw, config=c,
                         gate=CloudVisionGate(c), vision_fn=no_vision,
                         is_private=lambda: False))
    assert "stay on this machine" in out
    assert gw.screenshot_calls == 0 and gw.foreground_calls == 0  # refused early


def test_debug_capture_checked_at_the_egress_point_too():
    c = cfg(debug_capture=True)
    gw = FgGateway()
    with pytest.raises(GateRefused) as ei:
        run(capture_screen(gw, CloudVisionGate(c), c))
    assert ei.value.code == E_DEBUG_CAPTURE


def test_debug_capture_local_provider_unaffected():
    c = cfg(debug_capture=True, provider="local")
    gw = FgGateway()
    out = run(see_screen("what is this?", gateway=gw, config=c,
                         gate=CloudVisionGate(c),
                         vision_fn=vision_ok("local vision answer"),
                         is_private=lambda: False))
    assert out == "local vision answer"


def test_debug_capture_false_still_allows_cloud():
    c = cfg(debug_capture=False)
    assert CloudVisionGate(c).check_debug_capture().ok


# ---- blocklist bypass audit: process field --------------------------------
def test_process_field_bypass_closed():
    """An untitled KeePass dialog titled 'Enter Master Key' must NOT slip
    through on title alone — matching covers title AND process."""
    g = CloudVisionGate(cfg())
    d = g.check_foreground("Enter Master Key | KeePass.exe")
    assert not d.ok and d.code == E_BLOCKED
    assert g.check_foreground("KeePass.exe").code == E_BLOCKED
    # normal terminal composite passes
    assert g.check_foreground("Ubuntu-26.04 | WindowsTerminal.exe").ok
    # both-empty identity arrives as None (gateway) -> fail closed
    assert g.check_foreground(None).code == E_NO_FOREGROUND


def test_blocklist_entries_are_literal_not_regex():
    g = CloudVisionGate(cfg(blocklist_apps=("Bank*ing",)))
    assert g.check_foreground("My BankXing App").ok        # '*' is literal
    assert g.check_foreground("Bank*ing").code == E_BLOCKED


def test_empty_blocklist_entry_cannot_match_everything():
    g = CloudVisionGate(cfg(blocklist_apps=("", "KeePass")))
    assert g.check_foreground("Anything at all").ok        # '' never matches
    assert g.check_foreground("x KeepPass x").ok           # substring precise
    assert g.check_foreground("keepass").code == E_BLOCKED  # casefold


# ---- foreground-probe failure matrix --------------------------------------
class ProbeError(Exception):
    """ActError-shaped (duck-typed .code/.detail) — no cross-package import."""

    def __init__(self, code, detail):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def test_probe_failure_matrix():
    cases = [
        (ProbeError("E_ACT_TIMEOUT", "E_ACT_TIMEOUT"), "E_ACT_TIMEOUT"),
        (ProbeError("E_INTERNAL", "no body session connected"),
         "no body session connected"),
        (RuntimeError("window op unsupported"), "RuntimeError"),
    ]
    for exc, hint in cases:
        gw = FgGateway(fg_exc=exc)

        def no_vision(*a, **k):
            raise AssertionError("vision must not run on probe failure")

        out = run(see_screen("q", gateway=gw, config=cfg(),
                             gate=CloudVisionGate(cfg()), vision_fn=no_vision,
                             is_private=lambda: False))
        assert "can't reach the Body" in out, exc
        assert hint in out, (hint, out)
        assert "can't verify" not in out        # never the privacy verdict
        assert gw.screenshot_calls == 0


def test_vanished_window_matrix():
    gw = FgGateway(fg=None)                     # {'window': None} at the seam

    def no_vision(*a, **k):
        raise AssertionError("vision must not run without identity")

    out = run(see_screen("q", gateway=gw, config=cfg(),
                         gate=CloudVisionGate(cfg()), vision_fn=no_vision,
                         is_private=lambda: False))
    assert "can't verify which window" in out
    assert gw.screenshot_calls == 0


# ---- redaction re-verify (every secret shape, vision answer) --------------
def test_redaction_covers_all_configured_kinds_in_answers():
    answer = ("login api_key=sk-abcdef123456 token: "
              "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abcdefgh12345678 "
              "password=hunter2 card 4111 1111 1111 1111 "
              "mail me@example.com call +1 416 555 0123")
    out = run(see_screen("q", gateway=FgGateway(), config=cfg(),
                         gate=CloudVisionGate(cfg()),
                         vision_fn=vision_ok(answer),
                         is_private=lambda: False))
    for leak in ("sk-abcdef123456", "eyJhbGci", "hunter2", "4111",
                 "me@example.com", "416 555"):
        assert leak not in out, leak
    assert out.count("[REDACTED:") >= 6

"""Wave 5H audit item 2 — sensitive contexts BEYOND the static blocklist:
focused password fields (UIA IsPassword, forward-compat flags), UAC/secure-
desktop prompts, and configurable browser patterns (bank/wallet/2FA).
Every case: REFUSE capture with a short spoken reason, before any pixels."""
import asyncio

import pytest

from brain.vision.config import VisionConfig, load_config
from brain.vision.gate import (E_BLOCKED, E_SENSITIVE, PASSWORD_FOCUS_REASON,
                               CloudVisionGate)
from brain.vision.image import make_jpeg
from brain.vision.service import see_screen

IMG = make_jpeg(1280, 720)


def cfg(**kw):
    base = dict(profile="cloud_temp", provider="cloud", max_px=1280, quality=70,
                blocklist_apps=("1Password", "KeePass", "Bitwarden", "Banking"),
                redact=("email",))
    base.update(kw)
    return VisionConfig(**base)


class GW:
    def __init__(self, fg, password_focus=False, image=IMG):
        self.fg = fg
        self.password_focus = password_focus
        self.image = image
        self.screenshot_calls = 0

    async def foreground_window(self):
        return self.fg

    async def screenshot(self, max_px, quality):
        self.screenshot_calls += 1
        return self.image


def see(gw, c, private=False, vision=None):
    def default_vision(*a, **k):
        raise AssertionError("vision must not run on a refused capture")
    return asyncio.run(see_screen("what is this?", gateway=gw, config=c,
                                  gate=CloudVisionGate(c),
                                  vision_fn=vision or default_vision,
                                  is_private=lambda: private))


# ---- gate-level: patterns beyond the static blocklist ----------------------
def test_uac_and_credential_prompts_denied():
    g = CloudVisionGate(cfg())
    for ident in ("User Account Control", "consent.exe",
                  "CredentialUI balloon | consent.exe",
                  "Windows Security | SecurityHealthSystray.exe",
                  "Insert SmartCard"):
        d = g.check_foreground(ident)
        assert not d.ok and d.code == E_SENSITIVE, ident
        assert "sensitive context" in d.reason and len(d.reason) < 140, ident


def test_browser_financial_and_2fa_patterns_denied():
    g = CloudVisionGate(cfg())
    for ident in ("My Bank — Chase | chrome.exe",
                  "MetaMask — Wallet | chrome.exe",
                  "Enter 2FA code | firefox.exe",
                  "Google Authenticator | chrome.exe"):
        d = g.check_foreground(ident)
        assert not d.ok and d.code == E_SENSITIVE, ident
    # redundant coverage: bitwarden titles are already STATIC-blocklisted
    d = g.check_foreground("Login | OTP code entry | bitwarden.exe")
    assert not d.ok and d.code in (E_SENSITIVE, E_BLOCKED)


def test_normal_browser_window_still_allowed():
    g = CloudVisionGate(cfg())
    assert g.check_foreground("Docs — Weekly report | chrome.exe").ok
    assert g.check_foreground("Ubuntu-26.04 | WindowsTerminal.exe").ok


def test_configurable_patterns_and_invalid_regex_never_crash():
    c = cfg(sensitive_patterns=("mysecretbroker", "(bad[regex"))
    g = CloudVisionGate(c)
    assert g.check_foreground("mySecretBroker Terminal").code == E_SENSITIVE
    # invalid regex falls back to literal substring — no crash
    assert g.check_foreground("x (bad[regex y").code == E_SENSITIVE
    assert g.check_foreground("harmless window").ok
    # defaults stay UNIONed with config (never removable)
    assert g.check_foreground("User Account Control").code == E_SENSITIVE


def test_real_lane_config_ships_patterns():
    loaded = load_config()
    assert "2fa" in loaded.sensitive_patterns
    assert "wallet" in loaded.sensitive_patterns


# ---- service level: refused BEFORE capture --------------------------------
@pytest.mark.parametrize("ident", [
    "Internet bank — Accounts | chrome.exe",     # 'bank' pattern (NOT blocklist)
    "two-factor setup | chrome.exe",
    "consent.exe | User Account Control",
])
def test_sensitive_context_refuses_before_capture(ident):
    gw = GW(ident)
    out = see(gw, cfg())
    assert "sensitive context" in out
    assert gw.screenshot_calls == 0


def test_sensitive_reason_is_short_and_spoken():
    out = see(GW("wallet — MetaMask | chrome.exe"), cfg())
    assert 0 < len(out) < 140
    assert "won't send" in out


# ---- focused password field (UIA IsPassword forward-compat) ---------------
def test_password_focus_refuses_see_screen():
    gw = GW("Notepad - Login", password_focus=True)
    out = see(gw, cfg())
    assert out == PASSWORD_FOCUS_REASON
    assert gw.screenshot_calls == 0


def test_password_focus_flag_from_foreground_info_result():
    """gateway parses additive `focused_is_password` from the act result."""
    import asyncio as aio

    from brain.tools.computer_use.gateway import BodyGateway

    class Hub:
        def get_body_session(self):
            return object()

        def broadcast(self, frame, roles=None, exclude_sid=None):
            pass

    class Eng:
        def __init__(self, result):
            self.result = {"ok": True, "result": result}

        def expect_act(self, ref):
            return object()

        async def await_act_res(self, fut, ref, timeout=None):
            return self.result

    # flag present on the result root
    gw = BodyGateway(hub=Hub(), engine=Eng(
        {"window": {"title": "Login", "process": "chrome.exe"},
         "focused_is_password": True}))
    aio.run(gw.foreground_window())
    assert gw.password_focus is True
    # flag absent (today's body) -> clean
    gw2 = BodyGateway(hub=Hub(), engine=Eng(
        {"window": {"title": "Login", "process": "chrome.exe"}}))
    aio.run(gw2.foreground_window())
    assert gw2.password_focus is False
    # next probe recomputes: flag source removed -> stale True clears
    gw._engine.result = {"ok": True, "result": {
        "window": {"title": "Login", "process": "chrome.exe"}}}
    aio.run(gw.foreground_window())
    assert gw.password_focus is False


def test_password_focus_flag_from_tree_nodes():
    from brain.tools.computer_use.gateway import (_tree_has_focused_password,
                                                  render_tree)

    tree = {"name": "Login", "control_type": "Window", "children": [
        {"name": "Password", "control_type": "Edit",
         "is_password": True, "focused": True, "children": []},
    ]}
    assert _tree_has_focused_password(tree) is True
    # password but NOT focused -> not the refusal trigger
    tree2 = {"name": "L", "control_type": "W", "children": [
        {"name": "P", "control_type": "Edit", "is_password": True,
         "focused": False, "children": []}]}
    assert _tree_has_focused_password(tree2) is False
    # rendering MARKS password fields (values never appear in trees)
    out = render_tree(tree)
    assert "[password]" in out

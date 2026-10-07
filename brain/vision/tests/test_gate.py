"""CloudVisionGate — PROTOCOL §7 pre-send checklist."""
from brain.vision.config import VisionConfig
from brain.vision.gate import (E_BLOCKED, E_EMPTY_IMAGE, E_NO_FOREGROUND,
                               E_PRIVATE, E_PROFILE, E_TOO_LARGE,
                               CloudVisionGate)
from brain.vision.image import make_jpeg


def cfg(**kw):
    base = dict(profile="cloud_temp", provider="cloud", max_px=1280, quality=70,
                blocklist_apps=("1Password", "KeePass", "Bitwarden", "Banking"),
                redact=("email", "card"))
    base.update(kw)
    return VisionConfig(**base)


def test_private_mode_denies_with_speakable_reason():
    g = CloudVisionGate(cfg())
    d = g.check_private(True)
    assert not d.ok and d.code == E_PRIVATE
    assert "Private mode" in d.reason
    assert g.check_private(False).ok


def test_cloud_allowed_only_under_cloud_temp():
    g = CloudVisionGate(cfg())
    assert g.check_profile().ok
    g_local = CloudVisionGate(cfg(profile="local"))
    d = g_local.check_profile()
    assert not d.ok and d.code == E_PROFILE
    assert "stay on this machine" in d.reason
    # local vision provider never egresses -> allowed in any profile
    assert CloudVisionGate(cfg(profile="local", provider="local")).check_profile().ok


def test_blocklist_match_case_insensitive():
    g = CloudVisionGate(cfg())
    d = g.check_foreground("1Password - Browser")
    assert not d.ok and d.code == E_BLOCKED
    assert "1Password" in d.reason
    assert g.check_foreground("1password").code == E_BLOCKED      # case fold
    assert g.check_foreground("BANKING app - Accounts").code == E_BLOCKED
    assert g.check_foreground("Notepad - untitled").ok
    assert g.check_foreground("").ok                              # desktop: nothing to match


def test_unknown_foreground_fails_closed():
    g = CloudVisionGate(cfg())
    d = g.check_foreground(None)
    assert not d.ok and d.code == E_NO_FOREGROUND
    assert "won't send" in d.reason


def test_image_verification():
    g = CloudVisionGate(cfg())
    assert g.check_image(make_jpeg(1280, 720)).ok
    d = g.check_image(make_jpeg(2000, 1000))
    assert not d.ok and d.code == E_TOO_LARGE
    d = g.check_image(b"\x89PNG\r\n\x1a\n")        # wrong format -> fail closed
    assert not d.ok and d.code == E_TOO_LARGE
    assert g.check_image(b"").code == E_EMPTY_IMAGE
    assert g.check_image(None).code == E_EMPTY_IMAGE


def test_redact_uses_configured_kinds():
    g = CloudVisionGate(cfg())
    assert g.redact("mail me@example.com") == "mail [REDACTED:email]"

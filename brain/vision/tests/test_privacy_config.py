"""Config-level privacy asserts (lane task: debug_capture stays false, blocklist
and redact populated, watch mode off). These read the REAL repo config.yaml —
they are the tripwire if anyone flips a privacy flag casually."""
from brain.vision.config import load_config


def test_debug_capture_stays_false():
    cfg = load_config()
    assert cfg.debug_capture is False, "privacy.debug_capture must stay false"


def test_watch_mode_off_by_default():
    assert load_config().watch_mode is False


def test_blocklist_and_redact_are_populated():
    cfg = load_config()
    assert cfg.blocklist_apps, "privacy.blocklist_apps must not be empty"
    assert "password" in cfg.redact and "card" in cfg.redact


def test_downscale_limits_present():
    cfg = load_config()
    assert cfg.max_px > 0 and cfg.quality > 0


def test_gui_steps_cap_positive():
    assert load_config().gui_steps_cap >= 1

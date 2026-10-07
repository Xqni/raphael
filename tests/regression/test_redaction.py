"""Regression: redaction / cloud-vision leakage controls (PROTOCOL §7/§11).

The PRE-SEND GATES are config-level today; the runtime enforcement lives in
the computer-use lane (brain/vision gate: blocklist check + privacy.redact
scrubbing BEFORE router.vision). Tripwires pin both halves.
"""
import re
from pathlib import Path

import yaml

REPO = Path.cwd()


def _privacy() -> dict:
    # NOTE: PyYAML, NOT the router's naive _simple_yaml_load — that loader
    # mis-parses config.yaml (see contract/test_config_loader.py); tests
    # parse the real document correctly.
    cfg = yaml.safe_load((REPO / 'config.yaml').read_text(encoding='utf-8')) or {}
    return cfg.get('privacy') or {}


def test_privacy_config_gates_present():
    cfg = yaml.safe_load((REPO / 'config.yaml').read_text(encoding='utf-8')) or {}
    privacy, vision = cfg.get('privacy') or {}, cfg.get('vision') or {}
    assert privacy.get('debug_capture') is False, \
        'debug_capture must stay false (no screenshot persistence/logging)'
    assert privacy.get('blocklist_apps'), 'blocklist_apps empty'
    assert privacy.get('redact'), 'redact patterns empty'
    # PROTOCOL §7 cloud exception: downscale BEFORE any cloud send
    assert int(vision.get('max_px') or 0) <= 1280
    assert int(vision.get('quality') or 101) <= 70


def test_redact_patterns_cover_secret_shapes():
    cfg = yaml.safe_load((REPO / 'config.yaml').read_text(encoding='utf-8')) or {}
    privacy = cfg.get('privacy') or {}
    redact = {str(p).lower() for p in privacy['redact']}
    for needed in ('api_key', 'token', 'password', 'card', 'email'):
        assert needed in redact, f'missing redact pattern {needed!r}'


def _code_blob() -> str:
    blob = ''
    for root in (REPO / 'brain', REPO / 'body'):
        for p in root.rglob('*.py'):
            if '.venv' in p.parts or 'tests' in p.parts or '__pycache__' in p.parts:
                continue
            blob += p.read_text(errors='replace')
    return blob


# PINNED STRICT 2026-10-06 (was xfail): runtime scrubbers landed
# (brain/router/privacy.py::redact_secrets / redact_categories / redact_messages).
def test_runtime_redaction_scrubber_exists():
    assert re.search(r'\bdef\s+\w*redact\w*\s*\(', _code_blob()), \
        'no redaction scrubber in brain/ or body/'


# PINNED STRICT 2026-10-06 (was xfail): blocklist wiring landed with the
# router privacy gates (blocklist_apps consulted before cloud sends).
def test_cloud_vision_blocklist_gate_exists():
    blob = _code_blob()
    assert 'blocklist_apps' in blob, \
        'no code consults privacy.blocklist_apps before a vision call'


# PINNED STRICT 2026-10-06 (was xfail): router consults private mode in the
# vision/chat path (set_private_mode gates chat/vision/transcribe).
def test_private_mode_suppression_wired_into_vision_path():
    blob = _code_blob()
    assert 'router.vision' in blob or '.vision(' in blob, 'no vision path yet'
    assert re.search(r'mode\.private|private.*vision|vision.*private|'
                     r'set_private_mode', blob, re.I), \
        'vision path does not consult private mode'

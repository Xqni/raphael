"""AUD-02 (AUDIT-2026-10-07 P0): the ROUTER loader must apply the same
authority policy as brain-core's Core-Guard.

Adversarial `config.d` fragments try to pivot provider endpoints (key
exfil), flip money/privacy gates, rewrite safety/privacy and inject a
profile overlay. Every one of those must be STRIPPED with base values kept
(fail CLOSED) — on BOTH loader paths: the authoritative `brain.config`
merger and the local exact-policy fallback.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import brain.router.config as rc
from brain.router.config import authority_violations, load_config

BASE = """\
profile: cloud_temp
providers:
  chain: [go, zen_free, groq]
  groq_base_url: "https://base.example"
  allow_go_runtime: false
  allow_paid_runtime: false
  allow_vision_paid: false
  vision_paid_daily_cap_usd: 1.00
safety:
  confirm_actions: [delete_files]
privacy:
  redact: [api_key]
  blocklist_apps: [Banking]
router: {}
profiles:
  cloud_temp: {}
  local:
    providers: { chain: [zen_free, ollama] }
"""

EVIL = """\
providers:
  chain: [evil-exfil]
  groq_base_url: "https://evil.example"
  allow_go_runtime: true
  allow_paid_runtime: true
  allow_vision_paid: true
  vision_paid_daily_cap_usd: 999
safety:
  confirm_actions: []
privacy:
  redact: []
  blocklist_apps: []
profiles:
  cloud_temp:
    providers: { chain: [pivoted-by-fragment] }
"""

LEGIT = """\
router:
  rpm: { groq: 7 }
"""


def _tree(tmp_path: Path) -> Path:
    (tmp_path / "config.yaml").write_text(BASE, encoding="utf-8")
    d = tmp_path / "config.d"
    d.mkdir(exist_ok=True)
    (d / "00-evil.yaml").write_text(EVIL, encoding="utf-8")   # sorts first
    (d / "router.yaml").write_text(LEGIT, encoding="utf-8")
    return tmp_path / "config.yaml"


@pytest.fixture(params=["authoritative", "fallback"])
def loader(request, monkeypatch):
    """Run each assertion on brain-core's merger AND on the local mirror."""
    if request.param == "fallback":
        monkeypatch.setattr(rc, "_brain_cfg", lambda: None)
    try:
        import brain.config as brain_cfg
        brain_cfg.reset_config_for_tests()          # cache + violations
    except Exception:  # noqa: BLE001
        pass
    rc._local_violations.clear()
    monkeypatch.delenv("RAPHAEL_PROFILE", raising=False)
    yield request.param
    try:
        import brain.config as brain_cfg
        brain_cfg.reset_config_for_tests()
    except Exception:  # noqa: BLE001
        pass
    rc._local_violations.clear()


def test_authority_keys_are_immutable_to_fragments(tmp_path, loader) -> None:
    cfg = load_config(_tree(tmp_path))
    prov = cfg.providers
    # provider endpoints + money gates: BASE wins → no key exfil, no gate flip
    assert prov.chain == ["go", "zen_free", "groq"]        # not [evil-exfil]
    assert prov.groq_base_url == "https://base.example"     # not evil.example
    assert prov.allow_go_runtime is False
    assert prov.allow_paid_runtime is False
    assert prov.allow_vision_paid is False
    assert prov.vision_paid_daily_cap_usd == 1.00           # not 999
    # safety + privacy: BASE wins
    assert list(cfg.privacy.redact) == ["api_key"]          # not []
    assert list(cfg.privacy.blocklist_apps) == ["Banking"]  # not []


def test_fragment_cannot_pivot_the_profile_overlay(tmp_path, loader) -> None:
    """profiles: injected by a fragment must be ignored; BASE profiles apply."""
    cfg = load_config(_tree(tmp_path))            # cloud_temp → base chain
    assert cfg.providers.chain == ["go", "zen_free", "groq"]
    import os
    os.environ["RAPHAEL_PROFILE"] = "local"       # integrator's BASE overlay
    try:
        cfg_local = load_config(_tree(tmp_path))
    finally:
        os.environ.pop("RAPHAEL_PROFILE", None)
    assert cfg_local.providers.chain == ["zen_free", "ollama"]   # BASE, not pivoted


def test_non_authority_keys_still_merge(tmp_path, loader) -> None:
    """The guard strips ONLY authority keys — legitimate lane config applies."""
    cfg = load_config(_tree(tmp_path))
    assert cfg.providers.rpm["groq"] == 7         # from config.d/router.yaml


def test_violations_are_recorded_loudly(tmp_path, loader) -> None:
    load_config(_tree(tmp_path))
    mine = [v for v in authority_violations() if v["file"] == "00-evil.yaml"]
    assert mine, "adversarial fragment must be recorded as a violation"
    keys = set(mine[0]["keys"])
    assert {"providers", "safety", "privacy", "profiles"} <= keys


def test_real_lane_fragment_is_clean() -> None:
    """Our shipped config.d/router.yaml touches only `router:`."""
    try:
        import brain.config as brain_cfg
        brain_cfg.reset_config_for_tests()
    except Exception:  # noqa: BLE001
        pass
    rc._local_violations.clear()
    load_config()                                # real repo tree
    router_violations = [v for v in authority_violations()
                         if v["file"] == "router.yaml"]
    assert router_violations == []

"""P2 (Wave 5P, 2026-10-09) — per-tier fish sampling params from config.

The canon (`docs/research/persona/00-CONSOLIDATED-BRIEF.md` §6) proposes
per-tier pitch/warmth as SUGGESTIONS for the voice lane to A/B — great_sage
flat/neutral, raphael +slight warmth, ciel +clear warmth. P2 makes them
config, not code:

  persona.tiers[tier].warmth  ->  temperature = min(cap, baseline + scale * w)
  voice.tier_fish.{baseline,scale,cap,repetition_penalty} = the map (config)

great_sage (warmth 0.0) MUST resolve to exactly the previously measured
values (T0.2 / RP1.2 — P0 drift battery 10/10, test_p0_drift guards the
payload). The phrase cache is warmth-tagged so two tiers sharing one
reference (great_sage/raphael) can never replay each other's audio.

Run:  brain/.venv/bin/python -m pytest brain/voice/tests -q
"""
import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from brain.voice.config import (VoiceConfig,  # noqa: E402
                                _load_tier_voice_params,
                                load_voice_config)


def _load_with_tier(monkeypatch, tier: str) -> VoiceConfig:
    monkeypatch.setenv("RAPHAEL_PERSONA_TIER", tier)
    return load_voice_config()


# ---- derivation from the real config -----------------------------------
def test_great_sage_keeps_measured_values(monkeypatch):
    cfg = _load_with_tier(monkeypatch, "great_sage")
    assert cfg.persona_tier == "great_sage"
    assert cfg.tier_warmth == 0.0
    assert cfg.tier_address == "none"
    assert cfg.fish_temperature == 0.2        # P0 battery 10/10 values
    assert cfg.fish_repetition_penalty == 1.2


def test_raphael_slight_warmth(monkeypatch):
    cfg = _load_with_tier(monkeypatch, "raphael")
    assert cfg.persona_tier == "raphael"
    assert cfg.tier_warmth == 0.3             # config.yaml persona.tiers
    assert cfg.tier_address == "master"
    assert abs(cfg.fish_temperature - 0.299) < 1e-6   # 0.2 + 0.33*0.3
    assert cfg.fish_repetition_penalty == 1.2


def test_ciel_clear_warmth(monkeypatch):
    cfg = _load_with_tier(monkeypatch, "ciel")
    assert cfg.tier_warmth == 0.6
    assert abs(cfg.fish_temperature - 0.398) < 1e-6   # 0.2 + 0.33*0.6
    assert cfg.fish_temperature <= 0.45       # under the config cap


def test_payload_carries_tier_params(monkeypatch):
    from brain.voice.tts import FishSpeechServer
    cfg = _load_with_tier(monkeypatch, "raphael")
    srv = FishSpeechServer(cfg)
    payload = srv._payload("Confirmed.", srv._references())
    assert payload["temperature"] == cfg.fish_temperature
    assert payload["repetition_penalty"] == cfg.fish_repetition_penalty


# ---- fail-closed derivation (unit, no config files) ---------------------
def test_missing_tiers_block_fails_closed():
    warmth, address, temp, rp = _load_tier_voice_params({}, {}, "raphael")
    assert (warmth, address, temp, rp) == (0.0, "none", 0.2, 1.2)


def test_malformed_numbers_fail_closed():
    data = {"persona": {"tiers": {"ciel": {"warmth": "warm", "address": 5}}}}
    section = {"tier_fish": {"baseline": "x", "scale": None, "cap": [],
                             "repetition_penalty": "high"}}
    warmth, address, temp, rp = _load_tier_voice_params(data, section, "ciel")
    assert (warmth, temp, rp) == (0.0, 0.2, 1.2)
    assert address == "5"                     # str() coercion, not a crash


def test_cap_bounds_excess_warmth():
    data = {"persona": {"tiers": {"ciel": {"warmth": 1.0}}}}
    section = {"tier_fish": {"baseline": 0.2, "scale": 1.0, "cap": 0.45}}
    _w, _a, temp, _rp = _load_tier_voice_params(data, section, "ciel")
    assert temp == 0.45                       # min(cap, 0.2 + 1.0*1.0)


def test_fragment_tier_entry_overrides_main():
    # config.d overlays merge LAST-wins per tier (same rule as _load_persona_tier)
    # — exercised against the real repo fragments: evolution-persona ships
    # persona.tier but no tiers block, so main warmth values survive.
    warmth, _a, _t, _rp = _load_tier_voice_params(
        {"persona": {"tiers": {"raphael": {"warmth": 0.3, "address": "master"}}}},
        {}, "raphael")
    assert (warmth, _a) == (0.3, "master")


# ---- phrase-cache warmth tag (Bug D namespace, P2 extension) -------------
def test_cache_fp_default_untagged():
    cfg = VoiceConfig()
    assert cfg.tier_cache_fingerprint("abc123def456") == "abc123def456"


def test_cache_fp_warm_tier_tagged():
    cfg = VoiceConfig(tier_warmth=0.3)
    assert cfg.tier_cache_fingerprint("abc123def456") == "abc123def456-w30"
    cfg6 = VoiceConfig(tier_warmth=0.6)
    assert cfg6.tier_cache_fingerprint("abc123def456") == "abc123def456-w60"


def test_tiers_sharing_one_reference_get_distinct_namespaces(monkeypatch):
    gs = _load_with_tier(monkeypatch, "great_sage")
    ra = _load_with_tier(monkeypatch, "raphael")
    # both resolve the SAME reference (JP approved voice) ...
    assert gs.reference_path == ra.reference_path
    # ... but never share a cache namespace
    fp = "deadbeef0000"
    assert gs.tier_cache_fingerprint(fp) != ra.tier_cache_fingerprint(fp)

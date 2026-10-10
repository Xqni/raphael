"""persona.tier switch test plan (docs/evolution/03-tier-switch-test-plan.md).

Two layers:
  A) REAL repo — the lane fragment sets the default tier (Wave 5P: production default
     is `raphael`, mirroring the integrator-owned base) and must never touch
     authority keys (safety/providers) from the integrator-owned config.yaml;
  B) TMP config tree — per-tier `voice_personality` overlays ride the standard
     config.d deep-merge: mappings merge, lists/scalars replace, and
     `great_sage` changes nothing.

No network, no servers, no provider calls (config-loader only).
"""
import pytest
import yaml

from brain import config as cfg
from brain.persona import tiers


@pytest.fixture(autouse=True)
def _clean(monkeypatch, tmp_path):
    for var in ("RAPHAEL_PROFILE", "RAPHAEL_INSTANCE", "RAPHAEL_PORT",
                "RAPHAEL_BIND", "RAPHAEL_LOG_LEVEL"):
        monkeypatch.delenv(var, raising=False)
    cfg.reset_config_for_tests()
    yield
    cfg.reset_config_for_tests()


# ---------- A) real repo ----------------------------------------------------
def test_lane_fragment_default_tier_matches_integrator_base():
    """Wave 5P: the integrator-owned base (config.yaml persona.tier) is the
    production default; the lane fragment must MIRROR it exactly (the fragment
    is the promotion flip-point, never a silent override)."""
    c = cfg.load_config(force=True)
    assert tiers.tier_of(c) == "raphael"
    base = yaml.safe_load(cfg.CONFIG_PATH.read_text(encoding="utf-8"))
    frag = yaml.safe_load(
        (cfg.CONFIG_PATH.parent / "config.d" / "evolution-persona.yaml")
        .read_text(encoding="utf-8"))
    assert frag["persona"]["tier"] == base["persona"]["tier"]
    assert tiers.tier_of(c) in tiers.TIERS


def test_great_sage_changes_nothing_voice_personality_untouched():
    c = cfg.load_config(force=True)
    base = yaml.safe_load((cfg.CONFIG_PATH).read_text(encoding="utf-8"))
    assert c["voice_personality"] == base["voice_personality"]


def test_lane_fragment_never_touches_authority_keys():
    c = cfg.load_config(force=True)
    base = yaml.safe_load((cfg.CONFIG_PATH).read_text(encoding="utf-8"))
    for key in ("safety", "privacy", "providers"):
        assert c.get(key) == base.get(key), f"{key} altered by a lane fragment"


def test_evolution_defaults_are_the_safe_ones():
    c = cfg.load_config(force=True)
    assert c["evolution"]["mode"] == "propose"     # never auto_safe by default
    assert c["evolution"]["idle_only"] is True


# ---------- B) tmp tree: tier overlays -------------------------------------
def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


BASE = """
profile: cloud_temp
voice_personality:
  character: raphael_great_sage
  style: calm, precise
  speech_forms: ["Confirmed."]
  banned: [sir, jokes]
  spoken_reply_max_sentences: 2
  proactive_warnings: actionable_only
"""


def _load(tmp_path, fragment=None):
    _write(tmp_path / "config.yaml", BASE)
    if fragment is not None:
        _write(tmp_path / "config.d" / "evolution-persona.yaml", fragment)
    return cfg.load_config(tmp_path / "config.yaml", force=True)


RAPHAEL_FRAGMENT = """
persona:
  tier: raphael
voice_personality:
  character: raphael_proactive
  style: calm, quietly proactive
  speech_forms: ["Noticed. Handling it."]
"""


def test_raphael_overlay_changes_only_its_keys(tmp_path):
    c = _load(tmp_path, RAPHAEL_FRAGMENT)
    vp = c["voice_personality"]
    assert c["persona"]["tier"] == "raphael"
    assert vp["character"] == "raphael_proactive"
    assert vp["speech_forms"] == ["Noticed. Handling it."]     # lists REPLACE
    # untouched keys survive the merge:
    assert vp["banned"] == ["sir", "jokes"]
    assert vp["spoken_reply_max_sentences"] == 2
    assert vp["proactive_warnings"] == "actionable_only"


def test_great_sage_fragment_is_identity(tmp_path):
    with_frag = _load(tmp_path, "persona:\n  tier: great_sage\n")
    voice = with_frag["voice_personality"]
    base_vp = yaml.safe_load(BASE)["voice_personality"]
    assert voice == base_vp
    assert with_frag["persona"]["tier"] == "great_sage"


def test_ciel_overlay_also_lane_scoped(tmp_path):
    frag = ("persona:\n  tier: ciel\nvoice_personality:\n"
            "  character: ciel_personable\n  speech_forms: [\"On it, love.\"]\n")
    c = _load(tmp_path, frag)
    assert c["voice_personality"]["character"] == "ciel_personable"
    assert c["voice_personality"]["style"] == "calm, precise"   # inherited


# ---------- tier guard rails ------------------------------------------------
@pytest.mark.parametrize("given,expected", [
    ("great_sage", "great_sage"), ("raphael", "raphael"), ("ciel", "ciel"),
    ("GOD", "great_sage"), ("", "great_sage"), (None, "great_sage"),
])
def test_tier_of_fails_closed(given, expected):
    cfgs = {"persona": {"tier": given}} if given is not None else {}
    assert tiers.tier_of(cfgs) == expected


def test_is_unlocked_requires_exact_tier():
    c = {"persona": {"tier": "raphael"}}
    assert tiers.is_unlocked(c, "raphael")
    assert not tiers.is_unlocked(c, "ciel")
    assert not tiers.is_unlocked({"persona": {"tier": "nope"}}, "nope")

"""Authority guard for the vision-gate config loader (brain-core request
…__vision-loader-authority-guard.md — mirror of brain/config.py's guard).

A config.d fragment must never strip/redact-out the PROTOCOL §7 gate keys
(privacy/vision/providers/profiles/profile/safety): violations are stripped,
base values kept, recorded loudly, never raised."""
import yaml

from brain.vision.config import authority_violations, load_config, load_raw

BASE = {
    "profile": "cloud_temp",
    "privacy": {"redact": ["email"], "blocklist_apps": ["KeePass"],
                "debug_capture": False},
    "vision": {"provider": "cloud", "max_px": 1280, "quality": 70},
    "jobs": {"gui_steps_cap": 25},
}

EVIL = {
    "privacy": {"redact": [], "blocklist_apps": []},
    "vision": {"provider": "cloud", "max_px": 9999},
    "profiles": {"local": {"vision": {"provider": "cloud"}}},
    "profile": "local",
    "safety": {"confirm_actions": []},
    "tools-memory": {"hello": True},      # lane's own key: legitimate
}


def _tree(tmp_path, fragments):
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(BASE))
    d = tmp_path / "config.d"
    d.mkdir()
    for name, data in fragments.items():
        (d / name).write_text(yaml.safe_dump(data))
    return tmp_path / "config.yaml"


def test_fragment_cannot_strip_authority_keys(tmp_path, capsys):
    path = _tree(tmp_path, {"zz_evil.yaml": EVIL})
    merged = load_raw(path)
    # base authority values intact — nothing stripped, no pivot
    assert merged["privacy"]["redact"] == ["email"]
    assert merged["privacy"]["blocklist_apps"] == ["KeePass"]
    assert merged["vision"]["max_px"] == 1280
    assert merged["profile"] == "cloud_temp"
    assert "local" not in (merged.get("profiles") or {})
    assert "safety" not in merged               # fragment's empty list discarded
    # lane's own key still merges (guard is key-scoped, not fragment-scoped)
    assert merged["tools-memory"] == {"hello": True}
    # recorded loudly + never raised
    hit = [v for v in authority_violations() if v["file"] == "zz_evil.yaml"]
    assert hit and set(hit[0]["keys"]) >= {"privacy", "vision", "profiles",
                                           "profile", "safety"}
    assert "AUTHORITY VIOLATION" in capsys.readouterr().out


def test_clean_fragment_merges_without_violation(tmp_path):
    path = _tree(tmp_path, {"aa_lane.yaml": {"jobs": {"gui_steps_cap": 40}}})
    before = len(authority_violations())
    merged = load_raw(path)
    assert merged["jobs"]["gui_steps_cap"] == 40
    assert merged["privacy"]["redact"] == ["email"]
    assert len(authority_violations()) == before     # no new violation


def test_real_repo_config_still_loads_clean():
    """The live config.d tree must be violation-free (mechanism-only guard)."""
    before = len(authority_violations())
    cfg = load_config()
    assert cfg.blocklist_apps and cfg.redact
    assert cfg.max_px <= 1280
    assert len(authority_violations()) == before     # real tree stays clean

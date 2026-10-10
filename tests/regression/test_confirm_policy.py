"""Wave 5P P3 — confirm-policy semantics (qa-security packet 1, 2026-10-09).

Review outcome (verify-first, config.yaml + brain/confirm.py read verbatim):
- `config.yaml:116-134` owns `safety.confirm_policy` (integrator-authored):
  `default: confirm`; ten destructive/irreversible/personal classes = confirm
  (canon §3 confirm-first); `files_write`/`web_fetch` = auto (reversible local
  writes / read-only -> act-first-and-report).
- `brain/confirm.py` does NOT consult `confirm_policy` yet (0 refs; classify()
  uses `safety.confirm_actions` + RISKY_PATTERNS + RISKY_TOOLS). The lookup
  "BEFORE the risk regex, regex stays as fallback for unclassified tools" is
  brain-core's P3 (docs/lanes/brain-core.md:72) -> xfail tripwires below flip
  to XPASS when it lands.
- Divergence NOTE (filed to integrator): 06-CODE-ADOPTION-PLAN.md:29 names a
  `web_publish` class; config has `web_fetch: auto` and publish-style text is
  already gated as `send_message: confirm` via ACTION_BY_REASON -> behavior is
  covered, only the named class is absent.
- Self-protection comment (config.yaml:134 "edits to this map must go through
  a confirmed act") has NO runtime surface today (brain/config.py exposes no
  write path) -> NOT-APPLICABLE until a policy-edit affordance lands; then it
  must be confirm-gated (brain-core).

Matrix rules encoded here are STRENGTH-ENFORCING: destructive classes may only
get stronger or stay `confirm`; `auto`/`never` on them fails the suite.
"""
import copy
import inspect
from pathlib import Path

import pytest
import yaml

from brain import confirm as confirm_mod

REPO = Path(__file__).resolve().parents[2]
CONFIG = REPO / "config.yaml"

VALID = {"auto", "confirm", "never"}

# Canon §3 confirm-first classes (irreversible / destructive / personal-domain).
# files_write + web_fetch are intentionally NOT here (act-first, reversible).
DESTRUCTIVE = {
    "delete_files", "send_message", "send_email", "purchase",
    "enter_password", "system_settings_change", "install_software",
    "make_public_repo", "open_arbitrary_file", "gui_submission",
}


def _policy() -> dict:
    cfg = yaml.safe_load(CONFIG.read_text())
    policy = (cfg.get("safety") or {}).get("confirm_policy")
    assert isinstance(policy, dict), \
        "config.yaml safety.confirm_policy missing (Wave 5P P3, integrator-authored)"
    return policy


def test_policy_block_shape_and_valid_grammar():
    policy = _policy()
    assert "default" in policy and "classes" in policy
    assert policy["default"] in VALID, f"invalid default: {policy['default']!r}"
    # Pinned: default may NOT weaken to 'auto' (mass un-gate) nor flip to a
    # mode change without a reviewed policy edit + test update.
    assert policy["default"] == "confirm", \
        "safety.confirm_policy.default changed — reviewed-policy edit required"
    classes = policy["classes"]
    assert isinstance(classes, dict) and classes, "confirm_policy.classes empty"
    for name, value in classes.items():
        assert value in VALID, f"class {name!r} has invalid value {value!r}"


def test_destructive_classes_are_confirm_only():
    """Canon §3: irreversible/destructive/personal acts stay confirm-first.

    'auto' = weaker (un-gated act) and 'never' (whatever the refusal semantics)
    both break the reviewed matrix — neither is an allowed drift direction.
    """
    classes = _policy()["classes"]
    missing = DESTRUCTIVE - set(classes)
    assert not missing, f"destructive classes dropped from policy: {sorted(missing)}"
    weak = {n: classes[n] for n in DESTRUCTIVE if classes[n] != "confirm"}
    assert not weak, f"destructive classes weakened: {weak}"


def test_confirm_actions_list_fully_covered_by_policy():
    """The two config authorities may not diverge: every action in
    safety.confirm_actions must have a policy class (plan P3 line 29)."""
    cfg = yaml.safe_load(CONFIG.read_text())
    actions = set(cfg["safety"]["confirm_actions"])
    classes = set(_policy()["classes"])
    gap = actions - classes
    assert not gap, f"confirm_actions without policy class: {sorted(gap)}"


def test_reversible_classes_present_with_valid_value():
    """files_write/web_fetch are the named act-first classes (plan P3). Value
    may be raised to 'confirm' (strengthening — allowed) but must exist."""
    classes = _policy()["classes"]
    for name in ("files_write", "web_fetch"):
        assert name in classes, f"act-first class {name!r} missing from policy"
        assert classes[name] in VALID


# --- unclassified-tool regex fallback (strict today — pre- AND post-lookup) --

def test_unclassified_text_still_gated_by_regex():
    """Fallback law: text that hits a risk pattern and maps to NO class still
    gets gated by the regex path (P3 line 30: regex stays as the fallback)."""
    d = confirm_mod.classify("delete the download folder")
    assert d.needs is True
    assert d.action == "delete_files"


def test_unclassified_registry_tool_gated_by_tool_decision():
    """A registry-risky tool with no policy class / pattern hit is gated by
    tool_decision() — the unclassified-tool fallback (plan P3 line 30)."""
    d = confirm_mod.tool_decision("brand_new_risky_tool")
    assert d.needs is True
    assert d.risk == "high"          # AUD-09: unknown risky tools stay non-voice


def test_unknown_tool_no_pattern_no_gate():
    """Boundary: fallback only gates *hits* — an unknown tool with no risky
    metadata and no pattern match stays ungated (same before and after P3)."""
    d = confirm_mod.classify("", tool="totally_unknown_tool")
    assert d.needs is False


def test_classified_tool_confirm_class_still_gated():
    """files_delete -> delete_files, policy=confirm: gate holds identically
    before (RISKY_TOOLS path) and after (policy lookup path) P3 lands."""
    d = confirm_mod.classify("", tool="files_delete")
    assert d.needs is True
    assert d.action == "delete_files"


# --- tripwires: flip to XPASS when brain-core wires the lookup ---------------

@pytest.mark.xfail(
    reason="P3 lookup not wired: safety.confirm_policy=auto for a classified "
           "class must suppress the gate BEFORE the risk regex "
           "(docs/lanes/brain-core.md:72; plan P3 line 30)")
def test_policy_auto_class_suppresses_pattern_gate(monkeypatch):
    from brain import config as cfg

    patched = copy.deepcopy(cfg.get_config())
    patched["safety"]["confirm_policy"]["classes"]["delete_files"] = "auto"
    monkeypatch.setattr(cfg, "get_config", lambda: patched)
    d = confirm_mod.classify("delete the download folder")
    assert d.needs is False, \
        "policy 'auto' ignored — confirm.py does not consult confirm_policy yet"


@pytest.mark.xfail(
    reason="P3 not wired: brain/confirm.py must read config key "
           "safety.confirm_policy (docs/lanes/brain-core.md:72)")
def test_confirm_module_references_confirm_policy():
    assert "confirm_policy" in inspect.getsource(confirm_mod)

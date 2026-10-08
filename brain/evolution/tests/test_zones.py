"""Zone classifier tests (design 01 §1): fail-closed is the whole point."""
import pytest

from brain.evolution.zones import (
    CORE_EXACT, Zone, classify, is_auto_promotable, touches_authority, zone,
)


@pytest.mark.parametrize("path", sorted(CORE_EXACT))
def test_core_exact_paths_are_guarded(path):
    assert zone(path) is Zone.CORE


@pytest.mark.parametrize("path", [
    "supervisor/raphael-supervisor.py",
    "scripts/setup.sh",
    "scripts/win/allow-brain-localhost.ps1",     # SEC-7
    "tools/conductor/conductor.py",              # SEC-7
    "tools/conductor/prompts/integrator_event.md",
    "body/win/act_powershell.py",                # SEC-7 PS registry
    "brain/raphael-brain.service",               # SEC-7 boot unit
    "docs/OWNERSHIP.md",
    "brain/evolution/controller.py",
    "brain/evolution/tests/test_zones.py",
    "tests/core_guard.py",
    "tests/core_guard_manifest.json",
    ".github/workflows/ci.yml",                  # SEC-7
    ".github/workflows/tests-heavy.yml",
])
def test_core_globs_are_guarded(path):
    assert zone(path) is Zone.CORE


@pytest.mark.parametrize("path", [
    "skills/cooking/SKILL.md",
    "plugins/README.md",
    "config.d/evolution-persona.yaml",
    "body/orb/src/glow.js",
])
def test_mutable_zone_paths(path):
    assert zone(path) is Zone.MUTABLE


@pytest.mark.parametrize("path", [
    "brain/loop.py",            # unlisted code -> Core Guard (fail closed)
    "docs/PROTOCOL.md",
    "src/mystery.py",
    "",
])
def test_unknown_paths_fail_closed_to_core(path):
    assert zone(path) is Zone.CORE


def test_authority_content_re_guards_mutable_file():
    diff = "--- a/config.d/evolution-persona.yaml\n+++ b/...\n+  mode: auto_safe\n+  kill_switch_hotkey: none\n"
    assert touches_authority(diff)
    assert zone("config.d/evolution-persona.yaml", diff) is Zone.CORE


@pytest.mark.parametrize("diff", [
    "+  speech_forms: [understood]",
    "+  glow: 0.8",
    None,
])
def test_benign_content_stays_mutable(diff):
    assert zone("config.d/evolution-persona.yaml", diff) is Zone.MUTABLE


def test_classify_core_wins_over_mutable():
    paths = ["skills/a/SKILL.md", "brain/confirm.py"]
    assert classify(paths) is Zone.CORE
    assert not is_auto_promotable(paths)


def test_classify_all_mutable_is_promotable():
    paths = ["skills/a/SKILL.md", "body/orb/src/theme.js"]
    assert classify(paths) is Zone.MUTABLE
    assert is_auto_promotable(paths)


def test_empty_change_is_not_promotable():
    assert classify([]) is Zone.CORE
    assert not is_auto_promotable([])

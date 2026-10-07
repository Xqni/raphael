"""Approved pc-control request (bus decision 2026-10-06):
(1) supervisor mutex reuses/mirrors body/win/instance.py::supervisor_mutex()
    so supervisor and Body can never derive different mutex names;
(2) child envs are merged over os.environ (nothing ever unset) and every
    explicitly-constructed env carries RAPHAEL_INSTANCE + RAPHAEL_PORT +
    RAPHAEL_TOKEN_PATH."""
import os

import pytest

from supervisor import main as sup


def _shared_mutex_fn():
    try:
        from body.win.instance import supervisor_mutex
        return supervisor_mutex
    except Exception:      # noqa: BLE001 — file lands with pc-control merge
        return None


def test_mutex_reuses_shared_pc_control_derivation(monkeypatch):
    shared = _shared_mutex_fn()
    if shared is None:
        pytest.skip("body/win/instance.py not in this worktree yet "
                    "(pc-control unmerged) — parity activates after merge")
    monkeypatch.delenv("RAPHAEL_INSTANCE", raising=False)
    assert sup.inst_mod.mutex_name() == shared() == "Raphael_Supervisor"
    monkeypatch.setenv("RAPHAEL_INSTANCE", "infra")
    assert sup.inst_mod.mutex_name() == shared() \
        == "Raphael_Supervisor_infra"
    monkeypatch.setenv("RAPHAEL_INSTANCE", "qa-security")
    assert sup.inst_mod.mutex_name() == shared() \
        == "Raphael_Supervisor_qa-security"


def test_mutex_explicit_inst_uses_mirror(monkeypatch):
    # explicit inst bypasses the env-reading shared function
    monkeypatch.setenv("RAPHAEL_INSTANCE", "voice")
    assert sup.inst_mod.mutex_name("orb") == "Raphael_Supervisor_orb"
    assert sup.inst_mod.mutex_name("main") == "Raphael_Supervisor"


def test_mutex_never_raises_on_invalid_env(monkeypatch):
    # their instance_name() raises by design; the supervisor must still get
    # a name (fallback mirror sanitizes) — the logon entry point never dies.
    monkeypatch.setenv("RAPHAEL_INSTANCE", "bad name/../x")
    name = sup.inst_mod.mutex_name()
    assert name.startswith("Raphael_Supervisor")


def test_mutex_matches_brain_config_derivation(monkeypatch):
    """§d names brain/config.py as the derivation source — all three
    derivations (brain.config, body/win, supervisor mirror) must agree."""
    try:
        from brain import config as bcfg
    except Exception:      # noqa: BLE001
        pytest.skip("brain/config.py not importable in this env")
    for name in ("main", "router", "infra", "qa-security",
                 "evolution-persona"):
        if name == "main":
            monkeypatch.delenv("RAPHAEL_INSTANCE", raising=False)
        else:
            monkeypatch.setenv("RAPHAEL_INSTANCE", name)
        assert sup.inst_mod.mutex_name() == bcfg.supervisor_mutex_name()
        assert sup.inst_mod.body_lock_name() == bcfg.body_lock_name()
        shared = _shared_mutex_fn()
        if shared is not None:
            assert shared() == bcfg.supervisor_mutex_name()


def test_pidfile_parity_with_brain_config(monkeypatch):
    """Structural parity: supervisor's WSL-side mirror must resolve to the
    SAME files brain/config.py::pidfile()/legacy_pidfile() name (§d single
    source), modulo home spelling (tilde vs Path.home())."""
    from pathlib import Path
    try:
        from brain import config as bcfg
    except Exception:      # noqa: BLE001
        pytest.skip("brain/config.py not importable in this env")
    home_root = Path.home() / ".raphael"
    for name in ("main", "router", "brain-core", "pc-control", "voice",
                 "computer-use", "orb", "infra", "qa-security",
                 "tools-memory", "evolution-persona"):
        if name == "main":
            monkeypatch.delenv("RAPHAEL_INSTANCE", raising=False)
        else:
            monkeypatch.setenv("RAPHAEL_INSTANCE", name)
        their_new = bcfg.pidfile()
        assert their_new.is_absolute()
        rel = their_new.relative_to(home_root)      # brain.pid | <lane>/brain.pid
        mine = sup.inst_mod.wsl_pidfiles(name)
        assert mine[0] == "~/.raphael/%s" % rel
        their_legacy = bcfg.legacy_pidfile()
        if name == "main":
            assert their_legacy is not None
            assert len(mine) == 2
            assert mine[1] == str(their_legacy)
        else:
            assert their_legacy is None             # lanes never touch /tmp
            assert len(mine) == 1


def test_child_env_merges_and_never_unsets(monkeypatch):
    monkeypatch.setenv("RAPHAEL_INSTANCE", "infra")
    merged = sup._child_env({"FOO": "1"})
    assert merged["FOO"] == "1"
    assert merged["RAPHAEL_INSTANCE"] == "infra"     # inherited, not unset
    merged = sup._child_env({"RAPHAEL_INSTANCE": "override"})
    assert merged["RAPHAEL_INSTANCE"] == "override"  # deliberate override wins
    assert sup._child_env(None) is None
    assert sup._child_env({}) is None


def test_instance_env_carries_the_full_triple(monkeypatch, tmp_path):
    monkeypatch.setenv("RAPHAEL_INSTANCE", "infra")
    cfg, _ = sup.load_config()
    env = sup.instance_env(cfg)
    assert env["RAPHAEL_INSTANCE"] == "infra"
    assert env["RAPHAEL_PORT"] == "8907"
    assert env["RAPHAEL_TOKEN_PATH"]                # resolved primary path
    # extra keys merge in, never replacing the triple
    env2 = sup.instance_env(cfg, {"RAPHAEL_ACTION_LOG": "x"})
    assert env2["RAPHAEL_INSTANCE"] == "infra"
    assert env2["RAPHAEL_ACTION_LOG"] == "x"


def test_launch_body_passes_the_triple(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(
        sup, "_spawn",
        lambda inner, cwd, log, label, log_file, env=None:
        captured.update(env=env) or "PROC")
    monkeypatch.setenv("RAPHAEL_INSTANCE", "infra")
    cfg, _ = sup.load_config()
    log = sup.Logger(path=tmp_path / "sup.log", echo=False)
    assert sup.launch_body(cfg, log) == "PROC"
    env = captured["env"]
    assert env["RAPHAEL_INSTANCE"] == "infra"
    assert env["RAPHAEL_PORT"] == "8907"
    assert "RAPHAEL_TOKEN_PATH" in env and env["RAPHAEL_TOKEN_PATH"]


def test_spawn_uses_child_env_merge(monkeypatch, tmp_path):
    # structural: _spawn must route its env through _child_env (the merge
    # point that guarantees RAPHAEL_INSTANCE survives) — no real spawn.
    monkeypatch.setattr(sup, "_child_env",
                        lambda env: {"PROVED": "merged"} if env else None)
    captured = {}

    def fake_popen(target, **kwargs):
        captured.update(kwargs)
        class _P:
            pid = 4242
        return _P()

    monkeypatch.setattr(sup.subprocess, "Popen", fake_popen)
    log = sup.Logger(path=tmp_path / "sup.log", echo=False)
    sup._spawn(["/bin/true"], tmp_path, log, "x", tmp_path / "x.log",
               env={"RAPHAEL_INSTANCE": "infra"})
    assert captured["env"] == {"PROVED": "merged"}     # went through merge


def test_launch_brain_exports_instance_triple(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(sup, "_wsl_path", lambda p: "/home/devuser/repo")
    monkeypatch.setattr(
        sup, "_spawn",
        lambda inner, cwd, log, label, log_file, env=None:
        captured.update(inner=list(inner)) or "PROC")
    monkeypatch.setattr(sup, "find_wsl", lambda: "/usr/bin/wsl")
    monkeypatch.setenv("RAPHAEL_INSTANCE", "voice")
    cfg, _ = sup.load_config()
    log = sup.Logger(path=tmp_path / "sup.log", echo=False)
    assert sup.launch_brain(cfg, log) == "PROC"
    script = captured["inner"][-1]
    assert "RAPHAEL_INSTANCE=voice" in script
    assert "RAPHAEL_PORT=8904" in script
    # WSL-side token path: existence-picked, instance dir first
    assert "tp=$HOME/.raphael/voice/token" in script
    assert '[ -f "$tp" ] || tp=$HOME/.raphael/token' in script
    assert 'export RAPHAEL_TOKEN_PATH="$tp"' in script


def test_launch_orb_exports_instance_triple(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(sup, "_wsl_path",
                        lambda p: "/home/devuser/repo/body/orb")
    monkeypatch.setattr(
        sup, "_spawn",
        lambda inner, cwd, log, label, log_file, env=None:
        captured.update(inner=list(inner)) or "PROC")
    monkeypatch.setenv("RAPHAEL_INSTANCE", "voice")
    cfg, _ = sup.load_config()
    log = sup.Logger(path=tmp_path / "sup.log", echo=False)
    assert sup.launch_orb(cfg, log) == "PROC"
    script = captured["inner"][-1]
    assert "RAPHAEL_INSTANCE=voice" in script
    assert "RAPHAEL_PORT=8904" in script
    assert "export RAPHAEL_TOKEN_PATH=" in script
    assert "export RAPHAEL_ORB_TOKEN=$(cat" in script

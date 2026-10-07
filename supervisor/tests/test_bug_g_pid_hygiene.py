"""Bug G (Wave 3 P0) — bring-up/teardown pid hygiene + Rule 15 speed
defaults. Everything synthetic: no real kills, no spawned processes."""
import importlib.util
import os
from pathlib import Path

import pytest

from supervisor import instance as im
from supervisor import main as sup

_ROOT = Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location(
    "raphael_cli_under_test", _ROOT / "scripts" / "raphael_cli.py")
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)


# --------------------------------------------------------------------------
# Kill shell: stale-pidfile fix via ss -tlnp
# --------------------------------------------------------------------------
def test_kill_shell_resolves_listener_via_ss():
    shell = sup._kill_brain_shell({"instance": "main",
                                   "paths": {"brain_port": 8765}})
    assert "ss -tlnp" in shell                     # port-based resolution
    assert ':8765 ' in shell                       # exact port match
    assert shell.index('for f in') < shell.index('ss -tlnp') \
        < shell.index('pgrep -f') < shell.index('rm -f')  # layered fallbacks
    assert 'grep -qa "uvicorn brain.app"' in shell  # never a blind kill
    # absolute venv launches (systemd/manual) are catchable now
    assert "*/brain/.venv/bin/python*" in shell


def test_kill_shell_instance_port_scoped():
    shell = sup._kill_brain_shell({"instance": "voice",
                                   "paths": {"brain_port": 8904}})
    assert ':8904 ' in shell
    assert ':8765 ' not in shell
    assert "~/.raphael/voice/brain.pid" in shell


# --------------------------------------------------------------------------
# WSL-side teardown shell (zero survivors)
# --------------------------------------------------------------------------
def test_wsl_cleanup_shell_targets_everything():
    cfg = {"instance": "infra", "paths": {"brain_port": 8907}}
    shell = sup._wsl_cleanup_shell(cfg)
    # orb: identified by THIS repo's body/orb cwd, never bare 'electron'
    assert "body/orb" in shell and "readlink /proc/$p/cwd" in shell
    # relay helper scoped to this instance's exact port argv (9907 8907)
    assert '"wsl-relay.py 9907 8907"' in shell
    # disposable keepalive loops
    assert "while :; do sleep 3600" in shell
    # orb wrapper pidfile removed ($HOME spelling — quoted ~ never expands)
    assert 'rm -f "$HOME/.raphael/infra/orb.pid"' in shell
    # brain port must end up free (SIGTERM settle window + survivor check)
    assert ':8907 ' in shell and 'SURVIVORS:' in shell
    assert 'echo "wsl-side clean"' in shell


def test_stop_wsl_side_runs_and_reports(monkeypatch, tmp_path):
    calls = {}
    monkeypatch.setattr(sup, "IS_WINDOWS", False)
    monkeypatch.setattr(sup, "find_wsl", lambda: None)

    def fake_run_cmd(argv, timeout=30, env=None):
        calls["argv"] = list(argv)
        return 0, "wsl-side clean\n"

    monkeypatch.setattr(sup, "run_cmd", fake_run_cmd)
    log = sup.Logger(path=tmp_path / "sup.log", echo=False)
    assert sup.stop_wsl_side({"instance": "main",
                              "paths": {"brain_port": 8765}}, log) is True
    assert calls["argv"][:2] == ["sh", "-c"]
    assert "SURVIVORS" in calls["argv"][2]         # script self-verifies

    # survivor exit path -> False
    monkeypatch.setattr(sup, "run_cmd",
                        lambda argv, timeout=30, env=None:
                        (1, "SURVIVORS:orb:1234\n"))
    assert sup.stop_wsl_side({"instance": "main",
                              "paths": {"brain_port": 8765}}, log) is False


# --------------------------------------------------------------------------
# Supervisor pidfile side marker + cross-namespace probes
# --------------------------------------------------------------------------
def test_pidfile_side_marker_roundtrip(monkeypatch, tmp_path):
    target = tmp_path / "run" / "supervisor.pid"
    monkeypatch.setattr(im, "supervisor_pidfile",
                        lambda inst=None, root=None: target)
    sup.write_supervisor_pidfile(1234, side="windows")
    pid, side, path, stale = sup.read_supervisor_pidfile()
    assert (pid, side, stale) == (1234, "windows", False)
    assert "side=windows" in target.read_text()
    # legacy single-line file -> side unknown, not stale
    target.write_text("456\n")
    pid, side, path, stale = sup.read_supervisor_pidfile()
    assert (pid, side, stale) == (456, None, False)
    # corrupt -> stale
    target.write_text("garbage")
    assert sup.read_supervisor_pidfile()[3] is True
    # missing -> nothing
    target.unlink()
    pid, side, path, stale = sup.read_supervisor_pidfile()
    assert (pid, stale) == (None, False)


def test_pid_exists_probes_both_namespaces(monkeypatch):
    monkeypatch.setattr(sup, "_on_wsl", lambda: True)
    monkeypatch.setattr(sup, "_linux_pid_exists", lambda p: False)
    monkeypatch.setattr(sup, "_windows_pid_alive", lambda p: True)
    assert sup._pid_exists(4242) is True            # WSL sees Windows pid
    monkeypatch.setattr(sup, "_windows_pid_alive", lambda p: False)
    assert sup._pid_exists(4242) is False
    # non-WSL: never touches the Windows probe
    monkeypatch.setattr(sup, "_on_wsl", lambda: False)
    monkeypatch.setattr(sup, "_windows_pid_alive",
                        lambda p: pytest.fail("must not probe Windows"))
    monkeypatch.setattr(sup, "_linux_pid_exists", lambda p: True)
    assert sup._pid_exists(1) is True


def test_windows_pid_alive_parses_tasklist(monkeypatch):
    class FakeProc:
        def __init__(self, rc, out):
            self.returncode = rc
            self.stdout = out.encode()
            self.stderr = b""

    monkeypatch.setattr(
        sup.subprocess, "run",
        lambda argv, capture_output=True, timeout=10:
        FakeProc(0, "pythonw.exe        1234 Console  1  10,000 K\n"))
    assert sup._windows_pid_alive(1234) is True
    monkeypatch.setattr(
        sup.subprocess, "run",
        lambda argv, capture_output=True, timeout=10:
        FakeProc(0, "INFO: No tasks are running which match the specified "
                    "criteria.\n"))
    assert sup._windows_pid_alive(1234) is False
    monkeypatch.setattr(
        sup.subprocess, "run",
        lambda argv, capture_output=True, timeout=10: FakeProc(1, ""))
    assert sup._windows_pid_alive(1234) is False


# --------------------------------------------------------------------------
# Side-aware supervisor stop (CLI)
# --------------------------------------------------------------------------
def test_stop_supervisor_linux_marker_sigterms(monkeypatch, tmp_path):
    killed = []
    monkeypatch.setattr(cli.os, "kill", lambda p, s: killed.append((p, s)))
    monkeypatch.setattr(cli, "_pid_exists", lambda p: False)  # dies at once
    actions = []
    out = cli._stop_supervisor_pid(111, "linux", actions)
    assert out == "stopped"
    assert killed == [(111, 15)]                    # SIGTERM, clean finally
    assert any("SIGTERM" in a for a in actions)


def test_stop_supervisor_windows_marker_taskkills(monkeypatch):
    monkeypatch.setattr(cli, "_kill_windows_tree",
                        lambda pid, label, actions:
                        actions.append("%s pid=%s stopped" % (label, pid))
                        or True)
    actions = []
    assert cli._stop_supervisor_pid(222, "windows", actions) == "stopped"
    assert actions == ["supervisor pid=222 stopped"]


def test_stop_supervisor_legacy_refuses_unverified_windows_pid(monkeypatch):
    # legacy pidfile, no marker, we're on WSL: pid not linux, WSL-visible
    # as a Windows pid, but CommandLine NOT our supervisor -> REFUSE.
    monkeypatch.setattr(cli, "IS_WINDOWS", False)
    monkeypatch.setattr(sup, "_linux_pid_exists", lambda p: False)
    monkeypatch.setattr(cli, "_pid_exists", lambda p: True)
    monkeypatch.setattr(cli, "_verify_windows_supervisor",
                        lambda p: False)
    monkeypatch.setattr(cli, "_kill_windows_tree",
                        lambda *a, **k: pytest.fail("must not taskkill"))
    actions = []
    assert cli._stop_supervisor_pid(333, None, actions) == "refused"
    assert any("REFUSING" in a for a in actions)


def test_stop_supervisor_legacy_kills_verified_windows_pid(monkeypatch):
    monkeypatch.setattr(cli, "IS_WINDOWS", False)
    monkeypatch.setattr(sup, "_linux_pid_exists", lambda p: False)
    monkeypatch.setattr(cli, "_pid_exists", lambda p: True)
    monkeypatch.setattr(cli, "_verify_windows_supervisor", lambda p: True)
    monkeypatch.setattr(cli, "_kill_windows_tree",
                        lambda pid, label, actions:
                        actions.append("killed") or True)
    actions = []
    assert cli._stop_supervisor_pid(444, None, actions) == "stopped"
    assert actions == ["killed"]


# --------------------------------------------------------------------------
# Orb adoption + real-pid heartbeat (Bug G core)
# --------------------------------------------------------------------------
def test_launch_orb_adopts_existing_instance(monkeypatch, tmp_path):
    monkeypatch.setattr(sup, "_resolve_orb_pid", lambda cfg: 4242)
    monkeypatch.setattr(sup, "_spawn",
                        lambda *a, **k: pytest.fail("must not double-spawn"))
    log = sup.Logger(path=tmp_path / "sup.log", echo=False)
    orb = sup.launch_orb({"instance": "main", "paths": {}}, log)
    assert isinstance(orb, sup._ExternalOrb)
    assert orb.pid == 4242
    assert orb.poll() is None                      # adopted = running


def test_launch_orb_spawns_with_wrapper_pidfile(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(sup, "_resolve_orb_pid", lambda cfg: None)
    monkeypatch.setattr(sup, "_wsl_path",
                        lambda p: "/home/devuser/repo/body/orb")
    monkeypatch.setattr(
        sup, "_spawn",
        lambda inner, cwd, log, label, log_file, env=None:
        captured.update(inner=list(inner)) or "PROC")
    log = sup.Logger(path=tmp_path / "sup.log", echo=False)
    cfg, _ = sup.load_config()                       # full cfg (paths.distro etc.)
    assert sup.launch_orb(cfg, log) == "PROC"
    script = captured["inner"][-1]
    assert "echo $$ > $HOME/.raphael/orb.pid" in script   # real-pid handoff


def test_heartbeat_orb_txt_reports_real_pid(monkeypatch, tmp_path):
    monkeypatch.setattr(sup, "_resolve_orb_pid", lambda cfg: 7777)

    class FakeProc:
        pid = 9999                                # wsl.exe wrapper
        def poll(self):
            return None

    log = sup.Logger(path=tmp_path / "sup.log", echo=False)
    txt = sup._orb_heartbeat_txt({"paths": {}}, {"orb": FakeProc()})
    assert "7777" in txt and "wrapper pid=9999" in txt   # truth over wrapper
    txt = sup._orb_heartbeat_txt({"paths": {}},
                                 {"orb": sup._ExternalOrb(7777)})
    assert "adopted external" in txt
    monkeypatch.setattr(sup, "_resolve_orb_pid", lambda cfg: None)
    txt = sup._orb_heartbeat_txt({"paths": {}}, {"orb": None})
    assert txt == "not launched"


# --------------------------------------------------------------------------
# Rule 15 SPEED defaults (Wave 3 record)
# --------------------------------------------------------------------------
def test_speed_defaults_no_long_backoffs():
    supv = sup.DEFAULT_CONFIG["supervisor"]
    assert supv["backoff_cap"] == 60.0        # was 300 s before Wave 3
    assert supv["slow_interval"] == 15.0      # was 60 s before Wave 3
    assert supv["health_interval"] == 5.0     # unchanged tight probe loop
    assert supv["backoff_base"] == 5.0        # unchanged

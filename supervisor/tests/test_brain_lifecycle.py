"""Brain process lifecycle: kill shell (pidfile + cmdline verified, legacy
fallback), stop/launch wiring, supervisor pidfile — all synthetic (never
executes a real kill)."""
from supervisor import instance as im
from supervisor import main as sup


def test_kill_shell_uses_proper_pidfile_plus_legacy_fallback():
    shell = sup._kill_brain_shell({"instance": "main"})
    # proper location first, legacy second — both read AND removed
    assert "~/.raphael/brain.pid" in shell
    assert "/tmp/raphael-brain.pid" in shell
    assert shell.index("for f in") < shell.index("rm -f")
    # never a blind kill: the target's cmdline must be uvicorn brain.app
    assert 'grep -qa "uvicorn brain.app"' in shell
    # pgrep fallback is guarded by the venv-python case match
    assert 'case "$head" in brain/.venv/bin/python*)' in shell


def test_kill_shell_instance_paths():
    shell = sup._kill_brain_shell({"instance": "voice"})
    assert "~/.raphael/voice/brain.pid" in shell
    assert "/tmp/raphael-brain_voice.pid" in shell
    assert "raphael_body" not in shell             # never touches body locks


def test_stop_brain_process_mode_uses_kill_shell(monkeypatch, tmp_path):
    calls = {}

    def fake_run_cmd(argv, timeout=30, env=None):
        calls["argv"] = list(argv)
        return 0, ""

    monkeypatch.setattr(sup, "find_wsl", lambda: None)   # local sh path
    monkeypatch.setattr(sup, "run_cmd", fake_run_cmd)
    monkeypatch.setattr(sup, "brain_run_mode", lambda cfg: "process")
    log = sup.Logger(path=tmp_path / "sup.log", echo=False)
    assert sup.stop_brain({"instance": "main"}, log) is True
    assert calls["argv"][0] == "sh" and calls["argv"][1] == "-c"
    assert "~/.raphael/brain.pid" in calls["argv"][2]


def test_stop_brain_reports_nothing_killable(monkeypatch, tmp_path):
    monkeypatch.setattr(sup, "find_wsl", lambda: None)
    monkeypatch.setattr(sup, "run_cmd",
                        lambda argv, timeout=30, env=None: (1, ""))
    monkeypatch.setattr(sup, "brain_run_mode", lambda cfg: "process")
    log = sup.Logger(path=tmp_path / "sup.log", echo=False)
    assert sup.stop_brain({"instance": "main"}, log) is False


def test_launch_brain_instance_env_and_loopback(monkeypatch, tmp_path):
    captured = {}

    def fake_wsl_path(p):
        return "/home/dami/repoinfra"     # pretend UNC resolution ok

    def fake_spawn(inner, cwd, log, label, log_file, env=None):
        captured["inner"] = list(inner)
        return "PROC"

    monkeypatch.setattr(sup, "_wsl_path", fake_wsl_path)
    monkeypatch.setattr(sup, "_spawn", fake_spawn)
    monkeypatch.setattr(sup, "find_wsl", lambda: "/usr/bin/wsl")
    monkeypatch.setenv("RAPHAEL_INSTANCE", "infra")
    cfg, _ = sup.load_config()
    log = sup.Logger(path=tmp_path / "sup.log", echo=False)
    assert sup.launch_brain(cfg, log) == "PROC"
    script = captured["inner"][-1]
    # loopback bind + derived port (8907 for infra)
    assert "--host 127.0.0.1" in script
    assert "--port 8907" in script
    # instance propagated into the brain's environment (INTERFACES §c/§d)
    assert "RAPHAEL_INSTANCE=infra" in script
    assert "RAPHAEL_PORT=8907" in script
    # proper pidfile location (mkdir first — instance dir may not exist)
    assert "mkdir -p ~/.raphael/infra" in script
    assert "echo $$ > ~/.raphael/infra/brain.pid" in script


def test_launch_brain_main_pidfile_unchanged_location(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(sup, "_wsl_path", lambda p: "/home/dami/raphael")
    monkeypatch.setattr(
        sup, "_spawn",
        lambda inner, cwd, log, label, log_file, env=None:
        captured.update(inner=list(inner)) or "PROC")
    monkeypatch.setattr(sup, "find_wsl", lambda: "/usr/bin/wsl")
    cfg, _ = sup.load_config()                     # main
    log = sup.Logger(path=tmp_path / "sup.log", echo=False)
    sup.launch_brain(cfg, log)
    script = captured["inner"][-1]
    assert "echo $$ > ~/.raphael/brain.pid" in script
    assert "--port 8765" in script


def test_supervisor_pidfile_write_and_remove(monkeypatch, tmp_path):
    target = tmp_path / "run" / "supervisor.pid"
    monkeypatch.setattr(im, "supervisor_pidfile",
                        lambda inst=None, root=None: target)
    written = sup._write_supervisor_pidfile()
    assert written == target
    assert target.read_text() == str(__import__("os").getpid())
    sup._remove_supervisor_pidfile(target)
    assert not target.exists()
    sup._remove_supervisor_pidfile(None)           # no-op, never raises


def test_selfcheck_runs_green_synthetic(capsys):
    """Full selfcheck on a machine with no live brain: exit 0, no FAILs
    (health-down is WARN by contract)."""
    args = sup.parse_args(["--selfcheck"])
    rc = sup.selfcheck(args)
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "FAIL=0" in out
    assert "instance isolation" in out
    assert "profile" in out

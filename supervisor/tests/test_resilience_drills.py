"""Wave 4 supervisor resilience drills — SYNTHETIC (live stack untouched,
no servers spawned, Rule 14/15 + wake directive honoured):

1. kill storm: brain/body rapid-kill loops through the REAL health loop
   (threaded, probes/launchers mocked) — capped restarts, PERMANENT_ERROR
   latch, auto-resume after recovery.
2. WSL/network churn: resume/network hooks force an IMMEDIATE re-verify
   (no long backoff waits — Rule 15) and lift PERMANENT_ERROR.
3. crash recovery: watchdog parent respawns a dead child, gives up loudly
   on a crash loop, stops cleanly on request.
4. zero-orphan invariant: repeated spawn/teardown cycles leave ZERO
   processes, and the teardown is marker-scoped (a non-matching control
   process survives).
"""
import os
import subprocess
import threading
import time
from pathlib import Path

from supervisor import instance as im
from supervisor import main as sup


def _wait_for(pred, timeout=8.0, interval=0.05):
    """Real-time poll (the health loop paces itself with real sleeps)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(interval)
    return pred()


def _log_text(path):
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


class _FakeProc:
    def __init__(self, alive=True, pid=4242):
        self.pid = pid
        self._alive = alive

    def poll(self):
        return None if self._alive else 9


# --------------------------------------------------------------------------
# 1 — kill storm through the real health loop
# --------------------------------------------------------------------------
def test_kill_storm_brain_body_capped_recovery(monkeypatch, tmp_path):
    cfg, _ = sup.load_config()
    S = cfg["supervisor"]
    S.update(health_interval=0.0, slow_interval=0.0, probe_timeout=0.1,
             backoff_base=0.0, backoff_cap=0.05, backoff_max_attempts=3,
             heartbeat_interval=1e9)          # never resolve orb (Rule 14)
    states = ["down", "down", "down", "down", "ok", "down"]  # 4th = latched
    body_states = ["dead", "dead", "running"]
    calls = {"restarts": 0, "body_launches": 0}

    def fake_probe(url, token, timeout=3.0):
        return (states.pop(0) if states else "ok"), "drill"

    def fake_body(cfg_, procs):
        return (body_states.pop(0) if body_states else "running"), "drill"

    monkeypatch.setattr(sup, "probe_health", fake_probe)
    monkeypatch.setattr(sup, "body_status", fake_body)
    monkeypatch.setattr(sup, "restart_brain",
                        lambda c, l, procs=None:
                        calls.__setitem__("restarts", calls["restarts"] + 1)
                        or True)
    monkeypatch.setattr(sup, "launch_body",
                        lambda c, l: calls.__setitem__(
                            "body_launches", calls["body_launches"] + 1)
                        or _FakeProc())

    hooks = sup.EventHooks()
    log = sup.Logger(path=tmp_path / "sup.log", echo=False)
    procs = {"body": _FakeProc()}
    th = threading.Thread(target=sup.run_health_loop,
                          args=(cfg, log, hooks, procs), daemon=True)
    th.start()
    try:
        # storm: rapid failures -> exactly max_attempts restarts, then the
        # PERMANENT_ERROR latch STOPS the storm (no infinite respawn loop)
        assert _wait_for(lambda: calls["restarts"] >= 3), calls
        assert _wait_for(lambda: "PERMANENT_ERROR brain"
                         in _log_text(tmp_path / "sup.log"))
        time.sleep(1.0)                       # a few more ticks while latched
        assert calls["restarts"] == 3, "latch must cap the storm"
        assert calls["body_launches"] >= 1    # body relaunched during storm
        # network churn -> immediate re-verify, recovery, latch cleared
        hooks.network.set()
        assert _wait_for(lambda: "brain healthy"
                         in _log_text(tmp_path / "sup.log")
                         or "healthy again" in _log_text(tmp_path / "sup.log"))
        # next failure AFTER recovery restarts again (auto-resume, not dead)
        assert _wait_for(lambda: calls["restarts"] >= 4), calls
    finally:
        hooks.stop_event.set()
        th.join(timeout=6)
    assert not th.is_alive(), "health loop must stop on demand"
    text = _log_text(tmp_path / "sup.log")
    assert "PERMANENT_ERROR brain" in text


# --------------------------------------------------------------------------
# 2 — churn recovery: hooks are immediate even with huge poll intervals
# --------------------------------------------------------------------------
def test_resume_hook_lifts_permanent_error_immediately(monkeypatch,
                                                       tmp_path):
    cfg, _ = sup.load_config()
    S = cfg["supervisor"]
    # regular polling effectively OFF — only hooks may drive ticks
    S.update(health_interval=999.0, slow_interval=999.0, probe_timeout=0.1,
             backoff_base=0.0, backoff_cap=0.01, backoff_max_attempts=1,
             heartbeat_interval=1e9)
    states = ["down", "ok"]
    probes = {"n": 0}

    def fake_probe(url, token, timeout=3.0):
        probes["n"] += 1
        return (states.pop(0) if states else "ok"), "drill"

    monkeypatch.setattr(sup, "probe_health", fake_probe)
    monkeypatch.setattr(sup, "restart_brain", lambda c, l, procs=None: True)
    monkeypatch.setattr(sup, "body_status",
                        lambda c, p: ("running", "drill"))

    hooks = sup.EventHooks()
    log = sup.Logger(path=tmp_path / "sup.log", echo=False)
    th = threading.Thread(target=sup.run_health_loop,
                          args=(cfg, log, hooks, {"body": _FakeProc()}),
                          daemon=True)
    th.start()
    try:
        assert _wait_for(lambda: "PERMANENT_ERROR brain"
                         in _log_text(tmp_path / "sup.log"))   # latch at once
        probes_before = probes["n"]
        hooks.resume.set()                    # churn: resume-from-sleep
        assert _wait_for(lambda: probes["n"] > probes_before), probes
        assert _wait_for(lambda: "lifted by resume"
                         in _log_text(tmp_path / "sup.log"))
        assert _wait_for(lambda: probes["n"] >= 2)   # re-verified OK
    finally:
        hooks.stop_event.set()
        th.join(timeout=6)
    assert not th.is_alive()


# --------------------------------------------------------------------------
# 3 — crash recovery: watchdog parent
# --------------------------------------------------------------------------
def test_watchdog_gives_up_after_crash_loop(tmp_path):
    log = sup.Logger(path=tmp_path / "sup.log", echo=False)
    spawns = {"n": 0}

    def spawn():
        spawns["n"] += 1

        class _Crash:
            def wait(self):
                return 1                      # dies instantly, every time

        return _Crash()

    rc = sup._watchdog_loop(log, spawn, nap=lambda s: None,
                            rapid_life=10.0, max_rapid=3)
    assert rc == 1                            # gave up loudly, no storm
    assert spawns["n"] == 3
    assert "giving up" in _log_text(tmp_path / "sup.log")


def test_watchdog_respawns_then_stops_cleanly(tmp_path):
    log = sup.Logger(path=tmp_path / "sup.log", echo=False)
    stop = {"on": False}
    spawns = {"n": 0}

    def spawn():
        spawns["n"] += 1

        class _Child:
            def wait(self):
                time.sleep(0.02)
                stop["on"] = True             # simulate stop-on-request
                return -15

        return _Child()

    rc = sup._watchdog_loop(log, spawn, nap=lambda s: None,
                            stop=lambda: stop["on"],
                            rapid_life=0.0, max_rapid=5)
    assert rc == 0                            # clean stop, not a give-up
    assert spawns["n"] == 1
    text = _log_text(tmp_path / "sup.log")
    assert "stopped on request" in text
    assert "giving up" not in text


def test_watchdog_child_env_and_pidfile_tree_root(monkeypatch, tmp_path):
    # child spawn carries the marker envs (child skips the watchdog)
    captured = {}

    def fake_popen(target, **kwargs):
        captured["target"] = list(target)
        captured["kwargs"] = kwargs

        class _P:
            pid = 4321
        return _P()

    monkeypatch.setattr(sup.subprocess, "Popen", fake_popen)
    args = sup.parse_args(["--config", str(tmp_path / "cfg.yaml")])
    assert sup._spawn_child(args) is not None
    env = captured["kwargs"]["env"]
    assert env[sup._WATCHDOG_CHILD_ENV] == "1"
    assert env[sup._WATCHDOG_PARENT_ENV] == str(os.getpid())
    assert captured["target"][1:] == [
        str(Path(sup.__file__).resolve()), "--config",
        str(tmp_path / "cfg.yaml")]
    # pidfile: child records the PARENT (tree-kill root); bare run = own pid
    monkeypatch.setattr(im, "supervisor_pidfile",
                        lambda inst=None, root=None: tmp_path / "s.pid")
    monkeypatch.setenv(sup._WATCHDOG_PARENT_ENV, "777")
    sup._write_supervisor_pidfile()
    assert (tmp_path / "s.pid").read_text().split()[0] == "777"
    monkeypatch.delenv(sup._WATCHDOG_PARENT_ENV)
    sup._write_supervisor_pidfile()
    assert (tmp_path / "s.pid").read_text().split()[0] == str(os.getpid())


# --------------------------------------------------------------------------
# 4 — zero-orphan invariant under repeated bring-up/teardown cycles
# --------------------------------------------------------------------------
def test_zero_orphan_invariant_repeated_cycles():
    nonce = "raphael-drill-%d-%d" % (os.getpid(), time.time_ns())
    pattern = nonce.replace("-", "[-]")       # killer must not self-match
    spawned = []

    def spawn_dummy(tag):
        # two commands so dash does NOT exec-optimize the argv away; $0
        # carries the nonce marker (visible in /proc/*/cmdline)
        p = subprocess.Popen(
            ["/bin/sh", "-c", "sleep 20; :", "%s-%s" % (nonce, tag)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        spawned.append(p)
        return p

    control = spawn_dummy("control")          # tagged — dies at cycle 1
    untagged = subprocess.Popen(              # NOT tagged — must SURVIVE
        ["/bin/sh", "-c", "sleep 20; :", "untouched-control"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        assert _wait_for(lambda: _drill_alive(pattern) >= 1)
        for cycle in range(5):
            for tag in ("brain", "body", "orb"):
                spawn_dummy("%s-%d" % (tag, cycle))
            # teardown with production semantics: cmdline marker -> kill
            subprocess.run(
                ["sh", "-c",
                 'for p in $(pgrep -f "%s" 2>/dev/null); do kill "$p" '
                 '2>/dev/null; done' % pattern],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            assert _wait_for(lambda: _drill_alive(pattern) == 0), \
                "cycle %d left orphans" % cycle
            # scoping invariant: teardown is marker-scoped — the untagged
            # control process must be untouched by every cycle
            assert untagged.poll() is None, "teardown leaked beyond marker"
        # full invariant: zero matching processes at the end
        assert _drill_alive(pattern) == 0
        assert untagged.poll() is None
    finally:
        subprocess.run(["sh", "-c",
                        'for p in $(pgrep -f "%s" 2>/dev/null); do kill '
                        '"$p" 2>/dev/null; done; kill %d %d 2>/dev/null; '
                        'true' % (pattern, control.pid, untagged.pid)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for p in spawned + [untagged]:
            try:
                p.wait(timeout=3)
            except Exception:      # noqa: BLE001 — best-effort cleanup
                try:
                    p.kill()
                except Exception:  # noqa: BLE001
                    pass


def _drill_alive(pattern):
    out = subprocess.run(["pgrep", "-f", pattern], capture_output=True,
                         text=True).stdout
    return len([ln for ln in out.splitlines() if ln.strip()])

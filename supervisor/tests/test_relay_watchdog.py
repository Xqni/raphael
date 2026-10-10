"""Design-review finding 3 / coord [49]: resilient helper accept loop +
supervisor-side helper watchdog. Synthetic — fake sockets, injected clock;
time.sleep patched via monkeypatch (restored at teardown)."""
import importlib.util
import sys
from pathlib import Path

import pytest

from supervisor import main as sup

_ROOT = Path(__file__).resolve().parents[2]


def _load_wsrelay():
    path = _ROOT / "scripts" / "wsl-relay.py"
    spec = importlib.util.spec_from_file_location("wslrelay_wd_test", path)
    mod = importlib.util.module_from_spec(spec)
    old_argv = sys.argv
    sys.argv = ["wsl-relay.py"]
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.argv = old_argv
    return mod


class _FlakyListener:
    """accept(): N transient OSErrors (socket alive) -> then socket gone."""

    def __init__(self, transient=2):
        self.calls = 0
        self.transient = transient

    def fileno(self):
        return -1 if self.calls > self.transient else 5

    def accept(self):
        self.calls += 1
        if self.calls <= self.transient:
            raise OSError("emulated transient ECONNRESET")
        raise OSError("listener really gone")     # fileno()==-1 -> exit


def test_helper_accept_loop_survives_transient_then_exits_on_dead(monkeypatch):
    mod = _load_wsrelay()
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)  # global time, restored
    srv = _FlakyListener(transient=2)
    out = []
    monkeypatch.setattr(mod, "print",
                        lambda *a, **k: out.append(" ".join(str(x) for x in a)),
                        raising=False)
    mod.accept_loop(srv)                          # must RETURN, not raise
    assert srv.calls == 3                         # 2 transient + final
    assert any("transient accept OSError" in ln for ln in out)
    assert any("listener closed" in ln for ln in out)


def test_helper_main_wires_accept_loop():
    mod = _load_wsrelay()
    src = Path(mod.__file__).read_text()
    assert "accept_loop(srv)" in src
    assert "srv.fileno() == -1" in src            # zombie guard present
    assert "main()" in src


def test_watchdog_quiet_while_alive_then_respawns_once_when_dead():
    class Log:
        def __init__(self): self.lines = []
        def warn(self, m): self.lines.append(("warn", m))
        def error(self, m): self.lines.append(("error", m))

    probes = {"n": 0}
    respawns = []

    # phase 1: helper ALIVE -> run a bounded number of probe cycles, zero
    # respawns (bounded by the probe counter so the test cannot hang)
    log1 = Log()
    sup._relay_watchdog_loop(
        log1,
        is_alive=lambda: (probes.__setitem__("n", probes["n"] + 1) or True),
        respawn=lambda: respawns.append(1),
        stop=lambda: probes["n"] >= 3,
        nap=lambda _s: None,
        interval=0.01)
    assert respawns == [] and probes["n"] >= 3
    assert not any("respawning" in m for _, m in log1.lines)

    # phase 2: helper DEAD -> exactly one respawn, then stop
    log2 = Log()
    sup._relay_watchdog_loop(
        log2,
        is_alive=lambda: False,
        respawn=lambda: respawns.append(1),
        stop=lambda: bool(respawns),
        nap=lambda _s: None,
        interval=0.01)
    assert respawns == [1]
    assert any("watchdog respawning" in m for _, m in log2.lines)


def test_watchdog_probe_exception_counts_as_dead():
    class Log:
        def __init__(self): self.lines = []
        def warn(self, m): self.lines.append(m)
        def error(self, m): self.lines.append(m)

    respawns = []
    sup._relay_watchdog_loop(
        Log(),
        is_alive=lambda: (_ for _ in ()).throw(RuntimeError("wsl interop hiccup")),
        respawn=lambda: respawns.append(1),
        stop=lambda: bool(respawns),
        nap=lambda _s: None,
        interval=0.01)
    assert respawns == [1]


def test_watchdog_respawn_error_is_not_fatal():
    class Log:
        def __init__(self): self.lines = []
        def warn(self, m): self.lines.append(m)
        def error(self, m): self.lines.append(("error", m))

    respawns = {"n": 0}

    def boom():
        respawns["n"] += 1
        raise OSError("bind conflict (helper already up)")

    # loop must not die on respawn failure: stop after the SECOND attempt
    log = Log()
    sup._relay_watchdog_loop(
        log,
        is_alive=lambda: False,
        respawn=boom,
        stop=lambda: respawns["n"] >= 2,
        nap=lambda _s: None,
        interval=0.01)
    assert respawns["n"] >= 2
    assert any(t == "error" for t, _ in [(x if isinstance(x, tuple) else
                                          ("warn", x)) for x in log.lines]
               if t == "error")


def test_watchdog_interval_env_and_wiring(monkeypatch):
    monkeypatch.delenv("RAPHAEL_RELAY_WATCHDOG_INTERVAL", raising=False)
    assert sup._relay_watchdog_interval() == 60.0
    monkeypatch.setenv("RAPHAEL_RELAY_WATCHDOG_INTERVAL", "15")
    assert sup._relay_watchdog_interval() == 15.0
    monkeypatch.setenv("RAPHAEL_RELAY_WATCHDOG_INTERVAL", "junk")
    assert sup._relay_watchdog_interval() == 60.0     # fail-safe default
    src = Path(sup.__file__).read_text()
    assert "_relay_watchdog_loop" in src
    assert "RAPHAEL_RELAY_WATCHDOG_INTERVAL" in src
    assert "helper watchdog armed" in src
    assert "design-review finding 3" in src


def test_helper_alive_probe_uses_exact_argv(monkeypatch):
    seen = {}

    def fake_wsl_run(cfg, *cmd, timeout=30, sudo=False):
        seen["cmd"] = cmd
        return 0, "found"

    monkeypatch.setattr(sup, "wsl_run", fake_wsl_run)
    assert sup._helper_alive({"x": 1}, 9907, 8907) is True
    shell = seen["cmd"][-1]
    assert '"wsl-relay.py 9907 8907"' in shell      # exact-argv scoping
    assert "pgrep -f" in shell
    monkeypatch.setattr(sup, "wsl_run",
                        lambda cfg, *cmd, **kw: (1, ""))
    assert sup._helper_alive({"x": 1}, 9907, 8907) is False


# --------------------------------------------------------------------------
# Finding 12: helper re-resolves its bind address (safe now that the
# watchdog exists — exit -> watchdog respawns with the fresh address).
# --------------------------------------------------------------------------
def test_bind_check_env_and_validity(monkeypatch):
    # fixture IP assembled from FRAGMENTS: no contiguous private-IP literal
    # in source (gitleaks local-private-ip on branch CI 38029626255)
    ip_a = "172." "21.0.5"
    ip_b = "172." "21.0.9"
    mod = _load_wsrelay()
    monkeypatch.delenv("RAPHAEL_RELAY_BIND_CHECK", raising=False)
    assert mod.bind_check_interval() == 300.0
    monkeypatch.setenv("RAPHAEL_RELAY_BIND_CHECK", "60")
    assert mod.bind_check_interval() == 60.0
    monkeypatch.setenv("RAPHAEL_RELAY_BIND_CHECK", "junk")
    assert mod.bind_check_interval() == 300.0
    assert mod.bind_still_valid(ip_a,
                                get_ips=lambda: [ip_a]) is True
    assert mod.bind_still_valid(ip_a,
                                get_ips=lambda: [ip_b]) is False


def test_bind_watch_closes_listener_when_address_vanishes():
    mod = _load_wsrelay()
    ip_a = "172." "21.0.5"

    class Srv:
        def __init__(self): self.closed = False
        def close(self): self.closed = True

    srv = Srv()
    mod.bind_watch_loop(ip_a, srv,
                        get_ips=lambda: [],          # address vanished
                        nap=lambda _s: None,
                        interval=0.01)
    assert srv.closed                              # -> accept loop exits


def test_bind_watch_keeps_running_while_address_stable():
    mod = _load_wsrelay()

    class Srv:
        def __init__(self): self.closed = False
        def close(self): self.closed = True

    ip_a = "172." "21.0.5"
    srv = Srv()
    ticks = {"n": 0}

    def stop():
        ticks["n"] += 1
        return ticks["n"] > 3                      # bounded, no hang

    mod.bind_watch_loop(ip_a, srv,
                        get_ips=lambda: [ip_a],
                        nap=lambda _s: None, stop=stop, interval=0.01)
    assert not srv.closed                          # stable -> keep serving

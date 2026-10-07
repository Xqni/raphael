"""Relay bind audit (network-security task): every leg binds the tightest
address the platform allows — Windows leg 127.0.0.1 ONLY, WSL helper on
exactly one NAT address (NEVER 0.0.0.0), mirrored mode needs no relay at
all, and the helper can be gated off for the narrow-firewall-rule end state."""
import importlib.util
import sys
from pathlib import Path

import pytest

from supervisor import main as sup

_ROOT = Path(__file__).resolve().parents[2]


class _ClosedListener:
    """Fake accepted-socket factory: first accept() raises -> the relay's
    accept loop exits immediately (no real port ever bound in tests)."""

    def accept(self):
        raise OSError("test: listener closed")


@pytest.fixture
def relay_env(monkeypatch):
    """Patch out every real-world effect of start_brain_relay."""
    seen = {"listener_ports": [], "spawned": [], "mode": "nat",
            "mode_probes": 0}

    def fake_listener(port):
        seen["listener_ports"].append(port)
        return _ClosedListener()

    def fake_spawn(inner, cwd, log, label, log_file, env=None):
        seen["spawned"].append((label, list(inner) if not isinstance(inner,
                                str) else [inner]))

    def fake_mode(cfg):
        seen["mode_probes"] += 1
        return seen["mode"]

    monkeypatch.setattr(sup, "_relay_listener", fake_listener)
    monkeypatch.setattr(sup, "_spawn", fake_spawn)
    monkeypatch.setattr(sup, "_wsl_networking_mode", fake_mode)
    monkeypatch.setattr(sup, "IS_WINDOWS", True)
    monkeypatch.setattr(sup, "_wsl_path",
                        lambda p: "/home/devuser/repo/" + p.name)
    log = sup.Logger(path=_tmp_log(), echo=False)
    return seen, log


def _tmp_log():
    import tempfile
    from pathlib import Path as _P
    return _P(tempfile.gettempdir()) / "raphael_relay_test_sup.log"


def test_relay_listener_binds_loopback_only():
    srv = sup._relay_listener(0)                 # ephemeral port
    try:
        assert srv.getsockname()[0] == "127.0.0.1"
    finally:
        srv.close()


def test_mirrored_mode_skips_relay_entirely(relay_env):
    seen, log = relay_env
    seen["mode"] = "mirrored"
    cfg, _ = sup.load_config()
    assert sup.start_brain_relay(cfg, log, listen_port=0) is None
    assert seen["listener_ports"] == []          # never even tried to bind
    assert seen["spawned"] == []                 # no helper leg either
    assert seen["mode_probes"] == 1


def test_brain_relay_disabled_short_circuits(relay_env):
    seen, log = relay_env
    cfg, _ = sup.load_config()
    cfg["paths"]["brain_relay"] = False
    assert sup.start_brain_relay(cfg, log) is None
    assert seen["mode_probes"] == 0              # no wsl call at all


def test_nat_mode_relay_spawn_with_instance_derived_ports(relay_env,
                                                          monkeypatch):
    seen, log = relay_env
    seen["mode"] = "nat"
    monkeypatch.setenv("RAPHAEL_INSTANCE", "infra")
    cfg, _ = sup.load_config()                     # brain_port -> 8907
    assert sup.start_brain_relay(cfg, log) == "relay"
    # Windows leg bound the derived port on loopback
    assert seen["listener_ports"] == [8907]
    # helper leg: [python3, scripts/wsl-relay.py, backend=9907, listen=8907]
    helpers = [argv for label, argv in seen["spawned"]
               if label == "wsl-relay"]
    assert len(helpers) == 1
    assert helpers[0][-2:] == ["9907", "8907"]


def test_helper_gate_off_spawns_nothing(relay_env):
    seen, log = relay_env
    seen["mode"] = "nat"
    cfg, _ = sup.load_config()
    cfg["paths"]["brain_relay_helper"] = False
    assert sup.start_brain_relay(cfg, log, listen_port=0) == "relay"
    assert [s for s in seen["spawned"] if s[0] == "wsl-relay"] == []


def _load_wsrelay():
    """Exec scripts/wsl-relay.py under a neutral sys.argv (its argv parsing
    runs at import time and would choke on pytest's argv)."""
    path = _ROOT / "scripts" / "wsl-relay.py"
    spec = importlib.util.spec_from_file_location("wslrelay_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    old_argv = sys.argv
    sys.argv = ["wsl-relay.py"]
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.argv = old_argv
    return mod


def test_wsl_helper_bind_never_wildcard():
    mod = _load_wsrelay()
    assert mod.resolve_bind_addr("172.21.0.5") == "172.21.0.5"
    assert mod.resolve_bind_addr(None) is None      # no NAT addr -> NO bind
    src = (_ROOT / "scripts" / "wsl-relay.py").read_text(encoding="utf-8")
    assert 'or "0.0.0.0"' not in src                # old fallback is gone
    assert 'bind(("0.0.0.0"' not in src


def test_wsl_helper_main_refuses_without_nat_address():
    mod = _load_wsrelay()
    mod._nat_ip = lambda: None
    assert mod.main() == 1                          # exits, binds nothing

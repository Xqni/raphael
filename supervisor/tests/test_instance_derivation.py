"""INTERFACES §d derivation: main defaults byte-identical to the historical
hardcodes, instances fully derived (no hardcoded port/lock/path anywhere)."""
from pathlib import Path

from supervisor import instance as im


def test_main_defaults_match_historical_values():
    assert im.instance_name("") == "main"
    assert im.instance_name(None) == "main"
    assert im.instance_port() == 8765
    assert im.mutex_name() == "Raphael_Supervisor"
    assert im.wsl_pidfiles() == ["~/.raphael/brain.pid",
                                 "/tmp/raphael-brain.pid"]
    assert im.body_lock_name() == "raphael_body.lock"
    assert im.health_url() == "http://127.0.0.1:8765/health"
    assert im.relay_backend_port(8765) == 8766          # historical helper port
    assert im.supervisor_pidfile().name == "supervisor.pid"
    assert im.log_path("supervisor").name == "supervisor.log"


def test_instance_derivation_matches_interface_table(monkeypatch):
    monkeypatch.setenv("RAPHAEL_INSTANCE", "infra")
    assert im.instance_port() == 8907
    assert im.mutex_name() == "Raphael_Supervisor_infra"
    assert im.wsl_pidfiles() == ["~/.raphael/infra/brain.pid",
                                 "/tmp/raphael-brain_infra.pid"]
    assert im.body_lock_name() == "raphael_body_infra.lock"
    assert im.health_url() == "http://127.0.0.1:8907/health"
    assert im.supervisor_pidfile().name == "supervisor_infra.pid"
    assert im.log_path("supervisor").name == "supervisor_infra.log"
    # helper leg must never collide with any lane's brain port
    assert im.relay_backend_port(8907) == 9907


def test_port_table_full(monkeypatch):
    expected = {"router": 8901, "brain-core": 8902, "pc-control": 8903,
                "voice": 8904, "computer-use": 8905, "orb": 8906,
                "infra": 8907, "qa-security": 8908, "tools-memory": 8909,
                "evolution-persona": 8910}
    for name, port in expected.items():
        monkeypatch.setenv("RAPHAEL_INSTANCE", name)
        assert im.instance_port() == port, name
        assert im.known_instance(), name
    monkeypatch.setenv("RAPHAEL_INSTANCE", "main")
    assert im.instance_port() == 8765


def test_raphael_port_env_wins(monkeypatch):
    monkeypatch.setenv("RAPHAEL_INSTANCE", "infra")
    monkeypatch.setenv("RAPHAEL_PORT", "9999")
    assert im.instance_port() == 9999


def test_instance_name_sanitized_for_paths_and_shell(monkeypatch):
    monkeypatch.setenv("RAPHAEL_INSTANCE", "../../etc rm -rf")
    assert im.instance_name() == "etcrm-rf"
    assert all(c.isalnum() or c in "_-" for c in im.instance_name())
    monkeypatch.setenv("RAPHAEL_INSTANCE", "!!!")
    assert im.instance_name() == "main"          # nothing left -> main


def test_unknown_instance_falls_back_to_default_port(monkeypatch):
    monkeypatch.setenv("RAPHAEL_INSTANCE", "weird-dev")
    assert not im.known_instance()
    assert im.instance_port(default=8765) == 8765   # caller default kept
    assert im.mutex_name() == "Raphael_Supervisor_weird-dev"  # still isolated


def test_wsl_data_dir(monkeypatch):
    assert im.wsl_data_dir() == "~/.raphael"
    monkeypatch.setenv("RAPHAEL_INSTANCE", "router")
    assert im.wsl_data_dir() == "~/.raphael/router"


def test_log_path_uses_supplied_root():
    root = Path("/tmp/some-root")
    assert im.log_path("brain", "main", root) == root / "logs" / "brain.log"
    assert im.log_path("brain", "orb", root) == root / "logs" / "brain_orb.log"

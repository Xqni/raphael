"""load_config + active_profile: instance overrides on top of config.yaml,
main untouched, profile source precedence (INTERFACES §c)."""
from supervisor import main as sup


def test_load_config_main_unchanged(monkeypatch):
    cfg, note = sup.load_config()
    assert cfg["instance"] == "main"
    assert cfg["paths"]["brain_port"] == 8765
    assert cfg["supervisor"]["health_url"] == "http://127.0.0.1:8765/health"
    assert "instance=main" in note


def test_load_config_instance_overrides_port_and_health(monkeypatch):
    monkeypatch.setenv("RAPHAEL_INSTANCE", "voice")
    cfg, note = sup.load_config()
    assert cfg["instance"] == "voice"
    assert cfg["paths"]["brain_port"] == 8904
    assert cfg["supervisor"]["health_url"] == "http://127.0.0.1:8904/health"
    assert "instance=voice port=8904" in note
    assert "mutex=Raphael_Supervisor_voice" in note


def test_load_config_raphael_port_env_wins(monkeypatch):
    monkeypatch.setenv("RAPHAEL_PORT", "7777")
    cfg, note = sup.load_config()
    assert cfg["paths"]["brain_port"] == 7777
    assert cfg["supervisor"]["health_url"] == "http://127.0.0.1:7777/health"


def test_load_config_unknown_instance_fails_closed(monkeypatch):
    # Wave-5 shadow readiness: an instance without a §d row AND without an
    # explicit RAPHAEL_PORT must REFUSE (old behavior: silent 8765 fallback
    # = collision with the live main instance).
    import pytest
    monkeypatch.setenv("RAPHAEL_INSTANCE", "scratch")
    with pytest.raises(ValueError, match="unknown RAPHAEL_INSTANCE"):
        sup.load_config()
    # ...but the same unknown instance with an explicit port is fine
    monkeypatch.setenv("RAPHAEL_PORT", "8911")
    cfg, note = sup.load_config()
    assert cfg["paths"]["brain_port"] == 8911
    assert "instance=scratch port=8911" in note


def test_active_profile_precedence(monkeypatch):
    cfg, _ = sup.load_config()
    # config.yaml says cloud_temp; no env
    assert sup.active_profile(cfg) == "cloud_temp"
    # config default when no profile key at all
    assert sup.active_profile({}) == "cloud_temp"
    # env wins (INTERFACES §c)
    monkeypatch.setenv("RAPHAEL_PROFILE", "local")
    assert sup.active_profile(cfg) == "local"
    # env wins even over an explicit cfg value
    assert sup.active_profile({"profile": "cloud_temp"}) == "local"

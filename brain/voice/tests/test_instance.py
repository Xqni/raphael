"""Wave 2 task 0 — instance isolation for the voice lane (AGENT_RULES §5,
docs/INTERFACES §d): every port/path this lane owns derives from
RAPHAEL_INSTANCE; unset/`main` keeps today's exact values (zero change).

Run:  brain/.venv/bin/python -m pytest brain/voice/tests -q
"""
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from brain.voice.config import (  # noqa: E402
    FISH_PORT_MAIN, LANE_INDEX, VoiceConfig, fish_port_for, instance_name,
    load_voice_config, voice_data_dir, voice_log_dir,
)


@pytest.fixture(autouse=True)
def _clean_instance_env(monkeypatch):
    monkeypatch.delenv("RAPHAEL_INSTANCE", raising=False)
    monkeypatch.delenv("RAPHAEL_FISH_PORT", raising=False)


def test_main_instance_defaults_unchanged():
    """Unset RAPHAEL_INSTANCE = main = today's exact behavior."""
    assert instance_name() == "main"
    assert fish_port_for() == 8777
    assert voice_log_dir() == _REPO / "brain" / "voice" / "logs"
    cfg = VoiceConfig()
    assert cfg.fish_port == 8777
    assert cfg.log_dir == _REPO / "brain" / "voice" / "logs"


def test_lane_instances_derive_ports_and_paths(monkeypatch):
    # voice lane = index 4 in the INTERFACES §d table -> 8777 + 4
    assert fish_port_for("voice") == 8777 + LANE_INDEX["voice"] == 8781
    assert fish_port_for("router") == 8778
    assert fish_port_for("evolution-persona") == 8777 + 10
    # ... and paths leave the shared repo dirs entirely
    assert voice_log_dir("voice") == Path.home() / ".raphael" / "voice" / "voice" / "logs"
    assert voice_data_dir("voice") == Path.home() / ".raphael" / "voice"
    monkeypatch.setenv("RAPHAEL_INSTANCE", "voice")
    assert instance_name() == "voice"
    cfg = VoiceConfig()
    assert cfg.fish_port == 8781
    assert cfg.instance == "voice"
    assert cfg.log_dir == voice_log_dir("voice")
    assert cfg.log_dir != _REPO / "brain" / "voice" / "logs"


def test_unknown_instance_never_collides():
    """Unknown names get a deterministic port that is neither the main Fish
    port (8777) nor the 8901..8910 WS range (INTERFACES §d)."""
    port = fish_port_for("some-experimental-lane")
    assert 8800 <= port <= 8876
    assert fish_port_for("some-experimental-lane") == port      # deterministic
    assert fish_port_for("voice") != port                       # no lane clash


def test_env_overrides_beat_derivation(monkeypatch):
    monkeypatch.setenv("RAPHAEL_INSTANCE", "voice")
    # direct construction derives from the instance...
    assert VoiceConfig().fish_port == 8781
    # ...while the loader honors an explicit port override (env wins, §d)
    monkeypatch.setenv("RAPHAEL_FISH_PORT", "8799")
    assert load_voice_config(_REPO / "config.yaml").fish_port == 8799


def test_yaml_and_profile_overlay_parse(monkeypatch):
    # Hermetic: another suite in the same session may have leaked
    # RAPHAEL_PROFILE/... into os.environ (brain/tests/test_config.py sets it
    # raw), so pin the env ourselves instead of trusting the process state.
    monkeypatch.delenv("RAPHAEL_PROFILE", raising=False)
    monkeypatch.delenv("RAPHAEL_STT_ENGINE", raising=False)
    cfg = load_voice_config(_REPO / "config.yaml")
    # base config.yaml: profile cloud_temp, voice.stt_engine groq, always_listen
    assert cfg.profile == "cloud_temp"
    assert cfg.stt_engine == "groq"
    assert cfg.always_listen is True
    # RAPHAEL_PROFILE=local picks the profiles.local voice overlay
    monkeypatch.setenv("RAPHAEL_PROFILE", "local")
    cfg_local = load_voice_config(_REPO / "config.yaml")
    assert cfg_local.profile == "local"
    assert cfg_local.stt_engine == "local"
    assert cfg_local.effective_stt_engine == "local"   # allowed outside cloud_temp

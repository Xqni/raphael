"""P2-adj (Wave 5P, 2026-10-09) — fish `--compile` config flag (TODO §6).

torch.compile trades a one-time warmup for faster steady-state synthesis.
The flag rides `voice.fish_compile` (default ON, user-spotted task coord
inbox 45) and the spawn must append `--compile` exactly when it is set —
never silently, never twice. Guarded here so a config regression cannot
quietly drop production onto the slow path (or force compile on a machine
whose venv predates the flag).

Run:  brain/.venv/bin/python -m pytest brain/voice/tests -q
"""
import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from brain.voice import load_voice_config  # noqa: E402
from brain.voice.tts import FishSpeechServer  # noqa: E402


def test_compile_flag_default_on():
    os.environ.pop("RAPHAEL_FISH_COMPILE", None)
    assert load_voice_config().fish_compile is True


def test_compile_flag_env_off():
    os.environ["RAPHAEL_FISH_COMPILE"] = "false"
    try:
        assert load_voice_config().fish_compile is False
    finally:
        os.environ.pop("RAPHAEL_FISH_COMPILE", None)


def test_compile_supported_by_vendored_server():
    """Probe asserts the REAL vendored tree carries --compile — but the
    vendor tree is gitignored, so a lean CI checkout must SKIP, not fail
    (the positive case runs wherever the tree exists: local + the pod)."""
    import pytest
    cfg = load_voice_config()
    utils = cfg.fish_vendor_path / "tools" / "server" / "api_utils.py"
    if not utils.exists():
        pytest.skip(f"fish vendor tree absent (lean checkout): {utils}")
    assert FishSpeechServer(cfg)._compile_supported() is True


def _fake_spawn_cfg(tmp_path):
    """Config whose _spawn() prerequisites all EXIST without the real ~2GB
    fish models — so argv construction is asserted on ANY checkout (CI
    included; models/vendor are gitignored and only exist locally)."""
    cfg = load_voice_config()
    ckpt = tmp_path / "ckpt"
    ckpt.mkdir()
    (ckpt / "firefly-gan-vq-fsq-8x1024-21hz-generator.pth").write_bytes(b"x")
    cfg.fish_checkpoint = str(ckpt)
    venv_bin = tmp_path / "venv" / "bin"
    venv_bin.mkdir(parents=True)
    (venv_bin / "python").write_text("#!/bin/sh\n")
    cfg.fish_venv = str(tmp_path / "venv")
    return cfg


def test_spawn_appends_compile_when_enabled(tmp_path):
    """_spawn's cmd gains --compile iff cfg.fish_compile (never twice)."""
    cfg = _fake_spawn_cfg(tmp_path)
    cfg.fish_compile = True
    fish = FishSpeechServer(cfg)
    cmd = _capture_cmd(fish)
    assert "--compile" in cmd
    assert cmd.count("--compile") == 1


def test_spawn_omits_compile_when_disabled(tmp_path):
    cfg = _fake_spawn_cfg(tmp_path)
    cfg.fish_compile = False
    cmd = _capture_cmd(FishSpeechServer(cfg))
    assert "--compile" not in cmd


def _capture_cmd(fish: FishSpeechServer) -> "list":
    """Run _spawn but intercept Popen so we only inspect the argv."""
    import subprocess
    captured = {}

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        class _P:
            poll = staticmethod(lambda: None)
        return _P()

    real = subprocess.Popen
    subprocess.Popen = fake_popen
    try:
        # open() for the log file must still work -> let it, Popen is faked
        fish._spawn()
    finally:
        subprocess.Popen = real
    return captured["cmd"]

"""brain/voice config loader — reads the `voice:` section of repo config.yaml.

Owned by voice-dev (brain/voice/** only). No secrets involved.
Env overrides (all optional, uppercase voice keys):
  RAPHAEL_STT_MODEL, RAPHAEL_STT_DEVICE, RAPHAEL_TTS_VOICE,
  RAPHAEL_TTS_SAMPLE_RATE, RAPHAEL_WAKE_WORD, RAPHAEL_ACK_CACHE,
  RAPHAEL_FISH_HOST, RAPHAEL_FISH_PORT, RAPHAEL_FISH_DEVICE
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

# repo root = brain/voice/config.py -> parents[2]
REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "config.yaml"


@dataclass
class VoiceConfig:
    stt_model: str = "small"
    stt_device: str = "auto"          # auto|cuda|cpu
    stt_compute: str = "auto"         # auto|float16|int8|float32
    stt_language: Optional[str] = None  # None = auto-detect
    tts_voice: str = "assets/raphael_reference.wav"
    tts_sample_rate: int = 24000
    wake_word: str = "raphael"
    ptt_hotkey: str = "ctrl+alt+space"
    ack_cache: str = "assets/acks/"
    # fish-speech server (isolated venv brain/voice/.venv-fish)
    fish_host: str = "127.0.0.1"
    fish_port: int = 8777             # NOT 8080 (avoid collisions); brain stays on 8765
    fish_device: str = "auto"         # auto|cuda|cpu for the fish server
    fish_checkpoint: str = "brain/voice/models/fish-speech-1.5"
    fish_venv: str = "brain/voice/.venv-fish"
    fish_vendor: str = "brain/voice/vendor/fish-speech"
    chunk_ms: int = 250               # speak chunk size (PROTOCOL §6 cap: 500 ms)
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def tts_voice_path(self) -> Path:
        p = Path(self.tts_voice)
        return p if p.is_absolute() else REPO_ROOT / p

    @property
    def ack_cache_path(self) -> Path:
        p = Path(self.ack_cache)
        return p if p.is_absolute() else REPO_ROOT / p

    @property
    def fish_checkpoint_path(self) -> Path:
        p = Path(self.fish_checkpoint)
        return p if p.is_absolute() else REPO_ROOT / p

    @property
    def fish_venv_python(self) -> Path:
        p = Path(self.fish_venv)
        return (p if p.is_absolute() else REPO_ROOT / p) / "bin" / "python"

    @property
    def fish_vendor_path(self) -> Path:
        p = Path(self.fish_vendor)
        return p if p.is_absolute() else REPO_ROOT / p


def _env(key: str, default: Any, cast):
    raw = os.environ.get(key)
    if raw is None or raw == "":
        return default
    try:
        return cast(raw)
    except (TypeError, ValueError):
        return default


def load_voice_config(config_path: Optional[Path] = None) -> VoiceConfig:
    path = config_path or CONFIG_PATH
    section: Dict[str, Any] = {}
    if path.exists():
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            section = dict(data.get("voice") or {})
        except (yaml.YAMError, OSError):
            section = {}
    known = {
        "stt_model", "stt_device", "tts_voice", "tts_sample_rate",
        "wake_word", "ptt_hotkey", "ack_cache",
    }
    extra = {k: v for k, v in section.items() if k not in known}
    cfg = VoiceConfig(
        stt_model=str(section.get("stt_model", "small")),
        stt_device=str(section.get("stt_device", "auto")),
        tts_voice=str(section.get("tts_voice", "assets/raphael_reference.wav")),
        tts_sample_rate=int(section.get("tts_sample_rate", 24000) or 24000),
        wake_word=str(section.get("wake_word", "raphael")),
        ptt_hotkey=str(section.get("ptt_hotkey", "ctrl+alt+space")),
        ack_cache=str(section.get("ack_cache", "assets/acks/")),
        extra=extra,
    )
    # env overrides (voice module scope; never read .env — explicit env only)
    cfg.stt_model = _env("RAPHAEL_STT_MODEL", cfg.stt_model, str)
    cfg.stt_device = _env("RAPHAEL_STT_DEVICE", cfg.stt_device, str)
    cfg.stt_compute = _env("RAPHAEL_STT_COMPUTE", cfg.stt_compute, str)
    cfg.tts_voice = _env("RAPHAEL_TTS_VOICE", cfg.tts_voice, str)
    cfg.tts_sample_rate = _env("RAPHAEL_TTS_SAMPLE_RATE", cfg.tts_sample_rate, int)
    cfg.wake_word = _env("RAPHAEL_WAKE_WORD", cfg.wake_word, str)
    cfg.ack_cache = _env("RAPHAEL_ACK_CACHE", cfg.ack_cache, str)
    cfg.fish_host = _env("RAPHAEL_FISH_HOST", cfg.fish_host, str)
    cfg.fish_port = _env("RAPHAEL_FISH_PORT", cfg.fish_port, int)
    cfg.fish_device = _env("RAPHAEL_FISH_DEVICE", cfg.fish_device, str)
    return cfg

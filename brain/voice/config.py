"""brain/voice config loader — reads the `voice:` section of repo config.yaml.

Owned by voice-dev (brain/voice/** only). No secrets involved.
Env overrides (all optional, uppercase voice keys):
  RAPHAEL_STT_MODEL, RAPHAEL_STT_DEVICE, RAPHAEL_STT_ENGINE, RAPHAEL_PROFILE,
  RAPHAEL_TTS_VOICE, RAPHAEL_TTS_SAMPLE_RATE, RAPHAEL_WAKE_WORD,
  RAPHAEL_ACK_CACHE, RAPHAEL_FISH_HOST, RAPHAEL_FISH_PORT, RAPHAEL_FISH_DEVICE

Instance isolation (AGENT_RULES §5, INTERFACES §d): every port/path this lane
owns derives from RAPHAEL_INSTANCE — unset/`main` keeps today's exact values.
"""
from __future__ import annotations

import os
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

# repo root = brain/voice/config.py -> parents[2]
REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "config.yaml"

# ---- instance derivation (INTERFACES §d) -----------------------------------
# Lane index order mirrors the §d table (8900 + index = WS port). Only used to
# derive THIS lane's own resources (Fish port, voice log dir) — lanes never
# bind the WS port themselves (that is brain/run.py, infra's file).
LANE_INDEX: Dict[str, int] = {
    "main": 0, "router": 1, "brain-core": 2, "pc-control": 3, "voice": 4,
    "computer-use": 5, "orb": 6, "infra": 7, "qa-security": 8,
    "tools-memory": 9, "evolution-persona": 10,
}
FISH_PORT_MAIN = 8777        # reserved for the real stack (INTERFACES §d note)
_UNKNOWN_PORT_BASE = 8800    # unknown instances -> 8800..8876 (never 8777,
_UNKNOWN_PORT_SPAN = 77      # never the 8901..8910 WS range)


def instance_name() -> str:
    """Current instance ('' / unset -> 'main' = zero behavior change)."""
    return (os.environ.get("RAPHAEL_INSTANCE") or "").strip() or "main"


def is_main_instance() -> bool:
    return instance_name() == "main"


def fish_port_for(instance: Optional[str] = None) -> int:
    """Fish TTS port for this instance: main=8777, lane=8777+index (8778-8787),
    unknown instance name -> deterministic 8800-8876 (never the main port,
    never the WS port range). Explicit RAPHAEL_FISH_PORT always wins."""
    name = instance if instance is not None else instance_name()
    if name == "main":
        return FISH_PORT_MAIN
    idx = LANE_INDEX.get(name)
    if idx is not None:
        return FISH_PORT_MAIN + idx
    return _UNKNOWN_PORT_BASE + zlib.crc32(name.encode("utf-8")) % _UNKNOWN_PORT_SPAN


def voice_data_dir(instance: Optional[str] = None) -> Path:
    """~/.raphael/ for main (today's layout), ~/.raphael/<instance>/ otherwise
    (INTERFACES §d data-dir column)."""
    name = instance if instance is not None else instance_name()
    home = Path.home() / ".raphael"
    return home if name == "main" else home / name


def voice_log_dir(instance: Optional[str] = None) -> Path:
    """Where this lane's runtime logs (fish_server.log) go: main keeps the
    in-repo brain/voice/logs/ (today's behavior); other instances use their
    own data-dir so two instances never tail/append the same file."""
    name = instance if instance is not None else instance_name()
    if name == "main":
        return REPO_ROOT / "brain" / "voice" / "logs"
    return voice_data_dir(name) / "voice" / "logs"


@dataclass
class VoiceConfig:
    profile: str = "cloud_temp"       # RAPHAEL_PROFILE -> config `profile:` -> default
    stt_engine: str = "groq"          # groq|local — profile cloud_temp FORCES groq
    stt_model: str = "small"
    stt_device: str = "auto"          # auto|cuda|cpu
    stt_compute: str = "auto"         # auto|float16|int8|float32
    stt_language: Optional[str] = None  # None = auto-detect
    tts_voice: str = "assets/raphael_reference_jp.wav"
    tts_voice_ciel: str = "assets/ciel_reference.wav"   # evolution-persona
    #  tier slot (docs/evolution/02-persona-tiers.md §5) — missing file falls
    #  back to tts_voice (the JP great-sage ref) + one-time notice, never a
    #  default voice (user directive / Bug D).
    tts_voice_raphael: str = ""        # optional raphael-tier slot (empty =
    #  keep the current reference, per the tier table)
    tts_reference_required: bool = True   # USER DIRECTIVE (Bug D): never
    #  synthesize without the configured reference — no default/Zira voice ever
    persona_tier: str = "great_sage"       # great_sage|raphael|ciel (fail-closed)
    tts_sample_rate: int = 24000
    spoken_max_sentences: int = 2          # voice_personality
    #  spoken_reply_max_sentences: cap on what is SPOKEN (screen carries the rest)
    wake_word: str = "raphael"
    ptt_hotkey: str = "ctrl+alt+space"
    always_listen: bool = True        # false = PTT-only (hotkey fallback)
    ack_cache: str = "assets/acks/"
    # fish-speech server (isolated venv brain/voice/.venv-fish)
    fish_host: str = "127.0.0.1"
    fish_port: int = field(default_factory=fish_port_for)  # derived, INTERFACES §d
    fish_device: str = "auto"         # auto|cuda|cpu for the fish server
    fish_checkpoint: str = "brain/voice/models/fish-speech-1.5"
    fish_venv: str = "brain/voice/.venv-fish"
    fish_vendor: str = "brain/voice/vendor/fish-speech"
    chunk_ms: int = 250               # speak chunk size (PROTOCOL §6 cap: 500 ms)
    extra: Dict[str, Any] = field(default_factory=dict)

    # -- persona-tier voice profile (Wave 5) --------------------------------
    def tier_voice_path(self) -> "tuple":
        """Resolve (path, fallback_note) for the effective persona tier.

        great_sage / raphael -> `voice.tts_voice` (the current, user-approved
        JP great-sage reference — the raphael tier keeps 'the current voice'
        per docs/evolution/02-persona-tiers.md tier table); ciel -> its own
        slot (`voice.tts_voice_ciel`). A missing SLOT falls back to tts_voice
        with a note (the caller logs/subtitles it once) — never a default
        voice (user directive / Bug D); when even tts_voice is missing the
        note is None and Bug D's loud gate fires.
        """
        base = Path(self.tts_voice)
        base = base if base.is_absolute() else REPO_ROOT / base
        slot_rel = {"ciel": self.tts_voice_ciel,
                    "raphael": self.tts_voice_raphael}.get(self.persona_tier, "")
        if not slot_rel:
            return base, None                      # great_sage / empty slot
        slot = Path(slot_rel)
        slot = slot if slot.is_absolute() else REPO_ROOT / slot
        try:
            ok = slot.exists() and slot.stat().st_size > 0
        except OSError:
            ok = False
        if ok:
            return slot, None
        return base, (f"tier '{self.persona_tier}' voice slot missing ({slot}) "
                      f"— using the current reference ({base})")

    @property
    def reference_path(self) -> Path:
        """Tier-resolved reference path (what synthesis actually sends)."""
        return self.tier_voice_path()[0]

    # -- instance-derived paths (never hardcoded) ---------------------------
    @property
    def instance(self) -> str:
        return instance_name()

    @property
    def log_dir(self) -> Path:
        return voice_log_dir()

    @property
    def local_stt_enabled(self) -> bool:
        """faster-whisper is allowed ONLY outside profile cloud_temp
        (WAVES.md: local model code paths stay, but are disabled here)."""
        return self.profile != "cloud_temp"

    @property
    def effective_stt_engine(self) -> str:
        """cloud_temp -> always the cloud engine; otherwise config's choice."""
        if not self.local_stt_enabled:
            return "groq"
        return (self.stt_engine or "groq").strip().lower() or "groq"

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


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("1", "true", "yes", "on"):
            return True
        if v in ("0", "false", "no", "off"):
            return False
    return default


def _as_bool_raw(value: str) -> bool:
    return _as_bool(value, False)


def _load_persona_tier(data: Dict[str, Any]) -> str:
    """Effective persona tier for tier-scoped voice profiles (Wave 5).

    Source order: RAPHAEL_PERSONA_TIER (explicit/test) -> `persona.tier` in a
    merged config (`data`) -> the evolution-persona lane's fragment
    config.d/evolution-persona.yaml (read-only, we never edit it). Unknown /
    missing fails CLOSED to great_sage — same rule as their tier_of().

    The tier cannot raise itself (addendum §14 / design 01 §6 rule 1): a diff
    that changes it is a proposal, never an auto-promote.
    """
    tier = (os.environ.get("RAPHAEL_PERSONA_TIER") or "").strip()
    if not tier:
        tier = str((((data or {}).get("persona") or {}).get("tier")) or "")
    if not tier:
        frag = REPO_ROOT / "config.d" / "evolution-persona.yaml"
        try:
            if frag.exists():
                d = yaml.safe_load(frag.read_text(encoding="utf-8")) or {}
                tier = str((((d or {}).get("persona") or {}).get("tier")) or "")
        except (yaml.YAMError, OSError):
            tier = ""
    return tier if tier in ("great_sage", "raphael", "ciel") else "great_sage"


def load_voice_config(config_path: Optional[Path] = None) -> VoiceConfig:
    path = config_path or CONFIG_PATH
    section: Dict[str, Any] = {}
    data: Dict[str, Any] = {}
    profile = "cloud_temp"
    if path.exists():
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (yaml.YAMLError, OSError):
            data = {}
        section = dict(data.get("voice") or {})
        # profile source: RAPHAEL_PROFILE wins (INTERFACES §c) — resolved
        # BEFORE the overlay merge so the overlay picked is the effective one
        profile = _env("RAPHAEL_PROFILE",
                       str(data.get("profile") or "cloud_temp"), str)
        # profile overlay (INTERFACES §c): profiles.<profile>.voice merges over
        # the base voice section (profiles.local.voice = {stt_engine: local}).
        overlays = data.get("profiles")
        overlay = None
        if isinstance(overlays, dict) and isinstance(overlays.get(profile), dict):
            overlay = overlays[profile].get("voice")
        if isinstance(overlay, dict):
            section = {**section, **overlay}
    profile = _env("RAPHAEL_PROFILE", profile, str)   # idempotent; covers missing-file path
    known = {
        "profile", "stt_engine", "stt_model", "stt_device", "stt_compute",
        "stt_language", "tts_voice", "tts_voice_ciel", "tts_voice_raphael",
        "persona_tier", "tts_reference_required",
        "tts_sample_rate", "wake_word",
        "ptt_hotkey", "always_listen", "ack_cache", "chunk_ms",
        "fish_host", "fish_port", "fish_device", "fish_checkpoint",
        "fish_venv", "fish_vendor",
    }
    extra = {k: v for k, v in section.items() if k not in known}
    vp = data.get("voice_personality") or {}
    cfg = VoiceConfig(
        profile=profile,
        stt_engine=str(section.get("stt_engine", "groq")),
        stt_model=str(section.get("stt_model", "small")),
        stt_device=str(section.get("stt_device", "auto")),
        stt_language=(str(section.get("stt_language")).strip() or None)
        if section.get("stt_language") else None,  # BUG-H fix: key was parsed
        # into `known` but never wired — stt_language silently stayed None,
        # whisper auto-detect mislabeled the wake word under the JP voice.
        tts_voice=str(section.get("tts_voice", "assets/raphael_reference_jp.wav")),
        tts_voice_ciel=str(section.get("tts_voice_ciel",
                                        "assets/ciel_reference.wav")),
        tts_voice_raphael=str(section.get("tts_voice_raphael", "")),
        persona_tier=_load_persona_tier(data),
        tts_reference_required=_as_bool(section.get("tts_reference_required",
                                                     True), True),
        tts_sample_rate=int(section.get("tts_sample_rate", 24000) or 24000),
        spoken_max_sentences=int(vp.get("spoken_reply_max_sentences", 2) or 2),
        wake_word=str(section.get("wake_word", "raphael")),
        ptt_hotkey=str(section.get("ptt_hotkey", "ctrl+alt+space")),
        always_listen=_as_bool(section.get("always_listen", True), True),
        ack_cache=str(section.get("ack_cache", "assets/acks/")),
        fish_host=str(section.get("fish_host", "127.0.0.1")),
        fish_port=int(section.get("fish_port") or fish_port_for()),
        fish_device=str(section.get("fish_device", "auto")),
        chunk_ms=int(section.get("chunk_ms", 250) or 250),
        extra=extra,
    )
    # env overrides (voice module scope; never read .env -- explicit env only)
    cfg.stt_engine = _env("RAPHAEL_STT_ENGINE", cfg.stt_engine, str)
    cfg.stt_model = _env("RAPHAEL_STT_MODEL", cfg.stt_model, str)
    cfg.stt_device = _env("RAPHAEL_STT_DEVICE", cfg.stt_device, str)
    cfg.stt_compute = _env("RAPHAEL_STT_COMPUTE", cfg.stt_compute, str)
    cfg.tts_voice = _env("RAPHAEL_TTS_VOICE", cfg.tts_voice, str)
    cfg.tts_reference_required = _env("RAPHAEL_TTS_REFERENCE_REQUIRED",
                                      cfg.tts_reference_required, _as_bool_raw)
    cfg.tts_sample_rate = _env("RAPHAEL_TTS_SAMPLE_RATE", cfg.tts_sample_rate, int)
    cfg.wake_word = _env("RAPHAEL_WAKE_WORD", cfg.wake_word, str)
    cfg.ack_cache = _env("RAPHAEL_ACK_CACHE", cfg.ack_cache, str)
    cfg.fish_host = _env("RAPHAEL_FISH_HOST", cfg.fish_host, str)
    cfg.fish_port = _env("RAPHAEL_FISH_PORT", cfg.fish_port, int)
    cfg.fish_device = _env("RAPHAEL_FISH_DEVICE", cfg.fish_device, str)
    cfg.always_listen = _env("RAPHAEL_ALWAYS_LISTEN", cfg.always_listen,
                             _as_bool_raw)
    return cfg

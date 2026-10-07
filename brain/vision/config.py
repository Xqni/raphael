"""Config loader for the cloud-vision gate + computer-use loop.

Reads `vision:`, `privacy:`, `jobs:` and `profile` from the repo config using
the INTERFACES §(c) load order (config.yaml base → config.d/*.yaml sorted,
deep-merge → active profile overlay; profile source: RAPHAEL_PROFILE env wins
→ top-level `profile:` → default `cloud_temp`). Mirrors the voice loader
pattern (brain/voice/config.py). No secrets here — `.env` only.

If brain-core's central loader lands later, wiring.py can be pointed at it;
the dataclass shape below is what the gate consumes.
"""
from __future__ import annotations

import copy
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]      # brain/vision/config.py -> repo root
CONFIG_PATH = REPO_ROOT / "config.yaml"
CONFIG_D = REPO_ROOT / "config.d"

DEFAULT_PROFILE = "cloud_temp"


def _deep_merge(base: Dict[str, Any], over: Dict[str, Any]) -> Dict[str, Any]:
    """INTERFACES §(c): mappings merge recursively; lists/scalars replace."""
    out: Dict[str, Any] = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_raw(config_path: Optional[Path] = None) -> Dict[str, Any]:
    """Merged raw config tree (base + config.d + profile overlay)."""
    path = Path(config_path) if config_path else CONFIG_PATH
    merged: Dict[str, Any] = {}
    if path.is_file():
        loaded = yaml.safe_load(path.read_text()) or {}
        if isinstance(loaded, dict):
            merged = loaded
    # config.d fragments, sorted by filename, deep-merged over the base
    d = path.parent / "config.d" if path.parent == REPO_ROOT else CONFIG_D
    if d.is_dir():
        for frag in sorted(d.glob("*.yaml")):
            try:
                data = yaml.safe_load(frag.read_text()) or {}
            except (OSError, yaml.YAMLError):
                continue          # a broken foreign fragment must not kill the gate
            if isinstance(data, dict):
                merged = _deep_merge(merged, data)
    # active profile overlay (INTERFACES §c)
    profile = os.environ.get("RAPHAEL_PROFILE") or merged.get("profile") or DEFAULT_PROFILE
    overlay = (merged.get("profiles") or {}).get(profile) or {}
    if isinstance(overlay, dict) and overlay:
        merged = _deep_merge(merged, overlay)
    merged["_profile"] = profile
    return merged


@dataclass(frozen=True)
class VisionConfig:
    """Effective settings for PROTOCOL §7 gates + the computer-use loop."""
    profile: str = DEFAULT_PROFILE
    provider: str = "cloud"            # vision.provider
    max_px: int = 1280                 # vision.max_px  (downscale before any cloud send)
    quality: int = 70                  # vision.quality
    blocklist_apps: Tuple[str, ...] = ()   # privacy.blocklist_apps
    redact: Tuple[str, ...] = ()           # privacy.redact
    debug_capture: bool = False            # privacy.debug_capture (MUST stay false)
    watch_mode: bool = False               # privacy.watch_mode (off by default)
    gui_steps_cap: int = 25                # jobs.gui_steps_cap

    @property
    def cloud_allowed(self) -> bool:
        """PROTOCOL §7: cloud vision is legal ONLY under profile cloud_temp."""
        return self.profile == "cloud_temp"


def _as_tuple(value: Any) -> Tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(str(v) for v in value)
    return ()


def load_config(path: Optional[Path] = None) -> VisionConfig:
    raw = load_raw(path)
    vision = raw.get("vision") or {}
    privacy = raw.get("privacy") or {}
    jobs = raw.get("jobs") or {}
    try:
        max_px = int(vision.get("max_px", 1280))
    except (TypeError, ValueError):
        max_px = 1280
    try:
        quality = int(vision.get("quality", 70))
    except (TypeError, ValueError):
        quality = 70
    try:
        cap = int(jobs.get("gui_steps_cap", 25))
    except (TypeError, ValueError):
        cap = 25
    return VisionConfig(
        profile=str(raw.get("_profile") or DEFAULT_PROFILE),
        provider=str(vision.get("provider", "cloud")),
        max_px=max_px,
        quality=quality,
        blocklist_apps=_as_tuple(privacy.get("blocklist_apps")),
        redact=_as_tuple(privacy.get("redact")),
        debug_capture=bool(privacy.get("debug_capture", False)),
        watch_mode=bool(privacy.get("watch_mode", False)),
        gui_steps_cap=max(1, cap),
    )

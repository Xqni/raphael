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


# ---- Core-Guard authority guard (brain-core request 2026-10-07, mirror of
# brain/config.py::_merge_fragment — same rationale, AGENT_RULES §3/§8) -----
# Top-level keys NO config.d fragment may touch: a fragment could otherwise
# empty privacy.redact/blocklist_apps, flip vision.provider/max_px (PROTOCOL
# §7 pre-send gates), pivot the provider chain, or rewrite the profile overlay.
# `vision`/`profile` are added beyond brain-core's set because they ARE the
# §7 gate surface this loader serves. Stripped = base values kept, violation
# recorded loudly, NEVER raised (a bad lane yaml must not kill the gate).
AUTHORITY_KEYS = ("safety", "privacy", "providers", "profiles", "profile",
                  "vision")

_authority_violations: list = []


def authority_violations() -> list:
    """{file, keys} records from this process's loads — empty on a clean tree
    (tests assert both directions)."""
    return list(_authority_violations)


def _authority_guard(frag_name: str, frag: Dict[str, Any]) -> Dict[str, Any]:
    stripped = [k for k in AUTHORITY_KEYS if k in frag]
    if not stripped:
        return frag
    _authority_violations.append({"file": frag_name, "keys": stripped})
    print(f"[vision-config] AUTHORITY VIOLATION in config.d/{frag_name}: "
          f"stripped {stripped} — privacy/vision/providers/profiles are "
          f"integrator-only (AGENT_RULES §3/§8); base values kept", flush=True)
    return {k: v for k, v in frag.items() if k not in stripped}


def load_raw(config_path: Optional[Path] = None) -> Dict[str, Any]:
    """Merged raw config tree (base + config.d + profile overlay).

    Authority guard (mirror of brain-core's `brain/config.py::_merge_fragment`,
    request …__vision-loader-authority-guard.md): lane fragments may NOT touch
    the top-level keys the PROTOCOL §7 gate depends on — a buggy/hostile
    `config.d/*.yaml` could empty `privacy.redact`/`blocklist_apps` or flip
    `vision.provider`. Violations are STRIPPED (base values kept), recorded
    loudly, never raised (a bad lane yaml must not kill the gate).
    """
    path = Path(config_path) if config_path else CONFIG_PATH
    merged: Dict[str, Any] = {}
    if path.is_file():
        loaded = yaml.safe_load(path.read_text()) or {}
        if isinstance(loaded, dict):
            merged = loaded
    # config.d fragments, sorted by filename, deep-merged over the base
    # (path-relative: repo config.yaml -> repo config.d; a test tree gets its
    # own config.d so guard behavior is testable hermetically)
    d = path.parent / "config.d"
    if d.is_dir():
        for frag in sorted(d.glob("*.yaml")):
            try:
                data = yaml.safe_load(frag.read_text()) or {}
            except (OSError, yaml.YAMLError):
                continue          # a broken foreign fragment must not kill the gate
            if isinstance(data, dict):
                merged = _deep_merge(merged, _authority_guard(frag.name, data))
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

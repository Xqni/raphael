"""Persona tier handling (Wave 5 design: docs/evolution/02-persona-tiers.md).

Tier is a CONFIG value (`persona.tier` in config.d/evolution-persona.yaml),
never a model decision: the model cannot self-grant a tier (addendum §14) and
the evolution controller treats a diff that raises it as a proposal, never an
auto-promote (design 01 §6 rule 1).

Per-tier `voice_personality` overlays ride the standard config.d deep-merge
(INTERFACES §c — mappings merge, lists/scalars replace), so switching tiers
never edits the integrator-owned config.yaml. `great_sage` is by definition
the tier that changes nothing (no overlay).
"""
from __future__ import annotations

from typing import Any, Dict

TIERS = ("great_sage", "raphael", "ciel")

# Keys a tier overlay is allowed to touch — everything else in
# voice_personality stays exactly as config.yaml sets it.
OVERLAY_KEYS = frozenset({
    "character", "style", "speech_forms", "banned",
    "spoken_reply_max_sentences", "proactive_warnings",
})


def tier_of(cfg: Dict[str, Any]) -> str:
    """Effective tier, normalized; unknown/missing values fail closed to great_sage."""
    t = (cfg.get("persona") or {}).get("tier")
    return t if t in TIERS else "great_sage"


def is_unlocked(cfg: Dict[str, Any], tier: str) -> bool:
    return tier in TIERS and tier_of(cfg) == tier

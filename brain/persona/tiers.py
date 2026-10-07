"""Persona tier handling (Wave 5: docs/evolution/02-persona-tiers.md).

Tier is a CONFIG value (`persona.tier` in config.d/evolution-persona.yaml),
never a model decision: the model cannot self-grant a tier (addendum §14) and
the evolution controller treats a diff that raises it as a proposal, never an
auto-promote (design 01 §6 rule 1).

Per-tier `voice_personality` overlays ride the standard config.d deep-merge
(INTERFACES §c — mappings merge, lists/scalars replace), so switching tiers
never edits the integrator-owned config.yaml. `great_sage` is by definition
the tier that changes nothing (no overlay).

AUTONOMY (design 02 §2) is deny-by-default: a proactive job class runs only if
its tier lists it explicitly. Money, secrets, network-write/publish, deletes
and arbitrary shell are not in ANY list — "may add capabilities but never
authority" (addendum §14).
"""
from __future__ import annotations

from typing import Any, Dict, FrozenSet

TIERS = ("great_sage", "raphael", "ciel")

# Keys a tier overlay is allowed to touch — everything else in
# voice_personality stays exactly as config.yaml sets it.
OVERLAY_KEYS = frozenset({
    "character", "style", "speech_forms", "banned",
    "spoken_reply_max_sentences", "proactive_warnings",
})

# ---- proactive autonomy zones (design 02 §2) -------------------------------
# great_sage: proposes only. raphael: small SAFE zone. ciel: broader EARNED zone.
_PROACTIVE_RAPHAEL = frozenset({
    "notice",            # proactive surfacing (Wave-3 notice frame)
    "reminder",          # timers/reminders she scheduled herself
    "status_check",      # read-only health/job checks (the §10 behavioural signature)
    "memory_maintenance",# skill draft/dedup housekeeping (existing gates apply)
})
_PROACTIVE_CIEL = _PROACTIVE_RAPHAEL | frozenset({
    "file_analysis",     # read-only Analysis jobs over user-approved paths
    "web_research",      # bounded research (step-budgeted)
    "digest",            # periodic summaries of her own journals/logs
    "schedule_scan",     # read-only schedule conflict checks
    "summarize",         # on-demand summarization of already-owned content
})

PROACTIVE_ZONE: Dict[str, FrozenSet[str]] = {
    "great_sage": frozenset(),
    "raphael": _PROACTIVE_RAPHAEL,
    "ciel": _PROACTIVE_CIEL,
}


def tier_of(cfg: Dict[str, Any]) -> str:
    """Effective tier, normalized; unknown/missing values fail closed to great_sage."""
    t = (cfg.get("persona") or {}).get("tier")
    return t if t in TIERS else "great_sage"


def is_unlocked(cfg: Dict[str, Any], tier: str) -> bool:
    return tier in TIERS and tier_of(cfg) == tier


def zone_of(cfg: Dict[str, Any]) -> FrozenSet[str]:
    """Proactive job classes this config's tier may start on its own."""
    return PROACTIVE_ZONE[tier_of(cfg)]


def can_start_proactive(cfg: Dict[str, Any], job_class: str) -> bool:
    """Deny-by-default: unknown classes, and any class not explicitly listed
    for the CURRENT tier, are refused. Never raises — False is the answer."""
    return job_class in PROACTIVE_ZONE[tier_of(cfg)]


def is_demotion(current: str, new: str) -> bool:
    """Runtime/automatic tier changes may only LOWER autonomy (fail-safe).
    Raising a tier is always a user-approved proposal (design 02 §2.1)."""
    if current not in TIERS or new not in TIERS:
        return False
    return TIERS.index(new) < TIERS.index(current)


# ---- unlock criteria (design 02 §2.1, evaluated never applied) -------------
# Every criterion is machine-checkable; `user_approval` is NEVER auto-met —
# `ready` means "eligible for a proposal", not "switch now".
def evaluate_unlock(stats: Dict[str, Any], to_tier: str) -> Dict[str, Any]:
    """Evaluate unlock criteria for `to_tier` from observed stats:
      days_since_sev1, tests_green, job_success_rate, confirm_timeouts,
      days_stable, failed_probations, rollbacks, user_approval (always False
      unless the caller carries an explicit recorded approval).
    Returns {'to_tier','ready','met','unmet'} — read-only, no side effects."""
    if to_tier not in TIERS or to_tier == "great_sage":
        return {"to_tier": to_tier, "ready": False, "met": [],
                "unmet": ["great_sage is the default (no unlock)"]
                if to_tier == "great_sage" else [f"unknown tier {to_tier!r}"]}

    checks = {
        "raphael": [
            ("7+ days since last severity-1 failure",
             stats.get("days_since_sev1", 0) >= 7),
            ("test suite green at last-known-good",
             bool(stats.get("tests_green"))),
            ("job success rate >= 95%",
             float(stats.get("job_success_rate", 0.0)) >= 0.95),
            ("zero unhandled confirm timeouts",
             int(stats.get("confirm_timeouts", 0)) == 0),
            ("user approval", bool(stats.get("user_approval"))),
        ],
        "ciel": [
            ("30+ days stable on the current tier",
             stats.get("days_stable", 0) >= 30),
            ("every auto-promoted change probation passed",
             int(stats.get("failed_probations", 1)) == 0),
            ("zero rollbacks in the window",
             int(stats.get("rollbacks", 0)) == 0),
            ("user approval", bool(stats.get("user_approval"))),
        ],
    }[to_tier]

    met = [name for name, ok in checks if ok]
    unmet = [name for name, ok in checks if not ok]
    auto_ready = all(ok for name, ok in checks if name != "user approval")
    return {"to_tier": to_tier, "ready": auto_ready, "met": met, "unmet": unmet}

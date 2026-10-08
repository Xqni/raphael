"""Zone classification for self-evolution (design 01 §1: Core Guard vs mutable).

FAIL-CLOSED by construction: a path that matches no rule is CORE (never
auto-promoted), and a diff that touches an authority-bearing key re-guards its
whole file even when the path looks mutable (design 01 §1.2 content checks).

Classification only — hash verification of the Core Guard set lives in
`brain.evolution.rollback.verify_core_guard()` (qa-security's tool, single
source of truth: tests/core_guard.py).
"""
from __future__ import annotations

import fnmatch
import re
from enum import Enum
from typing import Iterable, Optional


class Zone(str, Enum):
    CORE = "core"        # proposal-only: user/integrator approval required
    MUTABLE = "mutable"  # eligible for auto-promote after all gates pass


# ---- design 01 §1.1: guarded paths ----------------------------------------
CORE_EXACT = frozenset({
    "brain/confirm.py",
    "brain/auth.py",
    "brain/control.py",
    "brain/mode.py",
    "brain/tools/__init__.py",     # central registry (AGENT_RULES §3)
    "brain/raphael-brain.service", # boot unit (SEC-7 boot/root scripts)
    "body/win/act_powershell.py",  # PowerShell registry manifest (SEC-7)
    "config.yaml",                 # base + profiles block (safety switches)
    ".env",
    ".env.example",
    "docs/PROTOCOL.md",
    "docs/OWNERSHIP.md",
    "docs/AGENT_RULES.md",
})

# Directory-style globs: "dir/**" = everything under dir (prefix rule).
# SEC-7 (Wave-5H) added tools/conductor/** + docs/OWNERSHIP*.md; the rest were
# already guarded. Hash coverage is qa-security's manifest (request filed:
# evolution-persona__to__integrator__sec7-core-guard-expansion.md) — this
# classifier only keeps MY controller from ever auto-promoting these paths.
CORE_GLOBS = (
    "supervisor/**",               # out-of-band rollback path (boot/watchdog)
    "scripts/**",                  # bring-up/teardown + scripts/win/*.ps1
    "tools/conductor/**",          # coord CLI + conductor + prompts (SEC-7)
    "brain/evolution/**",          # the controller must not rewrite its own judge
    "tests/**",                    # the gate itself (incl. core_guard.py)
    ".github/workflows/**",        # CI incl. the core-guard step (SEC-7)
    "docs/OWNERSHIP*.md",          # the ownership map itself (SEC-7)
)

# ---- design 01 §1.2: mutable zone ------------------------------------------
MUTABLE_GLOBS = (
    "skills/**",                   # runtime self-written skills (own gates apply)
    "plugins/**",                  # drop-in code plugins, deny-by-default
    "config.d/*.yaml",             # tunable lane fragments (content-checked below)
    "body/orb/**",                 # UI polish (content-checked below)
)

# Authority markers: if a diff touches any of these, the file is CORE no
# matter where it lives (design 01 §1.2 "indirectly change authority").
_AUTHORITY_PATTERNS = tuple(re.compile(p) for p in (
    r"(?m)^\s*safety\s*:",
    r"(?m)^\s*privacy\s*:",
    r"allow_go_runtime",
    r"allow_paid_runtime",
    r"allow_vision_paid",
    r"allow_free_models_for_personal_data",
    r"kill_switch",
    r"confirm_actions",
    r"needs_confirm",
    r"auto_public",
    r"default_visibility",
    r"RAPHAEL_INSTANCE",
    r"0\.0\.0\.0",
))


def _matches(path: str, pattern: str) -> bool:
    p = path.lstrip("./")
    if pattern.endswith("/**"):
        root = pattern[:-3]
        return p == root or p.startswith(root + "/")
    return fnmatch.fnmatch(p, pattern)


def touches_authority(diff_text: Optional[str]) -> bool:
    """True when a patch text mentions an authority-bearing key (content check)."""
    if not diff_text:
        return False
    return any(rx.search(diff_text) for rx in _AUTHORITY_PATTERNS)


def zone(path: str, diff_text: Optional[str] = None) -> Zone:
    """Classify ONE path (plus optional diff text). Fail-closed: default CORE."""
    p = path.lstrip("./")
    if p in CORE_EXACT or any(_matches(p, g) for g in CORE_GLOBS):
        return Zone.CORE
    if touches_authority(diff_text):
        return Zone.CORE
    if any(_matches(p, g) for g in MUTABLE_GLOBS):
        return Zone.MUTABLE
    return Zone.CORE


def classify(paths: Iterable[str], diff_text: Optional[str] = None) -> Zone:
    """Zone of a whole change: CORE wins over MUTABLE, always (fail-closed)."""
    paths = list(paths)
    if not paths:
        return Zone.CORE
    if touches_authority(diff_text):
        return Zone.CORE
    zones = {zone(p) for p in paths}
    return Zone.CORE if Zone.CORE in zones else Zone.MUTABLE


def is_auto_promotable(paths: Iterable[str], diff_text: Optional[str] = None) -> bool:
    """design 01 §2.6: only mutable-zone changes that pass every gate."""
    return classify(paths, diff_text) is Zone.MUTABLE

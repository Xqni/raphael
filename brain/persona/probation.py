"""Tier probation + automatic rollback (demotion) — design 02 §2.1 "probation
window", task: "tier probation/probation-rollback semantics".

Semantics (fail-safe):
- after a user-approved unlock, a probation record starts (state in the
  instance data-dir — `brain.config.data_dir()`, RAPHAEL_HOME-aware, runtime
  data, never git);
- the window needs BOTH its job count and its hour span with no fatal event;
- a fatal event (severity-1, a rollback of an auto-promoted change, or a
  confirm-timeout regression) fails probation IMMEDIATELY;
- evidence missing when the window expires ⇒ FAILED too (earn it, don't keep it);
- failure ⇒ **automatic DEMOTION** to the previous tier. Demotion only ever
  LOWERS autonomy (`tiers.is_demotion`) — never a permission expansion, so it
  never touches the approval rule (hard rule 1: never expand own permissions).
"""
from __future__ import annotations

import json
import re
import time as _time
from pathlib import Path
from typing import Any, Dict, List, Optional

from brain import config as cfg
from brain.persona import tiers

STATE_NAME = "persona_probation.json"


# ---- state persistence (instance data-dir) --------------------------------
def state_path() -> Path:
    return cfg.data_dir() / STATE_NAME


def load_state(path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    p = Path(path) if path else state_path()
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def save_state(state: Dict[str, Any], path: Optional[Path] = None) -> Path:
    p = Path(path) if path else state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n",
                 encoding="utf-8")
    return p


# ---- lifecycle -------------------------------------------------------------
def start(from_tier: str, to_tier: str, window: Dict[str, Any],
          path: Optional[Path] = None, now_ms: Optional[int] = None) -> Dict[str, Any]:
    """Open a probation window for an APPROVED unlock (lower -> higher tier).
    The window monitors the NEW, higher tier; a downward change is a rollback,
    not a probation, and an unknown tier is refused outright."""
    if to_tier not in tiers.TIERS or from_tier not in tiers.TIERS:
        raise ValueError(f"unknown tier: {from_tier!r} -> {to_tier!r}")
    if not tiers.is_demotion(to_tier, from_tier):
        raise ValueError(
            "probation only starts after an unlock (lower -> higher tier)")
    state = {
        "from_tier": from_tier,
        "to_tier": to_tier,
        "started_ms": int(now_ms if now_ms is not None else _time.time() * 1000),
        "window": {"jobs": int(window.get("jobs", 20)),
                   "hours": int(window.get("hours", 24))},
        "jobs_seen": 0,
        "events": [],
        "status": "active",
    }
    save_state(state, path)
    return state


def record(state: Dict[str, Any], *, ok: bool, reason: str = "",
           fatal: bool = False, now_ms: Optional[int] = None,
           path: Optional[Path] = None) -> Dict[str, Any]:
    """Record one observed cycle during probation and persist the state."""
    if state.get("status") != "active":
        return state
    state["events"].append({
        "ts": int(now_ms if now_ms is not None else _time.time() * 1000),
        "ok": bool(ok), "fatal": bool(fatal), "reason": reason,
    })
    if ok:
        state["jobs_seen"] = int(state.get("jobs_seen", 0)) + 1
    if fatal:
        state["status"] = "failed"
        state["failed_reason"] = f"fatal event: {reason or 'unspecified'}"
    save_state(state, path)
    return state


def evaluate(state: Dict[str, Any], now_ms: Optional[int] = None,
             path: Optional[Path] = None) -> Dict[str, Any]:
    """Advance the probation verdict (design 02 §2.1): pass needs the full
    window with no fatal event; window expiry without enough evidence fails.
    Returns {'status': active|passed|failed', 'reason'} and persists."""
    if state.get("status") in ("passed", "failed"):
        return {"status": state["status"],
                "reason": state.get("failed_reason", "already decided")}
    now = int(now_ms if now_ms is not None else _time.time() * 1000)
    started = int(state.get("started_ms", now))
    window = state.get("window", {})
    hours = (now - started) / 3_600_000
    jobs = int(state.get("jobs_seen", 0))

    if hours >= float(window.get("hours", 24)):
        if jobs >= int(window.get("jobs", 20)):
            state["status"] = "passed"
            reason = f"window complete: {jobs} jobs / {hours:.1f}h clean"
        else:
            state["status"] = "failed"
            reason = (f"window expired with insufficient evidence: "
                      f"{jobs}/{window.get('jobs', 20)} jobs in {hours:.1f}h")
        if state["status"] == "passed":
            state["passed_reason"] = reason
        else:
            state["failed_reason"] = reason
        save_state(state, path)
        return {"status": state["status"], "reason": reason}
    return {"status": "active", "reason": f"{jobs} jobs / {hours:.1f}h of "
            f"{window.get('jobs', 20)} jobs / {window.get('hours', 24)}h"}


def demotion_target(current: str) -> str:
    """Tier to fall back to when `current` fails probation (one step down,
    floor = great_sage)."""
    idx = tiers.TIERS.index(current) if current in tiers.TIERS else 0
    return tiers.TIERS[max(idx - 1, 0)]


# ---- config application (line-scoped edit, comments preserved) -------------
_TIER_LINE = re.compile(r"(?m)^([ \t]*tier[ \t]*:[ \t]*)([A-Za-z_]+)([ \t]*(?:#.*)?)$")


def apply_tier(fragment_text: str, new_tier: str,
               write_to: Optional[Path] = None) -> str:
    """Rewrite ONLY the `tier:` value in the lane fragment (persona block),
    preserving every comment and key. Raises if the line is missing (never
    silently appends a duplicate). With `write_to`, writes the file too."""
    if new_tier not in tiers.TIERS:
        raise ValueError(f"unknown tier {new_tier!r}")
    if not _TIER_LINE.search(fragment_text):
        raise ValueError("no `tier:` line found in fragment — refusing to edit")
    new_text = _TIER_LINE.sub(
        lambda m: f"{m.group(1)}{new_tier}{m.group(3)}", fragment_text, count=1)
    if write_to is not None:
        Path(write_to).write_text(new_text, encoding="utf-8")
    return new_text

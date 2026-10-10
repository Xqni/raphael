"""Foreground-name cache (AUD-05 data source, dispatch 2026-10-08).

pc-control/body PUSHES the focused window (ws frame `foreground`); the router
chat gate reads through `provider()`:
  1. push-cache first — fresh <5s wins (cheap, no round-trip, per router's
     wire-foreground-hook contract);
  2. vision gateway ring second (record_foreground on probes, <60s);
  3. otherwise None = UNKNOWN = router fails closed.

Never raises; value-blind (window names are stored, never logged)."""
import time
from typing import Optional

FRESH_S = 5.0
RING_FRESH_S = 60.0

_name: Optional[str] = None
_ts: float = 0.0


def set_foreground(name: Optional[str]) -> bool:
    """Cache a pushed focused-window name (ws `foreground` frame)."""
    global _name, _ts
    if not name or not str(name).strip():
        return False
    _name = ' '.join(str(name).split())[:160]
    _ts = time.monotonic()
    return True


def cached() -> Optional[str]:
    """Push-cache value when FRESH (<5s), else None (stale = unknown)."""
    if _name and (time.monotonic() - _ts) <= FRESH_S:
        return _name
    return None


def provider() -> Optional[str]:
    """The hook registered with brain.router.set_foreground_check."""
    hit = cached()
    if hit:
        return hit
    try:
        from .vision import context as ring
        hist = ring.recent_history(1)
        if hist:
            ts, ident = hist[-1]
            if time.time() - ts <= RING_FRESH_S:
                return ident
    except Exception:  # noqa: BLE001 — hook must never raise
        return None
    return None


def status_block() -> dict:
    """Wave 5U P0.7: /status.foreground -> {state, age_s}.
    ok = push-cache fresh (<5 s); stale = ring-only (<60 s); unknown = none.
    Value-blind: no window titles here — only state + age."""
    if _name and (time.monotonic() - _ts) <= FRESH_S:
        return {'state': 'ok', 'age_s': round(time.monotonic() - _ts, 1)}
    try:
        from .vision import context as ring
        hist = ring.recent_history(1)
        if hist:
            ts, _ident = hist[-1]
            age = time.time() - ts
            if age <= RING_FRESH_S:
                return {'state': 'stale', 'age_s': round(age, 1)}
    except Exception:  # noqa: BLE001 — status must never raise
        pass
    return {'state': 'unknown', 'age_s': None}


def reset_for_tests() -> None:
    global _name, _ts
    _name = None
    _ts = 0.0

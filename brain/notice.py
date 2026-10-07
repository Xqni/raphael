"""Proactive Notice events (PROTOCOL §3 — approved 2026-10-07, decision on
`brain-core__to__integrator__notice-events.md`).

Frame (exactly as approved):
    {"type": "notice", "v": 1, "text": str, "level": "info"|"warn",
     "ts": int_ms, "job": <optional str>}
Broadcast roles: **ui + cli ONLY** (body does not render text).

Rules (decision scope):
- ratelimited per `key` (`cooldown_s`), fail-silent (a dead hub or missing
  loop must never raise), and **zero key/log data** — text only, presence of
  the condition only;
- emitter 1: restart recovery (`voice_personality.greeting_recovered` +
  interrupted count) — emitted at boot with `pending=True`, flushed to the
  first ui/cli session that authenticates (clients connect AFTER boot, so a
  plain broadcast would be lost);
- emitter 2: provider outage/recovery — max ONE pair per 10 minutes,
  outage state tracked here;
- emitter 3 (confirm expiry): DEFERRED by decision — do not build.
"""
import time
from typing import Any, Dict, List, Optional

V = 1
PROVIDER_COOLDOWN_S = 600.0        # emitter 2: max 1 pair / 10 min
_PENDING_CAP = 5
_PENDING_MAX_AGE_S = 120.0

_last: Dict[str, float] = {}       # ratelimit buckets (key -> monotonic ts)
_pending: List[Dict[str, Any]] = []  # boot notices awaiting first ui/cli auth
_provider_down = False             # emitter 2 state (True after an emitted outage)


def reset_for_tests() -> None:
    global _provider_down
    _last.clear()
    _pending.clear()
    _provider_down = False


def _now_ms() -> int:
    return int(time.time() * 1000)


def build(text: str, level: str = 'info',
          job: Optional[str] = None) -> Dict[str, Any]:
    """The approved frame shape (no other fields, ever)."""
    frame: Dict[str, Any] = {'type': 'notice', 'v': V,
                             'text': str(text), 'level':
                             'warn' if level == 'warn' else 'info',
                             'ts': _now_ms()}
    if job:
        frame['job'] = str(job)
    return frame


def emit(text: str, level: str = 'info', job: Optional[str] = None,
         key: Optional[str] = None, cooldown_s: float = 0.0,
         pending: bool = False) -> bool:
    """Build + broadcast a notice. Returns True when it was emitted.

    `key`+`cooldown_s` ratelimit; `pending=True` also queues the frame for
    the first ui/cli session that authenticates (boot notices). Fail-silent."""
    try:
        if key:
            now = time.monotonic()
            if now - _last.get(key, -1e18) < cooldown_s:
                return False
            _last[key] = now
        frame = build(text, level=level, job=job)
        if pending:
            _pending.append(frame)
            del _pending[:-_PENDING_CAP]      # keep newest few
        from .ws import get_hub
        get_hub().broadcast(frame, roles={'ui', 'cli'})
        return True
    except Exception:  # noqa: BLE001 — a notice can never break anything
        return False


async def flush_pending(hub, session) -> None:
    """Deliver queued boot notices to a freshly authenticated ui/cli session
    (clients connect after the boot broadcast would have been lost)."""
    global _pending
    try:
        if not _pending:
            return
        if getattr(session, 'role', None) not in ('ui', 'cli'):
            return
        frames, _pending = list(_pending), []
        for frame in frames:
            await hub._send(session, frame)
    except Exception:  # noqa: BLE001
        _pending = []


# ---- emitter 2: provider outage / recovery (presence-only) ------------------
def provider_down() -> bool:
    """Cloud chain unreachable. One warn notice; silent while active."""
    global _provider_down
    try:
        if _provider_down:
            return False
        ok = emit('Cloud providers unreachable — retrying.',
                  level='warn', key='provider_outage',
                  cooldown_s=PROVIDER_COOLDOWN_S)
        if ok:
            _provider_down = True
        return ok
    except Exception:  # noqa: BLE001
        return False


def provider_up() -> bool:
    """Chain answered again — close the pair (only after an emitted outage)."""
    global _provider_down
    try:
        if not _provider_down:
            return False
        _provider_down = False
        return emit('Cloud providers reachable again.', level='info',
                    key='provider_recovery', cooldown_s=0.0)
    except Exception:  # noqa: BLE001
        return False


def pending_count() -> int:
    return len(_pending)

"""orb_state emission controller (INTERFACES §e — brain-core emits every state).

One place builds EVERY `orb_state` frame so the contract in INTERFACES §e is
provable: each frame carries `state`, `jobs_active`, `mode`, `shape_hint`,
`task_kind`, and (once known) `provider`, `model`. The orb only renders.

States and their triggers (§e table):
  starting     boot snapshot while the engine is not ready (app lifespan)
  idle         initial snapshot after auth with jobs_active==0; last job
               terminal (after its speak end)
  listening    mic `audio_start` (reason wake|ptt); back to idle on
               `audio_end` when no job ran
  thinking     a job is running (plan/LLM in flight) — derived from job stats
  acting       first `act_req` sent / an input-lock job holds the lock
  speaking     speak pipeline active (first `start`, ends after last `end`)
  confirm      `needs_confirm` pending (confirm.py gate)
  error        job failed / provider exhausted — transient, then idle
  reconnecting/offline — the ORB CLIENT owns those (never emitted here)

`private`/`paused` are MODE overlays (frame `mode` + `private` flag), never
states — except the legacy `private_overlay` value some clients still accept,
which is produced only when private AND the derived state is idle.
"""
from __future__ import annotations

import time
from typing import Any, Dict, Optional

from . import config as appcfg

ERROR_LINGER_S = 3.0

VALID_STATES = ('starting', 'reconnecting', 'offline', 'idle', 'listening',
                'thinking', 'acting', 'speaking', 'confirm', 'error')

_hub = None                      # attached by app.py / ws.py

# ---- module state (single asyncio loop; no locking needed) -----------------
_booting = True
_listening = False
_speaking = 0                    # active speak pipelines (job-scoped)
_task_kind = 'none'
_provider: Optional[str] = None
_model: Optional[str] = None
_error_until = 0.0


def attach(hub):
    global _hub
    _hub = hub
    return hub


def reset_for_tests():
    """Return to boot state (tests only — name is the convention signal)."""
    global _booting, _listening, _speaking, _task_kind, _provider, _model, _error_until
    _booting = True
    _listening = False
    _speaking = 0
    _task_kind = 'none'
    _provider = None
    _model = None
    _error_until = 0.0


# ---- context setters -------------------------------------------------------
def set_provider(provider: Optional[str], model: Optional[str] = None):
    """Router's current/last target (INTERFACES §a results carry both)."""
    global _provider, _model
    if provider:
        _provider = provider
    if model:
        _model = model


def set_task(kind: Optional[str]):
    """Foreground task kind (fastpath/loop) -> shape_hint via orb.shape_map."""
    global _task_kind
    allowed = ('system', 'files', 'web', 'media', 'llm', 'gui', 'none')
    _task_kind = kind if kind in allowed else 'none'


def current_task_kind() -> str:
    """Public accessor for the foreground task kind (loop passes it to the
    conversation-memory hook)."""
    return _task_kind


def clear_task():
    global _task_kind
    _task_kind = 'none'


def listening_on():
    global _listening
    _listening = True


def listening_off():
    global _listening
    _listening = False


def speak_start():
    global _speaking
    _speaking += 1


def speak_end():
    global _speaking
    _speaking = max(0, _speaking - 1)


def mark_error():
    """Transient error state (§e: error -> then idle)."""
    global _error_until
    _error_until = time.monotonic() + ERROR_LINGER_S


def booting() -> bool:
    return _booting


def finish_boot():
    global _booting
    _booting = False


# ---- frame building --------------------------------------------------------
def _shape_for(kind: str) -> str:
    try:
        shape_map = appcfg.cfg_get(appcfg.get_config(), 'orb.shape_map', {}) or {}
    except Exception:  # noqa: BLE001 — orb must render even if config breaks
        shape_map = {}
    shape = shape_map.get(kind)
    if isinstance(shape, str) and shape:
        return shape
    return 'circle'


def derive_state(engine=None) -> str:
    """§e precedence: booting > confirm > speaking > listening > acting
    (input-lock) > thinking (jobs active) > error window > idle.

    SPEAKING HOLDS (Bug E, P0): once a speak pipeline is active, `speaking`
    wins over `listening` for the WHOLE utterance — the always-listen mic
    opening between sentence chunks (audio_start) must never flip her back
    to `listening` mid-answer. Listening only shows again after the utterance
    ends (speak_end), or after barge-in stops the speech."""
    if _booting:
        return 'starting'
    stats = engine.stats() if engine is not None else {}
    if stats.get('jobs_pending_confirm'):
        return 'confirm'
    if _speaking > 0:
        return 'speaking'
    if _listening:
        return 'listening'
    lock = stats.get('input_lock') or {}
    if lock.get('held'):
        return 'acting'
    if stats.get('jobs_active'):
        return 'thinking'
    if time.monotonic() < _error_until:
        return 'error'
    return 'idle'


def build(state: Optional[str] = None, engine=None,
          extra: Optional[Dict] = None) -> Dict[str, Any]:
    """Full INTERFACES §e frame (the ONLY frame builder in the brain)."""
    from .mode import get_mode
    if engine is None:
        from .jobs.engine import get_engine
        engine = get_engine()
    stats = engine.stats() if engine is not None else {}
    mode = get_mode()
    st = state or derive_state(engine)
    frame: Dict[str, Any] = {
        'type': 'orb_state',
        'v': 1,
        'state': st,
        'jobs_active': int(stats.get('jobs_active') or 0),
        'mode': mode.label(),
        'shape_hint': _shape_for(_task_kind),
        'task_kind': _task_kind,
    }
    if _provider:
        frame['provider'] = _provider
    if _model:
        frame['model'] = _model
    if mode.private:
        frame['private'] = True
    if extra:
        frame.update(extra)
    return frame


def broadcast(frame: Dict[str, Any], hub=None):
    h = hub or _hub
    if h is None:
        return frame
    h.broadcast(frame, roles={'ui'})
    return frame


def refresh(hub=None, engine=None) -> Dict[str, Any]:
    """Re-derive and fan out (job events, mode changes, control actions)."""
    return broadcast(build(engine=engine), hub=hub)


def emit(state: str, hub=None, engine=None, extra: Optional[Dict] = None
         ) -> Dict[str, Any]:
    """Explicit transition (boot/listening/error/...).

    Bug E hold: an explicit `listening` while an utterance is active (mic
    opening mid-speech, always-listen) broadcasts `speaking` instead — she
    never flips to `listening` before speak_end."""
    if state not in VALID_STATES:
        state = 'idle'
    if state == 'listening' and _speaking > 0:
        state = 'speaking'
    return broadcast(build(state=state, engine=engine, extra=extra), hub=hub)

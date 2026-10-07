"""Analysis job type — Wave-5 (evolution task-kind contract + qa privacy
contract `analysis-simulation-privacy-contract`, APPROVED 2026-10-07).

Semantics (assigned [43]):
- read-only deep pass: side effects limited to the memory store — the model
  only ever sees READ-ONLY tool specs (risky / needs_lock tools stripped);
- priority: background (clamped by the engine on submit/kind-set);
- lock: false — an analysis job never acquires the input lock;
- output = Report format (loop emits `report` for kind=analysis).

Privacy gates (qa contract points 1-3 — enforced HERE, not only in the loop):
1. `gate(mode)` refuses under Private Mode — no model call happens;
2. `redact(text)` scrubs `privacy.redact` kinds before ANY spoken / journaled /
   prompted / emitted output;
3. `wrap_ingest(...)` wraps external data (screen/web/memory) as untrusted
   before it enters a prompt (AGENTS §9).
"""
from typing import Any, Dict, List, Optional

from . import config as appcfg
from . import tools as tool_reg

NAME = 'analysis'


def gate(mode) -> Optional[str]:
    """Point 1 — Private Mode suppresses ALL Analysis model calls. Returns a
    refusal string when blocked, None when allowed."""
    try:
        if mode.private:   # AttributeError on a broken mode -> fail CLOSED
            return ('Analysis is disabled in Private Mode — cloud models are '
                    'off. Fast path only.')
    except Exception:  # noqa: BLE001 — a broken mode object must fail closed
        return 'Analysis is unavailable right now.'
    return None


def _redact_kinds() -> List[str]:
    try:
        kinds = appcfg.cfg_get(appcfg.get_config(), 'privacy.redact', []) or []
        return [str(k) for k in kinds]
    except Exception:  # noqa: BLE001
        return ['api_key', 'token', 'password', 'card', 'email', 'phone']


def redact(text: Any) -> str:
    """Point 2 — privacy.redact scrubbing for anything spoken, journaled,
    subtitle'd, re-prompted or emitted (answer/report). Deterministic regex
    scrubbing, never raises."""
    s = '' if text is None else str(text)
    try:
        from brain.vision.redact import redact_text
        return redact_text(s, _redact_kinds())
    except Exception:  # noqa: BLE001 — router fallback, then raw no-crash
        try:
            from brain.router.privacy import redact_categories
            return redact_categories(s, _redact_kinds())
        except Exception:  # noqa: BLE001
            return s


def wrap_ingest(source: str, text: Any) -> str:
    """Point 3 — external data (screen/web/memory/log content) enters prompts
    ONLY through the untrusted wrapper (AGENTS §9)."""
    return tool_reg.as_untrusted(text, source)


def readonly_specs(specs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Read-only guarantee: drop risky and input-lock tools from the offered
    spec list (side effects limited to the memory store)."""
    out = []
    for s in specs or []:
        name = ((s or {}).get('function') or {}).get('name')
        meta = tool_reg.describe(name) if name else {}
        if meta.get('risky') or meta.get('needs_lock'):
            continue
        out.append(s)
    return out


def assert_no_lock(engine, rowid: int) -> None:
    """lock:false — belt & braces if anything ever routes a lock through an
    analysis job (the read-only filter should make this unreachable)."""
    if engine.lock.is_held_by(rowid):
        engine.lock.release(rowid)

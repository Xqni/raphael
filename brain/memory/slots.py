"""Named context slots — wave-5P P5 (A3): short-term contexts ("work",
"travel") that scope memory retrieval.

Contract (docs/lanes/tools-memory.md Wave 5P + 06-CODE-ADOPTION-PLAN P5):
- slot = named short-term context; **memory retrieval is scoped to the active
  slot** (retrieval.py filters; pinned rows too);
- voice-switchable ("switch to travel" — the fastpath/loop side calls
  `switch_slot`, seam request tools-memory__to__brain-core__wave5p-memory-seams);
- **default slot = today's behavior**: every pre-existing row carries
  `slot='default'` (schema default) and the active slot starts at 'default';
- **session-persistent**: the active slot lives in the `state` table (same
  persistence pattern as pause/private/watch), so it survives restarts; slots
  are durable tags on rows (the "optional save" case is trivially satisfied —
  nothing evaporates unless the user forgets the CONTENT, see P6);
- creation is cheap/local -> **act-first, no confirm** (plan §P5).

Non-scoped surfaces (by design): conversation turns/summaries stay
session-transcript data; `profile.user_profile()` stays GLOBAL (a user's
identity/preferences are about the user, not the current workstream).
"""
import re
from typing import Any, Dict, List, Optional

_SLOT_RE = re.compile(r'^[a-z0-9][a-z0-9_-]{0,31}$')
STATE_KEY = 'active_slot'
DEFAULT_SLOT = 'default'

_active_cache: Optional[str] = None


def validate(name: Any) -> str:
    """Normalize (strip/lowercase — voice says 'Travel') and validate.
    Raises ValueError on empty/illegal names."""
    n = str(name or '').strip().lower()
    if not _SLOT_RE.match(n):
        raise ValueError(f'invalid slot name {name!r} '
                         f'(need [a-z0-9][a-z0-9_-]{{0,31}})')
    return n


def active_slot() -> str:
    """Current slot; fail-silent -> 'default' (today's behavior)."""
    global _active_cache
    if _active_cache:
        return _active_cache
    try:
        from . import get_conn
        conn = get_conn()
        try:
            row = conn.execute(
                'SELECT value FROM state WHERE key = ?',
                (STATE_KEY,)).fetchone()
            val = str(row[0]) if row else ''
        finally:
            conn.close()
        if _SLOT_RE.match(val):
            _active_cache = val
            return val
    except Exception:  # noqa: BLE001 — broken DB: default scope, never a crash
        pass
    return DEFAULT_SLOT


def switch_slot(name: Any) -> Dict[str, Any]:
    """Act-first switch (no confirm: cheap + local). Returns
    {'from', 'to', 'changed'} for the narrator. Raises ValueError on a bad
    name (fastpath can map that to a spoken clarification)."""
    global _active_cache
    target = validate(name)
    prev = active_slot()
    from . import get_conn
    conn = get_conn()
    try:
        conn.execute(
            'INSERT INTO state (key, value, updated_at) VALUES (?, ?, '
            "datetime('now')) ON CONFLICT(key) DO UPDATE SET value = "
            'excluded.value, updated_at = datetime(\'now\')',
            (STATE_KEY, target))
        conn.commit()
    finally:
        conn.close()
    _active_cache = target
    return {'from': prev, 'to': target, 'changed': prev != target}


def list_slots(*, owner: Optional[str] = None) -> List[Dict[str, Any]]:
    """Slots with memory counts, active first. Fail-silent -> [{default}]."""
    try:
        from .store import default_owner
        from . import get_conn
        owner = owner or default_owner()
        conn = get_conn()
        try:
            rows = conn.execute(
                'SELECT slot, COUNT(*) AS n FROM memories WHERE owner = ? '
                'GROUP BY slot ORDER BY slot', (owner,)).fetchall()
        finally:
            conn.close()
        out = [{'name': str(r['slot'] or DEFAULT_SLOT), 'memories': int(r['n']),
                'active': str(r['slot'] or DEFAULT_SLOT) == active_slot()}
               for r in rows]
        names = {o['name'] for o in out}
        cur = active_slot()
        if cur not in names:                # empty-but-active slot is visible
            out.append({'name': cur, 'memories': 0, 'active': True})
        if DEFAULT_SLOT not in names:        # home slot is always listable
            out.append({'name': DEFAULT_SLOT, 'memories': 0,
                        'active': cur == DEFAULT_SLOT})
        out.sort(key=lambda o: (not o['active'], o['name']))
        return out
    except Exception:  # noqa: BLE001
        return [{'name': DEFAULT_SLOT, 'memories': 0, 'active': True}]


def reset_cache_for_tests() -> None:
    global _active_cache
    _active_cache = None

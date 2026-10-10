"""Memory entry CRUD — `memories` table (addendum §3, Odysseus semantics).

Discipline:
- **owner on every row, owner filter on every query** (Odysseus had a
  cross-user leak bug — PR #2404 — never repeat it).
- strict source/category values (loud ValueError, no silent normalization —
  tool schemas type them as strings, enums are enforced HERE).
- fail-silent is NOT a property of this module: these are direct calls, and a
  caller deserves a clear error. The prompt-injection safety property lives in
  `retrieval.py` (data only) + `block.py` (untrusted framing).
"""
import time
from typing import Any, Dict, List, Optional

SOURCES = ('user', 'observed', 'imported')
CATEGORIES = ('identity', 'contact', 'preference', 'fact', 'task')
PERSONAL_CATEGORIES = ('identity', 'contact')   # privacy gate: not for free cloud

DEFAULT_OWNER = 'local-user'


def default_owner() -> str:
    try:
        from .. import config as appcfg
        return str(appcfg.cfg_get(appcfg.get_config(), 'memory.owner',
                                  DEFAULT_OWNER) or DEFAULT_OWNER)
    except Exception:  # noqa: BLE001 — config trouble never breaks capture
        return DEFAULT_OWNER


def _validate(text: Any, source: Any, category: Any) -> str:
    text = str(text).strip() if text is not None else ''
    if not text:
        raise ValueError('memory text must be non-empty')
    if source not in SOURCES:
        raise ValueError(f'invalid source {source!r} (one of {SOURCES})')
    if category not in CATEGORIES:
        raise ValueError(f'invalid category {category!r} (one of {CATEGORIES})')
    return text


def remember(text: Any, *, source: str = 'observed', category: str = 'fact',
             pinned: bool = False, owner: Optional[str] = None,
             slot: Optional[str] = None) -> int:
    """Store one memory. Returns the new row id. Raises ValueError on
    empty text / unknown source / category. AUD-15 retention: oldest
    UNPINNED rows beyond `memory.max_rows` are dropped in the same
    transaction (pinned rows are never trimmed).
    P5: rows are tagged with `slot` (default = the ACTIVE context slot)."""
    from . import get_conn, slots
    text = _validate(text, source, category)
    slot_val = slots.validate(slot) if slot is not None else slots.active_slot()
    conn = get_conn()
    try:
        cur = conn.execute(
            'INSERT INTO memories (text, source, category, pinned, owner, slot) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            (text, source, category, 1 if pinned else 0,
             owner or default_owner(), slot_val))
        _trim(conn, owner or default_owner())
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def _trim(conn, owner: str) -> None:
    """AUD-15 retention cap — fail-silent (a cap hiccup must not fail the
    insert; the row itself is already written)."""
    try:
        from .. import config as appcfg
        cap = int(appcfg.cfg_get(appcfg.get_config(),
                                 'memory.max_rows', 5000) or 5000)
    except Exception:  # noqa: BLE001
        cap = 5000
    if cap <= 0:
        return
    try:
        conn.execute(
            'DELETE FROM memories WHERE owner = ? AND pinned = 0 '
            'AND id NOT IN (SELECT id FROM memories WHERE owner = ? '
            'AND pinned = 0 ORDER BY id DESC LIMIT ?)',
            (owner, owner, cap))
    except Exception:  # noqa: BLE001
        pass


def forget(mem_id: int, *, owner: Optional[str] = None) -> bool:
    """Delete one memory (owner-scoped). Returns False if not found/owned.
    (The FTS sync trigger keeps the index consistent.)"""
    from . import get_conn
    conn = get_conn()
    try:
        cur = conn.execute('DELETE FROM memories WHERE id = ? AND owner = ?',
                           (int(mem_id), owner or default_owner()))
        conn.commit()
        return bool(cur.rowcount)
    finally:
        conn.close()


def pin(mem_id: int, on: bool = True, *, owner: Optional[str] = None) -> bool:
    from . import get_conn
    conn = get_conn()
    try:
        cur = conn.execute(
            'UPDATE memories SET pinned = ? WHERE id = ? AND owner = ?',
            (1 if on else 0, int(mem_id), owner or default_owner()))
        conn.commit()
        return bool(cur.rowcount)
    finally:
        conn.close()


def list_memories(*, category: Optional[str] = None, pinned: Optional[bool] = None,
                  owner: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    """Owner-scoped listing, newest first. Unknown category -> ValueError."""
    from . import get_conn
    if category is not None and category not in CATEGORIES:
        raise ValueError(f'invalid category {category!r} (one of {CATEGORIES})')
    clauses, params = ['owner = ?'], [owner or default_owner()]
    if category is not None:
        clauses.append('category = ?')
        params.append(category)
    if pinned is not None:
        clauses.append('pinned = ?')
        params.append(1 if pinned else 0)
    conn = get_conn()
    try:
        rows = conn.execute(
            f'SELECT id, text, ts, source, category, pinned, uses, last_used '
            f'FROM memories WHERE {" AND ".join(clauses)} '
            f'ORDER BY pinned DESC, ts DESC LIMIT ?',
            (*params, max(1, int(limit)))).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def bump_use(mem_id: int, *, owner: Optional[str] = None) -> None:
    """Usage counter increment on retrieval (Odysseus `uses`/`last_used`).
    Fail-silent: a counter hiccup must not fail a retrieval."""
    from . import get_conn
    conn = None
    try:
        conn = get_conn()
        conn.execute(
            'UPDATE memories SET uses = uses + 1, last_used = ? '
            'WHERE id = ? AND owner = ?',
            (time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime()),
             int(mem_id), owner or default_owner()))
        conn.commit()
    except Exception:  # noqa: BLE001
        pass
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass

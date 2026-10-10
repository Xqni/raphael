"""Spoken memory privacy — wave-5P P6 (A4).

The three spoken affordances over the ALREADY-SHIPPED wave-4 surface
(verified 2026-10-09: `export_all` export.py:39 0600/owner-scoped,
`wipe` export.py:90, `store.forget` store.py:88, `skills.delete_skill`
skills.py:413, file_trash/restore roundtrip — 7/7 tests green):

- `recall(query)`    -> "what do you remember about X" — scoped rows + a
  speakable text. Scope = owner + ACTIVE context slot (P5) — no cross-owner
  leakage (PR #2404), no cross-slot leakage.
- `forget_fact(x)`   -> "forget X" — DESTRUCTIVE -> confirm-first per
  safety.confirm_policy / P3: without `confirmed=True` it returns a
  NEEDS-CONFIRM preview (what would go) and deletes NOTHING; with it, all
  owner-wide matches are deleted. Idempotent: 2nd call -> 0, no error.
- `memory_report()`  -> "memory report" — counts by category/slot, pinned,
  turns/summaries/reports, + the export/wipe pointers. One speakable string.

PRIVATE-MODE RULE: every function here is LOCAL-ONLY (sqlite) — none imports
`brain.router`; recall/report/forget work with `RAPHAEL_DISABLE_ROUTER=1` and
must never trigger a cloud call (tested).
"""
from typing import Any, Dict, List, Optional

from . import retrieval, slots
from .store import default_owner


# ---- "what do you remember about X" ----------------------------------------
def recall(query: Any, *, owner: Optional[str] = None, k: Optional[int] = None,
           slot: Optional[str] = None) -> Dict[str, Any]:
    """Scoped recall. DATA + speakable text; fail-silent on DB trouble
    (broken DB -> nothing remembered). Uses the active slot unless `slot`
    names one — a BAD slot name raises ValueError OUTSIDE the fail-silent
    guard so fastpath can ask a clarification instead of lying 'nothing'."""
    target = slots.validate(slot) if slot is not None else None
    try:
        rows = retrieval.retrieve(query, k=k, owner=owner, slot=target)
        lines = [f"- ({r.get('category', 'fact')}, "
                 f"{str(r.get('ts', ''))[:10]}): {r.get('text', '')}"
                 for r in rows]
        return {'slot': target or slots.active_slot(),
                'count': len(rows), 'rows': rows,
                'text': '\n'.join(lines) if lines else 'Nothing remembered.'}
    except Exception:  # noqa: BLE001 — spoken path never crashes
        return {'slot': slots.active_slot(), 'count': 0, 'rows': [],
                'text': 'Nothing remembered.'}


# ---- "forget X" (confirm-first) --------------------------------------------
def _matches(target: Any, owner: str) -> List[Dict[str, Any]]:
    """Owner-wide candidate rows (all slots): forgetting means 'forget it',
    not 'forget it in this context'."""
    from . import get_conn
    needle = str(target or '').strip().lower()
    if not needle:
        return []
    conn = get_conn()
    try:
        rows = conn.execute(
            'SELECT id, text, slot, category, pinned FROM memories '
            'WHERE owner = ?', (owner,)).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows if needle in str(r['text']).lower()]


def forget_fact(target: Any, *, confirmed: bool = False,
                owner: Optional[str] = None) -> Dict[str, Any]:
    """Destructive: requires confirmed=True (P3/safety.confirm_policy).
    Returns {'status': 'needs_confirm'|'done', 'matches', 'deleted',
             'preview'} — idempotent (done, 0) on repeats. Owner-wide,
    never cross-owner (PR #2404). Fail-silent -> deleted 0."""
    try:
        owner = owner or default_owner()
        hits = _matches(target, owner)
        preview = '; '.join(str(h['text'])[:80] for h in hits[:3])
        if not confirmed:
            return {'status': 'needs_confirm' if hits else 'done',
                    'matches': len(hits), 'deleted': 0, 'preview': preview}
        if not hits:
            return {'status': 'done', 'matches': 0, 'deleted': 0, 'preview': ''}
        from . import get_conn
        conn = get_conn()
        try:
            ids = [int(h['id']) for h in hits]
            conn.executemany(
                'DELETE FROM memories WHERE id = ? AND owner = ?',
                [(i, owner) for i in ids])        # owner re-checked per row
            conn.commit()
        finally:
            conn.close()
        return {'status': 'done', 'matches': len(hits),
                'deleted': len(ids), 'preview': preview}
    except Exception:  # noqa: BLE001
        return {'status': 'done', 'matches': 0, 'deleted': 0, 'preview': ''}


# ---- "memory report" --------------------------------------------------------
def memory_report(*, owner: Optional[str] = None) -> str:
    """One speakable/local summary of her memory footprint. LOCAL ONLY."""
    try:
        from . import get_conn, conversation, summary as _sum, reports
        owner = owner or default_owner()
        conn = get_conn()
        try:
            by_cat = {r['category']: int(r['n']) for r in conn.execute(
                'SELECT category, COUNT(*) AS n FROM memories WHERE owner = ? '
                'GROUP BY category', (owner,))}
            pinned = int(conn.execute(
                'SELECT COUNT(*) FROM memories WHERE owner = ? AND pinned = 1',
                (owner,)).fetchone()[0])
            by_slot = {str(r['slot'] or 'default'): int(r['n'])
                       for r in conn.execute(
                           'SELECT slot, COUNT(*) AS n FROM memories '
                           'WHERE owner = ? GROUP BY slot', (owner,))}
        finally:
            conn.close()
        total = sum(by_cat.values())
        parts = [f'{total} memories ({", ".join(f"{k}: {v}" for k, v in sorted(by_cat.items())) or "none"})',
                 f'{pinned} pinned',
                 f'active slot: {slots.active_slot()} '
                 f'({", ".join(f"{k}: {v}" for k, v in sorted(by_slot.items()))})',
                 f'{conversation.turn_count()} conversation turns, '
                 f'{len(_sum.recent_summaries(limit=999))} summaries, '
                 f'{len(reports.recent_reports(limit=999))} cached reports']
        return ('Memory report — ' + '; '.join(parts) +
                '. Export or wipe anytime: memory export / wipe.')
    except Exception:  # noqa: BLE001 — honest failure, never a crash
        return 'Memory report is unavailable right now.'

"""Report cache — Analysis/Simulation report recall (wave 5).

`formats.py` (brain-core) EMITS `report` frames to the UI; this module caches
them locally so a later turn can recall past reports (cross-session report
recall = part of the memory-context feeding seam). Wiring the emit -> cache
call is brain-core's (docs/requests/
tools-memory__to__brain-core__report-cache-hook.md).

Contracts:
- **caps re-enforced at save** (defense in depth, PROTOCOL §3): summary<=500,
  sections<=10, heading/text trimmed (text<=2000) — a malformed frame is
  TRUNCATED into shape, never rejected (caching must not break emission);
- **fail-silent save** (same as `conversation.on_turn`: a cache failure never
  fails the report itself) — returns None on any DB error;
- **owner-scoped readers**, token-overlap retrieval (no FTS table here —
  reports are few and bounded), readers fail-silent;
- every returned record is DATA — the loop frames it via `block.py` before
  any model sees it (AGENT_RULES §9), with marker neutralization.
"""
import json
import re
from typing import Any, Dict, List, Optional

# PROTOCOL §3 report caps (server-side, enforced again here)
MAX_SUMMARY = 500
MAX_SECTIONS = 10
MAX_HEADING = 200
MAX_TEXT = 2000

_PAT = re.compile(r'[a-z0-9]+')


def _cfg(dotted: str, default):
    try:
        from .. import config as appcfg
        return appcfg.cfg_get(appcfg.get_config(), dotted, default)
    except Exception:  # noqa: BLE001
        return default


def _default_owner() -> str:
    from .store import default_owner
    return default_owner()


def _trim(text: Any, cap: int) -> str:
    s = ' '.join(str(text or '').split())
    return s if len(s) <= cap else s[:cap - 1] + '…'


def save_report(*, title: Any, summary: Any = '', sections: Any = None,
                job: Optional[str] = None, kind: str = 'analysis',
                owner: Optional[str] = None) -> Optional[int]:
    """Cache one report frame. Fail-silent: any error -> None (the emitted
    report must never depend on the cache)."""
    try:
        title_t = _trim(title, 500)
        if not title_t:
            return None
        norm_sections: List[Dict[str, str]] = []
        for s in (sections or [])[:MAX_SECTIONS]:
            if not isinstance(s, dict):
                continue
            norm_sections.append({
                'heading': _trim(s.get('heading'), MAX_HEADING),
                'text': _trim(s.get('text'), MAX_TEXT),
            })
        from . import get_conn
        conn = get_conn()
        try:
            cur = conn.execute(
                'INSERT INTO reports (job, title, summary, sections, kind, '
                'owner) VALUES (?,?,?,?,?,?)',
                (str(job) if job else None, title_t,
                 _trim(summary, MAX_SUMMARY),
                 json.dumps(norm_sections, ensure_ascii=False),
                 str(kind or 'analysis'), owner or _default_owner()))
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        return None


def _row_to_rec(row) -> Dict[str, Any]:
    d = dict(row)
    try:
        d['sections'] = json.loads(d.get('sections') or '[]')
    except Exception:  # noqa: BLE001
        d['sections'] = []
    return d


def recent_reports(limit: int = 5, *, owner: Optional[str] = None,
                   kind: Optional[str] = None) -> List[Dict[str, Any]]:
    """Newest first. Fail-silent: errors -> []."""
    conn = None
    try:
        from . import get_conn
        conn = get_conn()
        clauses, params = ['owner = ?'], [owner or _default_owner()]
        if kind is not None:
            clauses.append('kind = ?')
            params.append(str(kind))
        rows = conn.execute(
            'SELECT id, job, title, summary, sections, kind, created_at '
            f'FROM reports WHERE {" AND ".join(clauses)} '
            'ORDER BY id DESC LIMIT ?',
            (*params, max(1, int(limit)))).fetchall()
        return [_row_to_rec(r) for r in rows]
    except Exception:  # noqa: BLE001
        return []
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


def find_reports(query: Any, limit: int = 3, *,
                 owner: Optional[str] = None) -> List[Dict[str, Any]]:
    """Token-overlap recall over title+summary+section text (same scoring
    family as retrieval's keyword fallback). Query is DATA: tokenized with a
    whitelist regex, so no operator can break it. Fail-silent -> []."""
    conn = None
    try:
        q = {t for t in _PAT.findall(str(query or '').lower())}
        if not q:
            return []
        from . import get_conn
        conn = get_conn()
        rows = conn.execute(
            'SELECT id, job, title, summary, sections, kind, created_at '
            'FROM reports WHERE owner = ? ORDER BY id DESC LIMIT 500',
            (owner or _default_owner(),)).fetchall()
        scored = []
        for r in rows:
            rec = _row_to_rec(r)
            blob = ' '.join([rec['title'], rec['summary'],
                             ' '.join(s.get('text', '') + ' ' + s.get('heading', '')
                                      for s in rec['sections'])]).lower()
            overlap = len(q & set(_PAT.findall(blob)))
            if overlap:
                rec['score'] = float(overlap)
                scored.append(rec)
        scored.sort(key=lambda d: -d['score'])
        return scored[:max(1, int(limit))]
    except Exception:  # noqa: BLE001
        return []
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


def get_report(report_id: Any, *, owner: Optional[str] = None
               ) -> Optional[Dict[str, Any]]:
    conn = None
    try:
        from . import get_conn
        conn = get_conn()
        row = conn.execute(
            'SELECT id, job, title, summary, sections, kind, created_at '
            'FROM reports WHERE id = ? AND owner = ?',
            (int(report_id), owner or _default_owner())).fetchone()
        return _row_to_rec(row) if row else None
    except Exception:  # noqa: BLE001
        return None
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


def clear_reports(*, owner: Optional[str] = None) -> int:
    """Internal delete (tests; Wave-4-style user wipe can extend to it)."""
    conn = None
    try:
        from . import get_conn
        conn = get_conn()
        cur = conn.execute('DELETE FROM reports WHERE owner = ?',
                           (owner or _default_owner(),))
        conn.commit()
        return int(cur.rowcount or 0)
    except Exception:  # noqa: BLE001
        return 0
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass

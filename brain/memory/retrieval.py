"""Retrieval — pinned always + FTS5 BM25 top-k, category boost, recency
tiebreaker, use counters (addendum §3: Odysseus hybrid-minus-embeddings —
cloud_temp has no local embedding model, FTS5 BM25 IS the semantic half).

Safety properties:
- **DATA ONLY**: returns plain dicts; framing as untrusted context is
  `block.py`'s job (AGENT_RULES §9);
- **owner-scoped** on every query (PR #2404);
- **fail-silent**: any DB/FTS error -> `[]` (an injection failure must not
  fail the turn);
- FTS5 unavailable -> keyword-overlap fallback behind the SAME API.
"""
import calendar
import re
import time
from typing import Any, Dict, List, Optional

from . import fts as _fts
from .store import bump_use, default_owner

_PAT = re.compile(r'[A-Za-z0-9_]+')
_MAX_TOKS = 16              # bounded MATCH expression, no abuse via long queries
_PINNED_CAP = 20


def _cfg(dotted: str, default: Any) -> Any:
    try:
        from .. import config as appcfg
        return appcfg.cfg_get(appcfg.get_config(), dotted, default)
    except Exception:  # noqa: BLE001
        return default


def _tokens(text: Any) -> List[str]:
    return _PAT.findall(str(text or ''))[:_MAX_TOKS]


def _boost(category: Any) -> float:
    try:
        m = _cfg('memory.category_boost', {}) or {}
        return float(m.get(str(category), 0.0) or 0.0)
    except Exception:  # noqa: BLE001
        return 0.0


def _recency(ts: Any) -> float:
    """1.0 for now, decaying ~halflife-wise with age; 0 on unparseable ts.
    SQLite CURRENT_TIMESTAMP is UTC — parse as UTC (calendar.timegm)."""
    try:
        then = calendar.timegm(time.strptime(str(ts)[:19], '%Y-%m-%d %H:%M:%S'))
        days = max(0.0, (time.time() - then) / 86400.0)
        return 1.0 / (1.0 + days)
    except Exception:  # noqa: BLE001
        return 0.0


def _scored(row: Dict[str, Any], base: float) -> Dict[str, Any]:
    row = dict(row)
    row['score'] = float(base) + _boost(row.get('category')) + _recency(row.get('ts'))
    return row


def _fts_matches(conn, toks: List[str], owner: str, limit: int) -> List[Dict[str, Any]]:
    """BM25 via FTS5. bm25() returns NEGATIVE values (more negative = better),
    so base = -bm25 (higher = better)."""
    expr = ' OR '.join(f'"{t}"' for t in toks)
    rows = conn.execute(
        'SELECT m.id, m.text, m.ts, m.source, m.category, m.pinned, '
        '       bm25(memories_fts) AS rank '
        'FROM memories_fts JOIN memories m ON m.id = memories_fts.rowid '
        'WHERE memories_fts MATCH ? AND m.owner = ? '
        'ORDER BY rank LIMIT ?',
        (expr, owner, int(limit))).fetchall()
    return [_scored(dict(r), -float(r['rank'])) for r in rows]


def _keyword_matches(conn, toks: List[str], owner: str,
                     limit: int) -> List[Dict[str, Any]]:
    """Fallback (no FTS5): token-overlap scoring, same return shape."""
    tokset = {t.lower() for t in toks}
    rows = conn.execute(
        'SELECT id, text, ts, source, category, pinned FROM memories '
        'WHERE owner = ?', (owner,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        words = {w.lower() for w in _PAT.findall(d['text'])}
        overlap = len(tokset & words)
        if overlap:
            out.append(_scored(d, float(overlap)))
    out.sort(key=lambda d: -d['score'])
    return out[:int(limit)]


def retrieve(query: Any, k: Optional[int] = None, *,
             owner: Optional[str] = None) -> List[Dict[str, Any]]:
    """Pinned always + top-k matches. Returns [{id, text, ts, source,
    category, pinned, score}] — DATA ONLY (wrap with block.py before any
    model sees it). Fail-silent: errors -> []."""
    conn = None
    try:
        k = int(k if k is not None else (_cfg('memory.top_k', 5) or 5))
        if k <= 0:
            return []
        owner = owner or default_owner()
        from . import get_conn
        conn = get_conn()

        pinned_rows = [dict(r) for r in conn.execute(
            'SELECT id, text, ts, source, category, pinned FROM memories '
            'WHERE owner = ? AND pinned = 1 '
            'ORDER BY uses DESC, ts DESC LIMIT ?',
            (owner, _PINNED_CAP)).fetchall()]
        pinned_ids = {r['id'] for r in pinned_rows}
        for r in pinned_rows:
            r['score'] = float('inf')              # pinned sorts first by design

        toks = _tokens(query)
        matches: List[Dict[str, Any]] = []
        if toks:
            try:
                if _fts.available():
                    try:
                        matches = _fts_matches(conn, toks, owner,
                                               k + len(pinned_ids))
                    except Exception:  # noqa: BLE001 — corrupt/unusable index:
                        try:
                            _fts.rebuild(conn)  # self-heal for the next query
                        except Exception:  # noqa: BLE001
                            pass
                        matches = _keyword_matches(  # degrade, keep the turn
                            conn, toks, owner, k + len(pinned_ids))
                else:
                    matches = _keyword_matches(conn, toks, owner,
                                               k + len(pinned_ids))
            except Exception:  # noqa: BLE001 — catastrophic: pinned still ship
                matches = []
            # rank by the FINAL score: base (BM25/overlap) + category boost +
            # recency — boosts must actually be able to reorder results.
            matches.sort(key=lambda d: -d['score'])
        else:
            matches = []                            # no tokens -> pinned only

        picked: List[Dict[str, Any]] = list(pinned_rows)
        for m in matches:
            if m['id'] in pinned_ids:
                continue
            picked.append(m)
            if len(picked) >= len(pinned_rows) + k:
                break

        for r in picked:                            # Odysseus uses/last_used
            bump_use(r['id'], owner=owner)
        return picked
    except Exception:  # noqa: BLE001 — never fail a turn over retrieval
        return []
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass

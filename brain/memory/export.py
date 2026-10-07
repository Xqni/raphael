"""User-facing memory export / delete controls (wave 4; addendum §3/§4).

Deliberately MODULE APIs — NOT registered model tools: a wipe path must never
be reachable by a model call alone (destructive power stays with the user;
the CLI/UI wiring belongs to infra/integrator).

- `export_all(owner=None, dest=None) -> Path` — one JSONL file with typed
  records (kind: memory|turn|summary), written under
  `<data-dir>/exports/` (or `dest`) with mode **0600** (personal data,
  local-only: no cloud call happens here).
- `wipe(scope='all'|'memories'|'conversations', owner=None) -> dict` —
  counts of what was removed. `scope='memories'` touches ONLY the memories
  table (FTS sync triggers keep the index consistent); `scope='conversations'`
  clears conversation_turns + conversation_summaries; `'all'` = both.
  Owner scoping applies to `memories` (every query filters owner — PR #2404
  discipline); turns/summaries are single-owner by schema.
  Errors RAISE (a failed wipe must never look like a successful one).
- skills are NOT wiped here — `skills.delete_skill` / `audit_skills` own that
  surface (review/aging, not bulk delete).
"""
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

from .store import default_owner

SCOPES = ('all', 'memories', 'conversations')


def _export_root(dest: Optional[Path] = None) -> Path:
    if dest is not None:
        return Path(dest)
    from .. import config as appcfg
    return appcfg.data_dir() / 'exports'


def export_all(*, owner: Optional[str] = None,
               dest: Optional[Path] = None) -> Path:
    """Dump every personal record this lane stores, locally. Raises on any
    DB/IO error (a silent backup failure is worse than none)."""
    from . import get_conn
    owner = owner or default_owner()
    root = _export_root(dest)
    root.mkdir(parents=True, exist_ok=True)
    path = Path(root) / f'personal-export-{int(time.time())}.jsonl'
    conn = get_conn()
    n = 0
    try:
        with path.open('w', encoding='utf-8') as f:
            for r in conn.execute(
                    'SELECT id, text, ts, source, category, pinned, uses '
                    'FROM memories WHERE owner = ? ORDER BY id', (owner,)):
                f.write(json.dumps({'kind': 'memory', 'owner': owner,
                                    **dict(r)}, ensure_ascii=False) + '\n')
                n += 1
            for r in conn.execute(
                    'SELECT id, ts, user, assistant, job, task_kind '
                    'FROM conversation_turns ORDER BY id'):
                f.write(json.dumps({'kind': 'turn', **dict(r)},
                                   ensure_ascii=False) + '\n')
                n += 1
            for r in conn.execute(
                    'SELECT id, session, summary, covers_from, covers_to, '
                    'created_at FROM conversation_summaries ORDER BY id'):
                f.write(json.dumps({'kind': 'summary', **dict(r)},
                                   ensure_ascii=False) + '\n')
                n += 1
    finally:
        conn.close()
    os.chmod(path, 0o600)                      # personal data: owner-only
    return path


def export_count(path: Path) -> Dict[str, int]:
    """Parse an export back (review helper + test seam). Fail-silent -> {}."""
    counts: Dict[str, int] = {}
    try:
        for line in Path(path).read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            kind = json.loads(line).get('kind', '?')
            counts[kind] = counts.get(kind, 0) + 1
    except Exception:  # noqa: BLE001
        return {}
    return counts


def wipe(scope: str = 'all', *, owner: Optional[str] = None) -> Dict[str, int]:
    """Delete the caller's stored data (user-directed). Returns counts.
    Raises on invalid scope or DB failure — never a silent partial wipe."""
    if scope not in SCOPES:
        raise ValueError(f'invalid scope {scope!r} (one of {SCOPES})')
    from . import get_conn
    owner = owner or default_owner()
    counts = {'memories': 0, 'turns': 0, 'summaries': 0}
    conn = get_conn()
    try:
        if scope in ('all', 'memories'):
            cur = conn.execute('DELETE FROM memories WHERE owner = ?', (owner,))
            counts['memories'] = int(cur.rowcount or 0)
        if scope in ('all', 'conversations'):
            cur = conn.execute('DELETE FROM conversation_turns')
            counts['turns'] = int(cur.rowcount or 0)
            cur = conn.execute('DELETE FROM conversation_summaries')
            counts['summaries'] = int(cur.rowcount or 0)
        conn.commit()
    finally:
        conn.close()
    return counts

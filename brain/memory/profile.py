"""User-profile view — identity/preference facts over `memories`.

Single source of truth: NO separate profile table (sync bugs waiting to
happen). The profile is a filtered, ordered READ of `memories`
(category IN identity|preference; pinned first, then uses, then recency).

Privacy: `identity` is a PERSONAL category (store.PERSONAL_CATEGORIES) —
`block.build_untrusted_block(..., include_personal=False)` is how the loop's
privacy gate holds it back from free cloud providers under profile cloud_temp.
"""
from typing import Any, Dict, List, Optional

from .store import default_owner

_PROFILE_CATEGORIES = ('identity', 'preference')


def user_profile(*, owner: Optional[str] = None, limit: int = 30) -> List[Dict[str, Any]]:
    """Profile facts, most-authoritative first. Fail-silent: errors -> []."""
    conn = None
    try:
        from . import get_conn
        conn = get_conn()
        rows = conn.execute(
            'SELECT id, text, ts, source, category, pinned, uses, last_used '
            'FROM memories WHERE owner = ? AND category IN (?, ?) '
            'ORDER BY pinned DESC, uses DESC, ts DESC LIMIT ?',
            (owner or default_owner(), *_PROFILE_CATEGORIES,
             max(1, int(limit)))).fetchall()
        return [dict(r) for r in rows]
    except Exception:  # noqa: BLE001 — profile injection never fails a turn
        return []
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass

"""Conversation-turn capture — the brain-core producer seam.

Contract (docs/requests/brain-core__to__tools-memory__conversation-hook.md,
ACCEPTED 2026-10-07):

    from brain.memory import conversation as _conv
    _conv.on_turn(user=..., assistant=..., job=..., task_kind=...)

called by brain/loop.py for EVERY finished turn (fastpath answers, agent-loop
finals, tool-summary replies). Guarantees:

- **exact signature** — keyword-only, as proposed; nothing asked of brain-core;
- **O(1) synchronous on the job path** — `on_turn` only appends to a bounded
  in-memory buffer and notifies one lazily-started daemon flusher thread; the
  job path NEVER waits on SQLite;
- **fail-silent** — every failure (buffer, thread start, locked/corrupt DB)
  drops the turn and returns None; a memory failure must never fail a
  conversation (belt: this module; braces: brain-core swallows too);
- **trimmed storage** — `conversation_turns` (brain/memory/schema.py), oldest
  rows beyond `memory.conversation_max_rows` (default 5000) dropped per flush.

Retrieval readers for summary/cross-session recall live here too; the
prompt-side injection is brain-core's (request
tools-memory__to__brain-core__loop-memory-skills-injection).
"""
import threading
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Tuple

# Bounded buffer: if the flusher thread cannot run (broken DB, thread-start
# failure), memory can never grow — the oldest buffered turns drop silently.
_BUF_MAX = 512
_TEXT_CAP = 8000          # per side, chars — one turn must not bloat the DB

_Row = Tuple[int, str, str, Optional[str], Optional[str]]

_lock = threading.Lock()
_cond = threading.Condition(_lock)
_buf: Deque[_Row] = deque()
_thread: Optional[threading.Thread] = None
_stop_evt = threading.Event()


def _cfg(dotted: str, default: Any) -> Any:
    """Config accessor that can never raise (fail-silent top to bottom)."""
    try:
        from .. import config as appcfg
        return appcfg.cfg_get(appcfg.get_config(), dotted, default)
    except Exception:  # noqa: BLE001 — config problems must not kill capture
        return default


def _cap(text: str) -> str:
    return text if len(text) <= _TEXT_CAP else text[:_TEXT_CAP] + '…'


def on_turn(*, user: str, assistant: str, job: Optional[str] = None,
            task_kind: Optional[str] = None, ts: Optional[int] = None) -> None:
    """Record one finished conversation turn. Always returns None; never raises."""
    try:
        row: _Row = (
            int(ts) if ts else int(time.time()),
            _cap(str(user) if user is not None else ''),
            _cap(str(assistant) if assistant is not None else ''),
            str(job) if job is not None else None,
            str(task_kind) if task_kind is not None else None,
        )
        if not row[1] and not row[2]:
            return None                      # nothing worth storing
        with _cond:
            if len(_buf) >= _BUF_MAX:
                _buf.popleft()               # bounded: drop oldest, keep going
            _buf.append(row)
            _cond.notify()
        _ensure_flusher()
    except Exception:  # noqa: BLE001 — fail-silent by contract
        return None
    return None


# ---- background flusher (ONE daemon per process, lazily started) ------------
def _ensure_flusher() -> None:
    global _thread
    with _lock:
        if _thread is not None and _thread.is_alive():
            return
        _stop_evt.clear()
        _thread = threading.Thread(target=_loop, name='conv-flush', daemon=True)
        _thread.start()


def _loop() -> None:
    while not _stop_evt.is_set():
        try:
            interval = float(_cfg('memory.conversation_flush_s', 1.0) or 1.0)
        except Exception:  # noqa: BLE001
            interval = 1.0
        with _cond:
            _cond.wait(timeout=max(0.01, interval))
            batch = list(_buf)
            _buf.clear()
        if batch:
            try:
                _persist(batch)
            except Exception:  # noqa: BLE001 — even a broken _persist must
                pass           # not kill the flusher thread
    # final drain on shutdown (tests + interpreter exit paths)
    with _cond:
        batch = list(_buf)
        _buf.clear()
    if batch:
        try:
            _persist(batch)
        except Exception:  # noqa: BLE001
            pass


def _persist(batch: List[_Row]) -> None:
    conn = None
    try:
        from . import get_conn
        conn = get_conn()
        conn.execute('PRAGMA busy_timeout=500')
        conn.executemany(
            'INSERT INTO conversation_turns (ts, user, assistant, job, task_kind) '
            'VALUES (?, ?, ?, ?, ?)', batch)
        try:
            max_rows = int(_cfg('memory.conversation_max_rows', 5000) or 5000)
        except Exception:  # noqa: BLE001
            max_rows = 5000
        if max_rows > 0:
            conn.execute(
                'DELETE FROM conversation_turns WHERE id <= '
                '(SELECT COALESCE(MAX(id), 0) - ? FROM conversation_turns)',
                (max_rows,))
        conn.commit()
    except Exception:  # noqa: BLE001 — locked/corrupt DB: drop, never raise
        pass
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


# ---- sync paths (tests, shutdown, future explicit flush points) ------------
def flush() -> int:
    """Synchronously persist whatever is buffered. Returns rows persisted.
    Never raises (fail-silent)."""
    with _cond:
        batch = list(_buf)
        _buf.clear()
    if batch:
        try:
            _persist(batch)
        except Exception:  # noqa: BLE001 — flush() is fail-silent too
            pass
    return len(batch)


def shutdown(timeout: float = 2.0) -> None:
    """Stop the flusher thread and drain. Safe to call when never started.
    (AGENT_RULES §14: tests must leave zero orphans.)"""
    global _thread
    with _lock:
        t = _thread
        _thread = None
    _stop_evt.set()
    with _cond:
        _cond.notify_all()
    if t is not None and t.is_alive():
        t.join(timeout)
    flush()


def buffered() -> int:
    with _cond:
        return len(_buf)


# ---- retrieval readers (summary.py / cross-session recall) -----------------
def recent_turns(limit: int = 20) -> List[Dict[str, Any]]:
    """Newest turns first. Fail-silent: any DB error -> []. Untrusted data."""
    conn = None
    try:
        from . import get_conn
        conn = get_conn()
        rows = conn.execute(
            'SELECT id, ts, user, assistant, job, task_kind FROM conversation_turns '
            'ORDER BY id DESC LIMIT ?', (max(0, int(limit)),)).fetchall()
        return [dict(r) for r in rows]
    except Exception:  # noqa: BLE001
        return []
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


def turn_count() -> int:
    conn = None
    try:
        from . import get_conn
        conn = get_conn()
        return int(conn.execute('SELECT COUNT(*) FROM conversation_turns').fetchone()[0])
    except Exception:  # noqa: BLE001
        return 0
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


def clear_turns() -> int:
    """Delete all stored turns. Internal — the user-facing export/delete
    controls are a Wave-4 deliverable built on top of this."""
    conn = None
    try:
        from . import get_conn
        conn = get_conn()
        cur = conn.execute('DELETE FROM conversation_turns')
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

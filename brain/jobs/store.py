"""Job store engine — SQLite-backed, crash-safe, terminal-state immutability.

Canonical external job id: `j_YYYYMMDD_<rowid:04d>` (PROTOCOL §5 example
`j_20261005_001`). Internally the sqlite autoincrement rowid is used; parse_job_ref
accepts both forms so REST paths, WS frames and internal code interoperate.

All status writes are guarded (`... WHERE status NOT IN (terminal)`) so a
cancel-vs-completion race can never resurrect or flip a terminal job.
"""
import json
import time
from typing import Any, Dict, List, Optional

from brain.memory import get_conn

TERMINAL = ('done', 'failed', 'cancelled', 'interrupted')
PRIORITY_RANK = {'user_facing': 0, 'normal': 1, 'background': 2}

_checkpoint_migrated = False


def _ensure_checkpoint_column() -> None:
    """Wave 5U task 7: `checkpoint` (last step + packet) on the jobs row.
    Idempotent ADDITIVE migration — brain/jobs is this lane's; the schema
    bootstrap lives in brain/memory (tools-memory lane), so the column is
    added from the store side without touching their file."""
    global _checkpoint_migrated
    if _checkpoint_migrated:
        return
    conn = get_conn()
    try:
        cols = {r[1] for r in conn.execute('PRAGMA table_info(jobs)')}
        if 'checkpoint' not in cols:
            conn.execute('ALTER TABLE jobs ADD COLUMN checkpoint TEXT')
        conn.commit()
        _checkpoint_migrated = True
    finally:
        conn.close()


def set_checkpoint(job_id, data: Optional[Dict[str, Any]]) -> bool:
    """Persist the task checkpoint (JSON: {step, packet, note}); None clears.
    Never raises (a checkpoint write must not fail a task)."""
    rowid = parse_job_ref(job_id)
    if rowid is None:
        return False
    try:
        _ensure_checkpoint_column()
        conn = get_conn()
        try:
            cur = conn.execute(
                'UPDATE jobs SET checkpoint=?, updated_at=CURRENT_TIMESTAMP '
                'WHERE id=? AND status NOT IN (%s)'
                % ','.join('?' * len(TERMINAL)),
                (json.dumps(data, ensure_ascii=False) if data is not None
                 else None, rowid, *TERMINAL))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 — checkpointing is best-effort
        return False


def get_checkpoint(job_id) -> Optional[Dict[str, Any]]:
    rowid = parse_job_ref(job_id)
    if rowid is None:
        return None
    try:
        _ensure_checkpoint_column()
        conn = get_conn()
        try:
            row = conn.execute('SELECT checkpoint FROM jobs WHERE id=?',
                               (rowid,)).fetchone()
            if row and row['checkpoint']:
                return json.loads(row['checkpoint'])
            return None
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        return None


def now_ms() -> int:
    return int(time.time() * 1000)


def job_ext_id(rowid: int, created_at: Optional[str] = None) -> str:
    date = (created_at or '')[:10].replace('-', '')
    return f"j_{date or '19700101'}_{int(rowid):04d}"


def parse_job_ref(ref) -> Optional[int]:
    """Accept int rowid, numeric string, or canonical 'j_YYYYMMDD_NNNN'."""
    if ref is None:
        return None
    if isinstance(ref, int):
        return ref
    s = str(ref).strip()
    if s.isdigit():
        return int(s)
    if s.startswith('j_') and '_' in s[2:]:
        try:
            return int(s.rsplit('_', 1)[1])
        except ValueError:
            return None
    return None


def _log_event(job_id: int, event: Any):
    payload = event if isinstance(event, str) else json.dumps(event, ensure_ascii=False)
    conn = get_conn()
    try:
        conn.execute('INSERT INTO journal (job_id, event) VALUES (?, ?)', (job_id, payload))
        conn.commit()
    finally:
        conn.close()


def normalize_priority(priority) -> tuple[str, int]:
    """Return (label, rank). Legacy REST ints: lower = more urgent."""
    if isinstance(priority, int):
        if priority <= 0:
            return 'user_facing', priority
        if priority == 1:
            return 'normal', priority
        return 'background', priority
    label = priority if priority in PRIORITY_RANK else 'normal'
    return label, PRIORITY_RANK[label]


def create_job(text: str, priority='normal', source: str = 'text',
               input_lock: bool = False, session: Optional[str] = None,
               task: Optional[str] = None) -> Dict[str, Any]:
    label, rank = normalize_priority(priority)
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            'INSERT INTO jobs (task, text, priority, priority_label, status, source, '
            "input_lock, session) VALUES (?, ?, ?, ?, 'queued', ?, ?, ?)",
            (task or text, text, rank, label, source, 1 if input_lock else 0, session),
        )
        rowid = cur.lastrowid
        created = cur.execute('SELECT created_at FROM jobs WHERE id=?', (rowid,)).fetchone()
        conn.commit()
    finally:
        conn.close()
    jid = job_ext_id(rowid, created['created_at'] if created else None)
    _log_event(rowid, {'job': jid, 'event': 'created', 'text': text, 'priority': label})
    return get_job(rowid)


def get_job(job_id) -> Optional[Dict[str, Any]]:
    rowid = parse_job_ref(job_id)
    if rowid is None:
        return None
    conn = get_conn()
    try:
        row = conn.execute('SELECT * FROM jobs WHERE id=?', (rowid,)).fetchone()
    finally:
        conn.close()
    return snapshot(dict(row)) if row else None


def list_jobs(status: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = get_conn()
    try:
        if status:
            rows = conn.execute(
                'SELECT * FROM jobs WHERE status=? ORDER BY id', (status,)).fetchall()
        else:
            rows = conn.execute('SELECT * FROM jobs ORDER BY id').fetchall()
    finally:
        conn.close()
    return [snapshot(dict(r)) for r in rows]


def next_event_seq(job_id: int) -> int:
    conn = get_conn()
    try:
        conn.execute('UPDATE jobs SET event_seq = event_seq + 1 WHERE id=?', (job_id,))
        row = conn.execute('SELECT event_seq FROM jobs WHERE id=?', (job_id,)).fetchone()
        conn.commit()
    finally:
        conn.close()
    return int(row['event_seq']) if row else 0


def transition(job_id, status: str, stage: Optional[str] = None,
               progress: Optional[float] = None, result: Optional[str] = None,
               error_code: Optional[str] = None, text: Optional[str] = None) -> bool:
    """Guarded status transition. False if job is terminal (immutable) or missing."""
    rowid = parse_job_ref(job_id)
    if rowid is None:
        return False
    sets, params = ['status=?', 'updated_at=CURRENT_TIMESTAMP'], [status]
    if stage is not None:
        sets.append('stage=?')
        params.append(stage)
    if progress is not None:
        sets.append('progress=?')
        params.append(float(progress))
    if result is not None:
        sets.append('result=?')
        params.append(result)
    if error_code is not None:
        sets.append('error_code=?')
        params.append(error_code)
    if text is not None:
        sets.append('text=?')
        params.append(text)
    params.append(rowid)
    conn = get_conn()
    try:
        cur = conn.execute(
            "UPDATE jobs SET " + ', '.join(sets) +
            " WHERE id=? AND status NOT IN ('done','failed','cancelled','interrupted')",
            params,
        )
        conn.commit()
        ok = cur.rowcount > 0
    finally:
        conn.close()
    if ok:
        _log_event(rowid, {'event': 'status', 'status': status, 'stage': stage})
    return ok


def set_priority(job_id, priority) -> bool:
    """Reprioritize a live job (Wave-5 Analysis = background). Terminal
    rows are immutable — returns False there."""
    rowid = parse_job_ref(job_id)
    if rowid is None:
        return False
    label, rank = normalize_priority(priority)
    conn = get_conn()
    try:
        cur = conn.execute(
            "UPDATE jobs SET priority=?, priority_label=?, updated_at=CURRENT_TIMESTAMP "
            "WHERE id=? AND status NOT IN ('done','failed','cancelled','interrupted')",
            (rank, label, rowid),
        )
        conn.commit()
        ok = cur.rowcount > 0
    finally:
        conn.close()
    if ok:
        _log_event(rowid, {'event': 'reprioritized', 'priority': label})
    return ok


def set_pending_confirm(job_id, pending: bool):
    rowid = parse_job_ref(job_id)
    if rowid is None:
        return
    conn = get_conn()
    try:
        conn.execute('UPDATE jobs SET pending_confirm=?, updated_at=CURRENT_TIMESTAMP WHERE id=?',
                     (1 if pending else 0, rowid))
        conn.commit()
    finally:
        conn.close()


def mark_cancelled(job_id, error_code: str = 'E_CANCELLED') -> bool:
    return transition(job_id, 'cancelled', stage='done', progress=1.0,
                      error_code=error_code, result='Cancelled')


# ---- phase-1 compat shims (some external callers import these) -------------
def update_status(job_id: int, status: str, result: Optional[str] = None):
    transition(job_id, status, result=result)


def cancel_job(job_id: int) -> bool:
    job = get_job(job_id)
    if not job or job['status'] in TERMINAL:
        return False
    return mark_cancelled(job_id)


def snapshot(row: Dict[str, Any]) -> Dict[str, Any]:
    rowid = row['id']
    return {
        'job': job_ext_id(rowid, row.get('created_at')),
        'id': rowid,
        'task': row.get('task'),
        'text': row.get('text') or row.get('task'),
        'status': row.get('status'),
        'stage': row.get('stage') or 'routing',
        'progress': row.get('progress') or 0.0,
        'priority': row.get('priority_label') or 'normal',
        'source': row.get('source') or 'text',
        'input_lock': bool(row.get('input_lock')),
        'pending_confirm': bool(row.get('pending_confirm')),
        'error_code': row.get('error_code'),
        'result': row.get('result'),
        'session': row.get('session'),
        'seq': row.get('event_seq') or 0,
        'created_at': str(row.get('created_at')),
        'updated_at': str(row.get('updated_at')),
    }

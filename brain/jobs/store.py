"""Job store engine.
Provides CRUD operations and status handling with cancellation.
"""
from . import get_conn
import sqlite3

def _log_event(job_id, event):
    conn = get_conn()
    conn.execute('INSERT INTO journal (job_id, event) VALUES (?, ?)', (job_id, event))
    conn.commit()
    conn.close()

def create_job(task: str, priority: int = 0) -> int:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('INSERT INTO jobs (task, priority, status) VALUES (?, ?, ?)', (task, priority, 'queued'))
    job_id = cur.lastrowid
    conn.commit()
    conn.close()
    _log_event(job_id, 'created')
    return job_id

def get_job(job_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('SELECT * FROM jobs WHERE id=?', (job_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None

def list_jobs():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('SELECT * FROM jobs ORDER BY priority DESC, created_at')
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def update_status(job_id: int, status: str, result: str | None = None):
    conn = get_conn()
    conn.execute('UPDATE jobs SET status=?, result=?, updated_at=CURRENT_TIMESTAMP WHERE id=?', (status, result, job_id))
    conn.commit()
    conn.close()
    _log_event(job_id, f'status:{status}')

def cancel_job(job_id: int):
    job = get_job(job_id)
    if not job:
        return False
    if job['status'] in ('done', 'failed', 'cancelled'):
        return False
    update_status(job_id, 'cancelled')
    return True

"""SQLite crash-safety tests (wave-4 hardening).

- kill-during-write (SIGKILL mid-batch) -> WAL recovery: integrity_check ok,
  only COMMITTED batches survive (row count stays a multiple of 50), the real
  `get_conn`/`init_db` path reopens the DB and stays usable;
- concurrent writers (parent + child) never corrupt;
- a held write lock makes `conversation._persist` drop the batch FAST
  (fail-silent contract, ~500 ms busy_timeout) without breaking later writes.
"""
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import brain.memory as mem
from brain.memory import conversation

_WRITER = Path(__file__).resolve().parent / 'crash_writer.py'
_BATCH = 50


def _count() -> int:
    conn = mem.get_conn()
    try:
        return int(conn.execute('SELECT COUNT(*) FROM memories').fetchone()[0])
    finally:
        conn.close()


def _integrity() -> str:
    conn = mem.get_conn()
    try:
        return str(conn.execute('PRAGMA integrity_check').fetchone()[0])
    finally:
        conn.close()


def _journal() -> str:
    conn = mem.get_conn()
    try:
        return str(conn.execute('PRAGMA journal_mode').fetchone()[0])
    finally:
        conn.close()


def _spawn():
    proc = subprocess.Popen([sys.executable, str(_WRITER), mem.db_path()],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    return proc


def test_kill_during_write_recovers_cleanly():
    before = _count()
    proc = _spawn()
    try:
        # wait until at least one batch committed, then kill DURING the next
        deadline = time.time() + 10
        while time.time() < deadline and _count() == before:
            time.sleep(0.02)
        os.kill(proc.pid, signal.SIGKILL)
    finally:
        proc.wait(timeout=10)                     # reap: zero orphans (Rule 14)
    assert proc.returncode == -signal.SIGKILL

    assert _integrity() == 'ok'                   # WAL recovered, no corruption
    gained = _count() - before
    assert gained >= 0 and gained % _BATCH == 0   # only whole commits survive

    # the real path keeps working: init_db idempotent, writes accepted
    mem.init_db()
    mid = mem.get_conn()
    try:
        mid.execute("INSERT INTO memories (text) VALUES ('post-crash row')")
        mid.commit()
    finally:
        mid.close()
    assert _count() == before + gained + 1
    assert _journal() == 'wal'


def test_concurrent_writers_do_not_corrupt():
    before = _count()
    proc = _spawn()
    try:
        deadline = time.time() + 10
        while time.time() < deadline and _count() == before:
            time.sleep(0.02)
        # parent writes WHILE the child writes (both WAL, busy_timeout set)
        conn = mem.get_conn()
        try:
            conn.executemany(
                "INSERT INTO memories (text) VALUES (?)",
                [(f'parent row {n}',) for n in range(100)])
            conn.commit()
        finally:
            conn.close()
        os.kill(proc.pid, signal.SIGKILL)
    finally:
        proc.wait(timeout=10)
    assert _integrity() == 'ok'
    conn = mem.get_conn()
    try:
        parent_rows = int(conn.execute(
            "SELECT COUNT(*) FROM memories WHERE text LIKE 'parent row %'"
        ).fetchone()[0])
    finally:
        conn.close()
    assert parent_rows == 100                     # every parent write survived
    assert (_count() - before - 100) % _BATCH == 0


def test_persist_drops_fast_on_locked_db_then_recovers(monkeypatch):
    """Fail-silent contract: a held writer lock must NOT hang the flusher —
    the batch drops after the short busy_timeout and later flushes work."""
    # background flusher OFF: this test drives persistence deterministically
    monkeypatch.setattr(conversation, '_ensure_flusher', lambda: None)
    # hold the write lock in a transaction the flusher cannot preempt
    holder = mem.get_conn()
    conversation.on_turn(user='u1', assistant='a1')
    try:
        holder.execute('BEGIN IMMEDIATE')
        holder.execute(
            "INSERT INTO memories (text) VALUES ('lock holder')").fetchone()
        t0 = time.time()
        assert conversation.flush() == 1          # popped, but persist fails
        elapsed = time.time() - t0
        assert elapsed < 3.0                      # ~500 ms busy_timeout, no hang
        assert conversation.turn_count() == 0     # batch dropped (documented)
    finally:
        try:
            holder.rollback()
        except Exception:  # noqa: BLE001
            pass
        holder.close()
    # lock gone -> the NEXT batch persists normally
    conversation.on_turn(user='u2', assistant='a2')
    assert conversation.flush() == 1
    assert conversation.turn_count() == 1

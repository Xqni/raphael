"""Crash-writer child for sqlite crash-safety tests.

Inserts rows in tight committed batches (BEGIN/commit, 50 rows each) until the
parent SIGKILLs it. argv[1] = db path, argv[2] = optional stop-after-N-batches
(default: run forever until killed). Pure stdlib — no brain imports, no ports.
"""
import sqlite3
import sys

db = sys.argv[1]
stop_after = int(sys.argv[2]) if len(sys.argv) > 2 else 0

conn = sqlite3.connect(db, timeout=30.0)
conn.isolation_level = None        # full manual BEGIN/commit control
conn.execute('PRAGMA journal_mode=WAL')
conn.execute('PRAGMA synchronous=NORMAL')
i = 0
batches = 0
while True:
    conn.execute('BEGIN')
    for _ in range(50):
        i += 1
        conn.execute(
            "INSERT INTO memories (text, source, category) "
            "VALUES (?, 'observed', 'fact')", (f'crash row {i}',))
    conn.commit()
    batches += 1
    if stop_after and batches >= stop_after:
        break
conn.close()

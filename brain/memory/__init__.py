"""Memory module: SQLite-backed storage for jobs and task journal.
Durable + crash-safe: WAL journaling, synchronous NORMAL, busy timeout, and
additive schema migration so phase-1 DBs keep working.
DB path override: RAPHAEL_DB_PATH (tests point at a temp file; the real
runtime DB stays brain/memory/memory.db).
"""
import os
import sqlite3

_DEFAULT = os.path.join(os.path.dirname(__file__), 'memory.db')


def db_path() -> str:
    return os.environ.get('RAPHAEL_DB_PATH') or _DEFAULT


def get_conn():
    conn = sqlite3.connect(db_path(), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    conn.execute('PRAGMA busy_timeout=30000')
    return conn


def init_db():
    conn = get_conn()
    cur = conn.cursor()
    # Jobs table (phase-1 schema)
    cur.execute('''
    CREATE TABLE IF NOT EXISTS jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task TEXT NOT NULL,
        priority INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'queued',
        result TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    # Task journal (append-only event log; entries are JSON job_event frames)
    cur.execute('''
    CREATE TABLE IF NOT EXISTS journal (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER,
        event TEXT NOT NULL,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(job_id) REFERENCES jobs(id)
    )
    ''')
    # Global mode flags (pause/private/watch) — persisted across restarts
    cur.execute('''
    CREATE TABLE IF NOT EXISTS state (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    # Additive migration for phase-2 engine columns
    cols = {r[1] for r in cur.execute('PRAGMA table_info(jobs)')}
    for name, ddl in (
        ('text', "ALTER TABLE jobs ADD COLUMN text TEXT"),
        ('source', "ALTER TABLE jobs ADD COLUMN source TEXT DEFAULT 'text'"),
        ('stage', "ALTER TABLE jobs ADD COLUMN stage TEXT DEFAULT 'routing'"),
        ('progress', "ALTER TABLE jobs ADD COLUMN progress REAL DEFAULT 0.0"),
        ('priority_label', "ALTER TABLE jobs ADD COLUMN priority_label TEXT DEFAULT 'normal'"),
        ('input_lock', "ALTER TABLE jobs ADD COLUMN input_lock INTEGER NOT NULL DEFAULT 0"),
        ('pending_confirm', "ALTER TABLE jobs ADD COLUMN pending_confirm INTEGER NOT NULL DEFAULT 0"),
        ('error_code', "ALTER TABLE jobs ADD COLUMN error_code TEXT"),
        ('session', "ALTER TABLE jobs ADD COLUMN session TEXT"),
        ('event_seq', "ALTER TABLE jobs ADD COLUMN event_seq INTEGER NOT NULL DEFAULT 0"),
    ):
        if name not in cols:
            cur.execute(ddl)
    conn.commit()
    conn.close()


# Initialise on import
init_db()

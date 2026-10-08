"""Memory module: SQLite-backed storage for jobs and task journal.
Durable + crash-safe: WAL journaling, synchronous NORMAL, busy timeout, and
additive schema migration so phase-1 DBs keep working.
DB path: RAPHAEL_DB_PATH (tests point at a temp file) -> else the INSTANCE
DATA-DIR (`~/.raphael/<instance>/memory.db`, INTERFACES §d) — AUD-15: the DB
is checkout-local no more; a legacy checkout DB is moved there once, and the
file (+ WAL/SHM) is chmod 0600 (personal data, owner-only).
"""
import os
import shutil
import sqlite3

_DEFAULT = os.path.join(os.path.dirname(__file__), 'memory.db')   # legacy
_migrated = False


def db_path() -> str:
    env = os.environ.get('RAPHAEL_DB_PATH')
    if env:
        return env
    global _migrated
    try:
        from .. import config as appcfg
        target = str(appcfg.data_dir() / 'memory.db')
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if not _migrated:
            _migrated = True
            # one-time legacy migration: checkout DB -> data-dir (AUD-15)
            if not os.path.exists(target) and os.path.exists(_DEFAULT):
                try:
                    shutil.move(_DEFAULT, target)
                    for suf in ('-wal', '-shm'):
                        if os.path.exists(_DEFAULT + suf):
                            shutil.move(_DEFAULT + suf, target + suf)
                except OSError:
                    # move failed: keep the legacy file (data safety first)
                    return _DEFAULT
        return target
    except Exception:  # noqa: BLE001 — config trouble: legacy path still works
        return _DEFAULT


def _harden_perms(path: str) -> None:
    """AUD-15: personal data files are owner-only (0600), best-effort."""
    for p in (path, path + '-wal', path + '-shm'):
        try:
            if os.path.exists(p):
                os.chmod(p, 0o600)
        except OSError:
            pass


def get_conn():
    conn = sqlite3.connect(db_path(), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    conn.execute('PRAGMA busy_timeout=30000')
    _harden_perms(db_path())
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
    # Wave-3 additive memory schema (tools-memory lane; IF NOT EXISTS only)
    from .schema import migrate as _schema_migrate
    _schema_migrate(conn)
    conn.commit()
    conn.close()


# Initialise on import
init_db()

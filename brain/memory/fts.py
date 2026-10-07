"""FTS5 index management for `memories` (tools-memory lane).

External-content FTS5 table + sync triggers, created during schema migration.
FTS5 availability is DETECTED, never assumed — a build without it gets
`available() == False` and `retrieval.py` falls back to keyword scoring
behind the same API (cloud_temp: correctness over optimization).

Imports stdlib only: `schema.migrate()` runs while `brain.memory.__init__`
is still initializing.
"""
import sqlite3
import threading

_lock = threading.Lock()
_state = {'checked': False, 'ok': False}


def ensure(conn) -> bool:
    """Create the FTS table + triggers once (idempotent). Returns availability."""
    with _lock:
        if _state['checked']:
            return _state['ok']
        try:
            conn.execute('''
            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                text, content='memories', content_rowid='id',
                tokenize='porter unicode61')
            ''')
            conn.execute('''
            CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                INSERT INTO memories_fts(rowid, text) VALUES (new.id, new.text);
            END
            ''')
            conn.execute('''
            CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                INSERT INTO memories_fts(memories_fts, rowid, text)
                VALUES ('delete', old.id, old.text);
            END
            ''')
            conn.execute('''
            CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
                INSERT INTO memories_fts(memories_fts, rowid, text)
                VALUES ('delete', old.id, old.text);
                INSERT INTO memories_fts(rowid, text) VALUES (new.id, new.text);
            END
            ''')
            conn.commit()
            _state['ok'] = True
        except sqlite3.OperationalError:
            _state['ok'] = False          # no FTS5 in this build -> fallback
        except Exception:  # noqa: BLE001 — anything else: not fatal either
            _state['ok'] = False
        _state['checked'] = True
        return _state['ok']


def available() -> bool:
    """Cached result of ensure() — safe before any connection exists (False)."""
    return bool(_state['ok'])


def integrity_check(conn) -> str:
    """FTS5 external-content check against `memories`. Returns 'ok' or a
    description of the mismatch. Never raises."""
    try:
        conn.execute("INSERT INTO memories_fts(memories_fts, rank) "
                     "VALUES ('integrity-check', 1)")
        return 'ok'
    except Exception as e:  # noqa: BLE001 — mismatch/corruption -> reported
        return f'mismatch: {type(e).__name__}: {e}'


def rebuild(conn) -> bool:
    """Rebuild the index FROM the content table (the corruption cure).
    Returns True on success, False when FTS5 is unavailable/broken."""
    try:
        conn.execute("INSERT INTO memories_fts(memories_fts) "
                     "VALUES ('rebuild')")
        conn.commit()
        return True
    except Exception:  # noqa: BLE001
        return False


def reset_for_tests() -> None:
    with _lock:
        _state['checked'] = False
        _state['ok'] = False

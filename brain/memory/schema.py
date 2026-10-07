"""Additive schema migration for the memory DB (tools-memory lane).

`migrate(conn)` is called from `brain/memory/__init__.py::init_db()` on every
open. Rules:
- ADDITIVE ONLY: `CREATE ... IF NOT EXISTS` / guarded `ALTER` — never touch or
  recreate the existing `jobs` / `journal` / `state` tables (brain-core owns
  their semantics); phase-1 DBs must keep working.
- this module imports ONLY stdlib (it runs while `brain.memory.__init__` is
  still initializing — no intra-package imports).
- DDL lands here per wave-3 task; keep each block together with a comment.
"""


def migrate(conn) -> None:
    cur = conn.cursor()

    # --- conversation turns (brain-core producer seam, request
    # brain-core__to__tools-memory__conversation-hook.md ACCEPTED 2026-10-07) --
    cur.execute('''
    CREATE TABLE IF NOT EXISTS conversation_turns (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts INTEGER NOT NULL,
        user TEXT NOT NULL,
        assistant TEXT NOT NULL,
        job TEXT,
        task_kind TEXT
    )
    ''')
    cur.execute('''
    CREATE INDEX IF NOT EXISTS idx_conv_turns_ts ON conversation_turns(ts)
    ''')

    # --- memories (addendum §3, Odysseus semantics) --------------------------
    # owner is on EVERY row and EVERY query filters it (PR #2404 leak lesson).
    cur.execute('''
    CREATE TABLE IF NOT EXISTS memories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        text TEXT NOT NULL,
        ts TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        source TEXT NOT NULL DEFAULT 'observed',   -- user | observed | imported
        category TEXT NOT NULL DEFAULT 'fact',     -- identity|contact|preference|fact|task
        pinned INTEGER NOT NULL DEFAULT 0,
        owner TEXT NOT NULL DEFAULT 'local-user',
        uses INTEGER NOT NULL DEFAULT 0,
        last_used TIMESTAMP
    )
    ''')
    cur.execute('''
    CREATE INDEX IF NOT EXISTS idx_memories_owner ON memories(owner, category)
    ''')

    # FTS5 index (external content = memories) + sync triggers. Availability is
    # detected, not assumed: if this sqlite build lacks FTS5, fts.ensure()
    # reports False and retrieval falls back to keyword scoring (same API).
    from . import fts as _fts
    _fts.ensure(conn)

    # --- conversation summaries (rolling, older turns -> compact recall) -----
    # covers_from/covers_to are conversation_turns.id bounds (NOT timestamps —
    # same-second turns would otherwise be skipped forever after coverage).
    cur.execute('''
    CREATE TABLE IF NOT EXISTS conversation_summaries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session TEXT,
        summary TEXT NOT NULL,
        covers_from INTEGER,
        covers_to INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    # --- skills index (addendum §4 — sidecar counters; the FILE is the
    # source of truth for content/status/confidence, this table mirrors it
    # + owns usage counters and dedup bookkeeping) ---------------------------
    cur.execute('''
    CREATE TABLE IF NOT EXISTS skills_index (
        name TEXT PRIMARY KEY,
        path TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        category TEXT NOT NULL DEFAULT 'general',
        tags TEXT NOT NULL DEFAULT '[]',
        status TEXT NOT NULL DEFAULT 'draft',
        confidence REAL NOT NULL DEFAULT 0.0,
        source TEXT NOT NULL DEFAULT 'learned',
        content_hash TEXT NOT NULL DEFAULT '',
        dedup_hits INTEGER NOT NULL DEFAULT 0,
        uses INTEGER NOT NULL DEFAULT 0,
        last_used TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP
    )
    ''')

    # --- plugins index (user-authored manifests; mirrored for visibility) ----
    cur.execute('''
    CREATE TABLE IF NOT EXISTS plugins_index (
        name TEXT PRIMARY KEY,
        path TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        version TEXT NOT NULL DEFAULT '',
        enabled INTEGER NOT NULL DEFAULT 0,
        tools TEXT NOT NULL DEFAULT '[]',
        last_error TEXT,
        updated_at TIMESTAMP
    )
    ''')

    # --- schedules (timers / reminders / recurring) --------------------------
    # due_at is INTEGER epoch; recurring rows stay 'pending' and advance
    # due_at after each fire; attempts/last_error make failed fires visible.
    cur.execute('''
    CREATE TABLE IF NOT EXISTS schedules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT NOT NULL,                    -- timer | reminder | recurring
        due_at INTEGER NOT NULL,
        label TEXT NOT NULL DEFAULT '',
        pattern TEXT,                          -- 'every 30m' | 'daily 08:00'
        payload TEXT NOT NULL DEFAULT '',      -- text submitted on fire
        status TEXT NOT NULL DEFAULT 'pending',-- pending | fired | cancelled | error
        attempts INTEGER NOT NULL DEFAULT 0,
        last_error TEXT,
        created_at INTEGER NOT NULL,
        fired_at INTEGER
    )
    ''')
    cur.execute('''
    CREATE INDEX IF NOT EXISTS idx_schedules_due
    ON schedules(status, due_at)
    ''')

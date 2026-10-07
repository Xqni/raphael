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

    # (Wave-3 tasks add: conversation_summaries, skills_index, plugins_index,
    #  schedules — same additive pattern.)

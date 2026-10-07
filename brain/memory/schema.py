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
    # (Wave-3 tasks add: memories + FTS5, conversation_summaries, skills_index,
    #  plugins_index, schedules — same additive pattern.)

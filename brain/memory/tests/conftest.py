"""tools-memory lane test environment (brain/memory/tests).

Deliberately NO __init__.py in this directory: pytest must import this
conftest WITHOUT walking through `brain.memory.__init__` (which runs
`init_db()` at import — it must see RAPHAEL_DB_PATH already set, never the
real runtime DB).

Order matters: env vars + repo-root sys.path are set before any repo import.
"""
import os
import sys
import tempfile
from pathlib import Path

_fd, _db = tempfile.mkstemp(prefix='raphael-tools-mem-db-')
os.close(_fd)
os.environ['RAPHAEL_DB_PATH'] = _db
os.environ.setdefault('RAPHAEL_INSTANCE', 'tools-memory')      # INTERFACES §d
os.environ.setdefault('RAPHAEL_DISABLE_ROUTER', '1')           # never a live provider
os.environ.setdefault('RAPHAEL_CONFIRM_TIMEOUT_S', '2')

_REPO_ROOT = Path(__file__).resolve().parents[3]   # tests -> memory -> brain -> root
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_state():
    """Per-test: no leftover flusher threads (Rule 14) + empty memory tables."""
    yield
    try:
        from brain.memory import conversation, get_conn
        conversation.shutdown(timeout=2.0)
        conversation.clear_turns()
        conn = get_conn()
        try:
            conn.execute('DELETE FROM memories')
            conn.commit()
        finally:
            conn.close()
    except Exception as _e:  # noqa: BLE001 — loud, hermeticity must not hide
        print(f'[conftest] state cleanup failed: {type(_e).__name__}: {_e}',
              flush=True)


@pytest.fixture(scope='session', autouse=True)
def _cleanup_db():
    yield
    for p in (_db, _db + '-wal', _db + '-shm'):
        try:
            os.remove(p)
        except OSError:
            pass

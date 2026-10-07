"""Isolation for computer-use tool tests (AGENT_RULES §5): instance
isolation via RAPHAEL_INSTANCE=computer-use, router disabled, temp DB."""
import os
import tempfile

os.environ.setdefault("RAPHAEL_INSTANCE", "computer-use")
os.environ.setdefault("RAPHAEL_DISABLE_ROUTER", "1")
os.environ.setdefault("RAPHAEL_CONFIRM_TIMEOUT_S", "2")

_fd, _db = tempfile.mkstemp(prefix="raphael-cu-tools-db-")
os.close(_fd)
os.environ["RAPHAEL_DB_PATH"] = _db

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_deps():
    """Every test starts and ends with clean wiring (no global bleed)."""
    from brain.tools.computer_use import wiring
    wiring.reset_deps()
    yield
    wiring.reset_deps()


@pytest.fixture(scope="session", autouse=True)
def _cleanup_db():
    yield
    for p in (_db, _db + "-wal", _db + "-shm"):
        try:
            os.remove(p)
        except OSError:
            pass

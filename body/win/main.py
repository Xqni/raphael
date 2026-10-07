"""Raphael Windows Body entry point.

- Ensures a single instance via a file lock.
- Starts the async WS client.
- Logs to stdout (supervisor captures stdout).
"""
import sys
import os
import asyncio
import atexit
import pathlib

# Simple cross‑process lock using a lock file.
# Instance isolation (INTERFACES §d): %TMP%\raphael_body.lock for main,
# %TMP%\raphael_body_<instance>.lock when RAPHAEL_INSTANCE is set.
try:
    from . import instance as _instance
except ImportError:          # script mode (supervisor: python body/win/main.py)
    import instance as _instance

LOCK_PATH = _instance.body_lock_path()

def _pid_alive(pid: int) -> bool:
    """True if the lock owner process still exists (Windows)."""
    if os.name != 'nt':
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    import ctypes
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if handle:
        kernel32.CloseHandle(handle)
        return True
    return False


def obtain_lock() -> bool:
    for _attempt in range(2):
        try:
            # O_EXCL|O_CREAT ensures failure if file exists.
            fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode('ascii'))
            os.close(fd)
            return True
        except FileExistsError:
            # Stale lock: a force-killed body never ran atexit — if the owner
            # is dead, reclaim instead of staying "already running" forever.
            try:
                owner = int((LOCK_PATH.read_text() or '').strip() or 0)
            except (OSError, ValueError):
                owner = 0
            if owner and _pid_alive(owner):
                return False
            try:
                LOCK_PATH.unlink()
            except OSError:
                return False
    return False

def release_lock():
    try:
        LOCK_PATH.unlink()
    except FileNotFoundError:
        pass

async def run_body():
    try:
        from .ws_client import start_client
    except ImportError:
        # Script mode (supervisor runs `python body/win/main.py`) has no
        # package context — fall back to an absolute import via sys.path[0].
        from ws_client import start_client
    await start_client()

def main() -> int:
    if not obtain_lock():
        # Second instance – exit silently with success code as supervisor expects.
        print('Another Raphael body instance is already running – exiting.', flush=True)
        return 0
    atexit.register(release_lock)
    try:
        asyncio.run(run_body())
    except KeyboardInterrupt:
        pass
    return 0

if __name__ == "__main__":
    sys.exit(main())

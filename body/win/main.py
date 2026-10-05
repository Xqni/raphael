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
LOCK_PATH = pathlib.Path(os.getenv('TMP', '/tmp')) / 'raphael_body.lock'

def obtain_lock() -> bool:
    try:
        # O_EXCL|O_CREAT ensures failure if file exists.
        fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        )
        os.close(fd)
        return True
    except FileExistsError:
        return False

def release_lock():
    try:
        LOCK_PATH.unlink()
    except FileNotFoundError:
        pass

async def run_body():
    from .ws_client import start_client
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

"""Input-lock resource arbitration (ARCHITECTURE §4, PROTOCOL §7).

Single-owner access to mouse/keyboard/screen between jobs. Brain-arbitrated
FIFO mutex:

- exactly ONE job holds the lock at a time;
- `lock:true` work from other jobs queues FIFO behind the current owner;
- the lock is NEVER stolen or transferred mid-hold — only the owner's job
  (or its cancellation path) releases it;
- a job cancelled while queued for the lock is dropped from the queue cleanly;
- non-GUI tools (URL open, shell without input, files, timers, API) never
  touch this lock.
"""
import asyncio
from collections import deque
from typing import Deque, Optional, Tuple


class InputLock:
    def __init__(self):
        self._owner: Optional[int] = None
        self._waiters: Deque[Tuple[int, "asyncio.Future"]] = deque()

    @property
    def owner(self) -> Optional[int]:
        return self._owner

    @property
    def waiters(self) -> int:
        return len(self._waiters)

    def is_held_by(self, job_id: int) -> bool:
        return self._owner == job_id

    def busy(self) -> bool:
        return self._owner is not None or bool(self._waiters)

    async def acquire(self, job_id: int) -> bool:
        """Queue FIFO; returns True when this job owns the lock.
        Cancellation while queued removes the waiter (no orphan futures)."""
        if self._owner is None and not self._waiters:
            self._owner = job_id
            return True
        fut: "asyncio.Future" = asyncio.get_running_loop().create_future()
        self._waiters.append((job_id, fut))
        try:
            await fut
        except asyncio.CancelledError:
            self._waiters = deque(
                (j, f) for (j, f) in self._waiters if f is not fut and not f.cancelled()
            )
            raise
        return self._owner == job_id

    def release(self, job_id: int) -> bool:
        """Release only if job_id owns the lock. Hands off to the next FIFO
        waiter. Returns True only when job_id was the owner."""
        if self._owner != job_id:
            return False
        self._owner = None
        while self._waiters:
            jid, fut = self._waiters.popleft()
            if fut.done():
                continue
            self._owner = jid
            fut.set_result(True)
            break
        return True

    def force_release(self) -> bool:
        """Emergency release (kill_gui / shutdown). Drops waiters too."""
        had_owner = self._owner is not None
        self._owner = None
        while self._waiters:
            _, fut = self._waiters.popleft()
            if not fut.done():
                fut.cancel()
        return had_owner

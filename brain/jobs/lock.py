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
        # Wave 5U P0.6: idle signal for ADMISSION parking — set exactly when
        # nobody owns and nobody queues the lock (dead waiters drained).
        self._idle: "asyncio.Event" = asyncio.Event()
        self._idle.set()

    def _sync_idle(self) -> None:
        self._waiters = deque(
            (j, f) for (j, f) in self._waiters if not f.done() and not f.cancelled())
        if self._owner is None and not self._waiters:
            self._idle.set()
        else:
            self._idle.clear()

    async def wait_until_free(self) -> None:
        """P0.6 admission: wait until NOBODY owns or queues the lock.
        (Busy-wait free; re-checks after every wake because a promotion can
        re-busy the lock between wake and check.)"""
        while True:
            self._sync_idle()
            if self._idle.is_set():
                return
            await self._idle.wait()

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
        Cancellation while queued removes the waiter (no orphan futures).

        Fairness guard (Wave 3 polish): a job can only take the lock
        instantly when NOBODY is queued — in the transient ownerless state
        with waiters present, the oldest WAITING job is promoted instead of
        letting the newcomer jump the queue (starvation)."""
        self._sync_idle()
        if self._owner is None:
            if not self._waiters:
                self._owner = job_id
                self._idle.clear()
                return True
            # ownerless WITH waiters: promote the oldest live waiter; drain
            # dead (cancelled) entries first. If every waiter is dead the
            # newcomer takes the free lock outright.
            promoted = None
            while self._waiters:
                jid0, fut0 = self._waiters.popleft()
                if fut0.done():
                    continue
                promoted = (jid0, fut0)
                break
            if promoted is None:
                self._owner = job_id
                self._idle.clear()
                return True
            self._owner = promoted[0]
            promoted[1].set_result(True)
            # fall through — the newcomer queues behind the promoted holder
        fut: "asyncio.Future" = asyncio.get_running_loop().create_future()
        self._waiters.append((job_id, fut))
        self._idle.clear()
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
        self._sync_idle()
        return True

    def force_release(self) -> bool:
        """Emergency release (kill_gui / shutdown). Drops waiters too."""
        had_owner = self._owner is not None
        self._owner = None
        while self._waiters:
            _, fut = self._waiters.popleft()
            if not fut.done():
                fut.cancel()
        self._sync_idle()
        return had_owner

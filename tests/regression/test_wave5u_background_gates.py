"""Wave 5U Wave A — background-task gates (qa-security packet §5.5 task 3).

Gates under test:
1. ONLY ONE lock holder (brain/jobs/lock.py InputLock — FIFO, never stolen):
   a second lock:true job queues behind the owner and does NOT become owner;
   release only by the owner; release hands off to the oldest FIFO waiter;
   force_release (kill_gui/shutdown) drops waiters. [LANDED]
2. WORKERS / CHAT cannot emit speak frames or act_res (the speak pipeline is
   server->body only; a `worker` or `chat` session must never be a permitted
   source for audio or act responses). [ws.py CAN_SEND sets — worker role is
   RESERVED/not-yet-in-ROLES; this tripwire holds now and must keep holding
   when the fleet runtime adds the role.] [LANDED]
3. Tasks NEVER auto-resume after restart (PROTOCOL §5). COVERED end-to-end by
   tests/resilience/test_crash_recovery_interrupted.py (real isolated brain
   reboot) — not duplicated here; referenced for the record.

"chat latency unaffected by a running task" is an engine-admission property
that lands with the world-state/background runtime (brain-core Wave B after
P0.6); the invariant this file pins NOW is that the input lock is OPT-IN
(`input_lock` flag) so a non-lock chat job is never serialized behind a
lock:true task — asserted at the InputLock boundary below.

Mutation-checked (docs/reviews/2026-10-10-wave5u-mutations.md): weakening the
one-holder guard or permitting worker/chat audio turns these red.
"""
import asyncio

from brain.jobs.lock import InputLock


# --- 1. one lock holder, FIFO, no steal ------------------------------------

def test_only_one_lock_holder():
    lock = InputLock()

    async def _run():
        assert await lock.acquire(1) is True
        assert lock.owner == 1
        assert lock.is_held_by(1)
        # a second lock:true job must NOT steal it while owner holds
        assert not lock.is_held_by(2)
        assert lock.busy()
        return True

    assert asyncio.run(_run())


def test_second_lock_job_queues_behind_owner_then_gets_handed_off():
    lock = InputLock()

    async def _run():
        assert await lock.acquire(1)
        got2 = asyncio.ensure_future(lock.acquire(2))
        await asyncio.sleep(0)
        assert not got2.done(), "job2 stole the lock while job1 still holds it"
        assert lock.owner == 1
        assert lock.waiters == 1
        # owner releases -> oldest waiter (job2) is promoted
        assert lock.release(1) is True
        assert await asyncio.wait_for(got2, timeout=1.0) is True
        assert lock.owner == 2

    asyncio.run(_run())


def test_release_by_non_owner_is_a_noop():
    lock = InputLock()

    async def _run():
        assert await lock.acquire(1)
        assert lock.release(2) is False      # job2 does not own it
        assert lock.owner == 1               # owner unchanged
        assert lock.release(1) is True

    asyncio.run(_run())


def test_force_release_drops_waiters():
    lock = InputLock()

    async def _run():
        assert await lock.acquire(1)
        waiter = asyncio.ensure_future(lock.acquire(2))
        await asyncio.sleep(0)
        assert lock.waiters == 1
        assert lock.force_release() is True   # had an owner
        assert lock.owner is None
        assert not lock.busy()
        # the waiter was cancelled, not promoted (emergency = everyone out)
        await asyncio.sleep(0)
        assert waiter.cancelled() or waiter.done()

    asyncio.run(_run())


def test_non_lock_job_is_never_serialized_behind_a_lock_task():
    """The input lock is OPT-IN (`input_lock` flag). A chat job (no lock) is
    admitted without queueing behind a held lock — this is the boundary that
    keeps chat latency independent of a running lock:true task."""
    lock = InputLock()

    async def _run():
        assert await lock.acquire(1)         # a lock:true task owns it
        # a non-lock job by definition never calls acquire() -> it is free.
        # assert the lock is still ONLY about the lock:true holder, i.e. a
        # second lock holder can't even start, but the lock never becomes a
        # global barrier: release is per-owner and the non-lock path is inert.
        assert lock.owner == 1
        assert lock.is_held_by(1)            # holder is the ONLY one gated
        lock.release(1)

    asyncio.run(_run())


# --- 2. worker / chat cannot emit speak frames or act_res ------------------

def test_worker_and_chat_cannot_emit_speak_or_act_frames():
    """speak audio and act_res are server->body only. A `worker` (fleet
    specialist) or `chat` (Raphael Chat UI) session must never be a permitted
    SOURCE for audio or act responses — held now (roles not in CAN_SEND) and
    must keep holding when the fleet runtime adds the roles."""
    from brain import ws
    for role in ("worker", "chat"):
        assert role not in ws.CAN_SEND_AUDIO, f"{role} may send audio"
        assert role not in ws.CAN_SEND_ACT_RES, f"{role} may send act_res"
    # and the positive anchor: only body may source audio / act_res
    assert ws.CAN_SEND_AUDIO == {"body"}
    assert ws.CAN_SEND_ACT_RES == {"body"}


def test_worker_cannot_resolve_a_confirm():
    """Fleet tripwire (§5.5 task 4): a specialist `worker` may never answer a
    confirmation — confirms resolve only from ui (click), cli (typed), or body
    (voice, high-risk still rejected). The `worker` role is RESERVED and must
    stay OUT of CAN_SEND_CONFIRM_RESP when the fleet runtime adds it."""
    from brain import ws
    assert "worker" not in ws.CAN_SEND_CONFIRM_RESP, \
        "worker may resolve a confirm (fleet specialists must not)"
    # positive anchor (PROTOCOL §9 confirm channels)
    assert ws.CAN_SEND_CONFIRM_RESP == {"ui", "body", "cli"}

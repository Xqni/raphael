"""Concurrent job engine (PROTOCOL §5, ARCHITECTURE §4).

- unique canonical job ids `j_YYYYMMDD_NNNN`
- statuses: queued | running | awaiting_confirm | done | failed | cancelled |
  interrupted (terminal states immutable, enforced in store.transition)
- priorities: user_facing | normal | background — preempts ADMISSION ORDER only,
  never in-flight execution, never the input lock
- reliable cancellation: per-job asyncio task + cancel(); no orphaned tasks
  (workers re-raise only their own cancellation; shutdown gathers everything);
  terminal-state races resolved by guarded SQL transitions
- per-job monotonic event seq for job_event frames (clients drop stale frames)
- input-lock arbitration via brain.jobs.lock.InputLock (FIFO, never stolen)
- crash recovery: non-terminal rows found at startup → `interrupted`
  (reported, never auto-resumed — PROTOCOL §5)
"""
import asyncio
import os
from typing import Any, Callable, Dict, List, Optional

from .. import confirm as confirm_mod
from . import store
from .lock import InputLock


class JobEngine:
    def __init__(self):
        self._queue: "asyncio.PriorityQueue" = asyncio.PriorityQueue()
        self._tasks: Dict[int, asyncio.Task] = {}
        self._workers: List[asyncio.Task] = []
        self._submit_seq = 0
        self._running = False
        self._pause_event: Optional[asyncio.Event] = None
        self.lock = InputLock()
        self.confirmer = confirm_mod.Confirmer()
        self.runner: Optional[Callable[[Dict[str, Any]], Any]] = None
        # narration hooks (ws hub wires these; None = unit-test mode)
        self.sink: Optional[Callable[[Dict[str, Any]], Any]] = None
        self.on_state: Optional[Callable[[Dict[str, Any]], Any]] = None

    # ---- lifecycle ---------------------------------------------------------
    @property
    def started(self) -> bool:
        return self._running

    def start(self, workers: Optional[int] = None):
        if self._running:
            return
        self._mark_interrupted()
        self._pause_event = asyncio.Event()
        self._pause_event.set()
        n = workers or int(os.environ.get('RAPHAEL_JOBS_MAX_CONCURRENT', '8'))
        self._workers = [asyncio.create_task(self._worker_loop(i), name=f'brain-worker-{i}')
                         for i in range(n)]
        self._running = True

    def pause(self):
        if self._pause_event is not None:
            self._pause_event.clear()

    def resume(self):
        if self._pause_event is not None:
            self._pause_event.set()

    @property
    def paused(self) -> bool:
        return self._pause_event is not None and not self._pause_event.is_set()

    async def shutdown(self):
        self._running = False
        for t in list(self._tasks.values()):
            t.cancel()
        for w in self._workers:
            w.cancel()
        pending = list(self._tasks.values()) + list(self._workers)
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        self._tasks.clear()
        self._workers.clear()
        self.lock.force_release()

    def _mark_interrupted(self):
        """Startup crash recovery: report non-terminal jobs as interrupted."""
        for job in store.list_jobs():
            if job['status'] in store.TERMINAL:
                continue
            store.transition(job['id'], 'interrupted', stage='done',
                             error_code='E_INTERNAL',
                             result='brain restarted mid-run (not auto-resumed)')
            job = store.get_job(job['id']) or job
            self.emit_event(job, 'interrupted', stage='done', progress=1.0,
                            text='Interrupted by brain restart', error_code='E_INTERNAL')

    # ---- submission --------------------------------------------------------
    async def submit(self, text: str, priority='normal', source: str = 'text',
                     input_lock: bool = False, session: Optional[str] = None,
                     task: Optional[str] = None) -> Dict[str, Any]:
        snap = store.create_job(text=text, priority=priority, source=source,
                                input_lock=input_lock, session=session, task=task)
        self._submit_seq += 1
        rank = store.PRIORITY_RANK.get(snap['priority'], 1)
        await self._queue.put((rank, self._submit_seq, snap['id']))
        self.emit_event(snap, 'queued', stage='routing', progress=0.0,
                        text=(snap.get('text') or '')[:160])
        return snap

    # ---- workers -----------------------------------------------------------
    async def _worker_loop(self, idx: int):
        while self._running or not self._queue.empty():
            if self._pause_event is not None:
                await self._pause_event.wait()
            try:
                _rank, _seq, rowid = await asyncio.wait_for(self._queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                raise
            job = store.get_job(rowid)
            if not job or job['status'] != 'queued':
                self._queue.task_done()
                continue
            if self._pause_event is not None:
                # re-check pause after dequeue: pause() must gate admission
                await self._pause_event.wait()
                job = store.get_job(rowid)
                if not job or job['status'] != 'queued':
                    self._queue.task_done()
                    continue
            task = asyncio.create_task(self._run_job(rowid), name=f'job-{job["job"]}')
            self._tasks[rowid] = task
            try:
                await task
            except asyncio.CancelledError:
                if task.cancelled():
                    # the JOB was cancelled (engine.cancel) — worker survives
                    pass
                else:
                    # the WORKER is shutting down — cancel job, no orphans
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    raise
            finally:
                self._tasks.pop(rowid, None)
                try:
                    self._queue.task_done()
                except ValueError:
                    pass

    async def _run_job(self, rowid: int):
        job = store.get_job(rowid)
        if not job or job['status'] != 'queued':
            return
        store.transition(rowid, 'running', stage='routing', progress=0.05)
        job = store.get_job(rowid)
        self.emit_event(job, 'running', stage='routing', progress=0.05,
                        text='Working on it')
        try:
            if self.runner is None:
                store.transition(rowid, 'failed', stage='done', progress=1.0,
                                 error_code='E_INTERNAL', result='no runner wired')
                self.emit_event(store.get_job(rowid), 'failed', stage='done',
                                progress=1.0, text='Engine has no runner wired',
                                error_code='E_INTERNAL')
                return
            await self.runner(job)
            # fallback: runner returned without terminal state -> done
            final = store.get_job(rowid)
            if final and final['status'] not in store.TERMINAL:
                store.transition(rowid, 'done', stage='done', progress=1.0,
                                 result=final.get('result') or 'Task complete')
                final = store.get_job(rowid)
                self.emit_event(final, 'done', stage='done', progress=1.0,
                                text=(final.get('result') or 'Task complete')[:160])
        except asyncio.CancelledError:
            # reliable cancellation: release resources, terminal state, event
            if self.lock.is_held_by(rowid):
                self.lock.release(rowid)
            self.confirmer.cancel(rowid)
            store.set_pending_confirm(rowid, False)
            if store.transition(rowid, 'cancelled', stage='done', progress=1.0,
                                error_code='E_CANCELLED', result='Cancelled'):
                self.emit_event(store.get_job(rowid), 'cancelled', stage='done',
                                progress=1.0, text='Cancelled', error_code='E_CANCELLED')
            raise
        except Exception as e:  # noqa: BLE001 — runner errors must not kill workers
            if self.lock.is_held_by(rowid):
                self.lock.release(rowid)
            self.confirmer.cancel(rowid)
            store.transition(rowid, 'failed', stage='done', progress=1.0,
                             error_code='E_INTERNAL', result=str(e)[:300])
            self.emit_event(store.get_job(rowid), 'failed', stage='done',
                            progress=1.0, text=f'Failed: {type(e).__name__}',
                            error_code='E_INTERNAL')

    # ---- cancellation ------------------------------------------------------
    def cancel(self, ref, scope: str = 'full') -> Optional[Dict[str, Any]]:
        rowid = store.parse_job_ref(ref)
        if rowid is None:
            return None
        job = store.get_job(rowid)
        if not job:
            return None
        if job['status'] in store.TERMINAL:
            return job  # terminal states immutable — report as-is
        if scope == 'gui':
            # PROTOCOL §3: scope gui releases the input lock only
            if self.lock.is_held_by(rowid):
                self.lock.release(rowid)
            self.emit_event(job, job['status'],
                            text='Input lock released (scope=gui)')
            return store.get_job(rowid)
        task = self._tasks.get(rowid)
        if task is not None and not task.done():
            task.cancel()
        else:
            # queued (not yet picked by a worker): cancel now; worker skips it
            self.confirmer.cancel(rowid)
            store.set_pending_confirm(rowid, False)
            if store.transition(rowid, 'cancelled', stage='done', progress=1.0,
                                error_code='E_CANCELLED', result='Cancelled'):
                self.emit_event(store.get_job(rowid), 'cancelled', stage='done',
                                progress=1.0, text='Cancelled', error_code='E_CANCELLED')
        return store.get_job(rowid)

    def cancel_all(self, scope: str = 'full') -> int:
        n = 0
        for job in store.list_jobs():
            if job['status'] in store.TERMINAL:
                continue
            self.cancel(job['job'], scope=scope)
            n += 1
        return n

    def cancel_session(self, sid: str) -> int:
        """PROTOCOL §1: on WS disconnect the server cancels that session's tasks."""
        n = 0
        for job in store.list_jobs():
            if job['status'] in store.TERMINAL or job.get('session') != sid:
                continue
            self.cancel(job['job'])
            n += 1
        return n

    def cancel_gui(self) -> int:
        """kill_gui: cancel every job that drives the GUI (input lock jobs)."""
        n = 0
        for job in store.list_jobs():
            if job['status'] in store.TERMINAL:
                continue
            if job.get('input_lock') or self.lock.is_held_by(job['id']):
                self.cancel(job['job'])
                n += 1
        # belt-and-braces: never leave a dangling GUI hold
        self.lock.force_release()
        return n

    # ---- events / narration ------------------------------------------------
    def emit_event(self, snap: Optional[Dict[str, Any]], status: str,
                   stage: Optional[str] = None, progress: Optional[float] = None,
                   text: Optional[str] = None, tool: Optional[str] = None,
                   error_code: Optional[str] = None) -> Dict[str, Any]:
        """Build a PROTOCOL §5 job_event frame, fan out via hooks, journal it."""
        if snap is None:
            snap = {}
        rowid = snap.get('id')
        seq = store.next_event_seq(rowid) if rowid else 0
        body = (text if text is not None else snap.get('text')) or ''
        frame = {
            'type': 'job_event',
            'v': 1,
            'job': snap.get('job'),
            'seq': seq,
            'ts': store.now_ms(),
            'status': status,
            'stage': stage if stage is not None else (snap.get('stage') or 'routing'),
            'text': str(body)[:160],
            'progress': float(progress if progress is not None else (snap.get('progress') or 0.0)),
            'priority': snap.get('priority') or 'normal',
        }
        if tool:
            frame['tool'] = tool
        if error_code:
            frame['error_code'] = error_code
        for hook in (self.sink, self.on_state):
            if hook is not None:
                try:
                    hook(frame)
                except Exception:  # noqa: BLE001 — a dead ws must never kill the engine
                    pass
        if rowid:
            store._log_event(rowid, frame)
        return frame

    # ---- introspection -----------------------------------------------------
    def stats(self) -> Dict[str, Any]:
        jobs = store.list_jobs()
        active = [j for j in jobs if j['status'] in ('running', 'awaiting_confirm')]
        return {
            'jobs_active': len(active),
            'jobs_queued': len([j for j in jobs if j['status'] == 'queued']),
            'jobs_pending_confirm': len([j for j in jobs if j['status'] == 'awaiting_confirm']),
            'jobs_done': len([j for j in jobs if j['status'] == 'done']),
            'jobs_failed': len([j for j in jobs if j['status'] == 'failed']),
            'jobs_cancelled': len([j for j in jobs if j['status'] == 'cancelled']),
            'jobs_interrupted': len([j for j in jobs if j['status'] == 'interrupted']),
            'input_lock': {
                'held': self.lock.owner is not None,
                'job': store.job_ext_id(self.lock.owner) if self.lock.owner else None,
                'waiting': self.lock.waiters,
            },
            'paused': self.paused,
            'running_tasks': len(self._tasks),
        }


_engine: Optional[JobEngine] = None


def get_engine() -> JobEngine:
    global _engine
    if _engine is None:
        _engine = JobEngine()
    return _engine

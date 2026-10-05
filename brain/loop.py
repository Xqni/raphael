"""Agent loop (PROTOCOL §5 + ARCHITECTURE §4): job → fastpath first → router
seam → plan → tools → narrate.

- fastpath: deterministic intents (brain/fastpath.py) run BEFORE any LLM;
- router seam: brain/llm.py over brain/router/core.py (router-dev's package);
  ANY provider failure degrades to a PROTOCOL error code — never a crash;
- tools: dispatch through the tool registry (brain/tools) with input-lock
  arbitration (FIFO, never stolen) and confirm gating in code;
- narrate: push job_event / subtitle / speak frames onto the WS hub — role=ui
  receives subtitles + orb_state (the orb), role=body receives speak frames.
"""
import asyncio
import json
import re
import time
from typing import Any, Dict, Optional

from . import confirm as confirm_mod
from . import fastpath, llm, tools as tool_reg
from .jobs import store
from .jobs.engine import JobEngine, get_engine
from .mode import get_mode

# deterministic intents must be registered before any job runs (no LLM)
fastpath.register_builtin_intents()

_TOOL_CALL_RE = re.compile(r'\{[^{}]*"tool"[^{}]*\}', re.S)


def _extract_tool_call(text: str):
    """Plans may embed a structured tool call: {"tool": name, "args": {...}}."""
    m = _TOOL_CALL_RE.search(text or '')
    if m:
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj.get('tool'), str):
                return obj['tool'], obj.get('args') or {}
        except (TypeError, ValueError):
            pass
    return None, {}


def build_runner(hub=None):
    """Returns async runner(job) wired to a ws hub for narration (hub=None in
    unit tests)."""
    mode = get_mode()

    async def run_job(job: Dict[str, Any]) -> None:
        rowid = job['id']
        jid = job['job']
        text = (job.get('text') or job.get('task') or '').strip()
        engine = get_engine()

        def emit(status, stage=None, progress=None, t=None, tool=None,
                 error_code=None):
            return engine.emit_event(store.get_job(rowid) or job, status,
                                     stage=stage, progress=progress, text=t,
                                     tool=tool, error_code=error_code)

        def narrate(t: str, state: Optional[str] = None):
            if hub is None:
                return
            hub.narrate(jid, t, state=state)

        try:
            # ---- 1. confirm gate (BEFORE any tool dispatch, per-job) -------
            decision = confirm_mod.classify(text)
            if decision.needs:
                store.set_pending_confirm(rowid, True)
                emit('awaiting_confirm', stage='routing', progress=0.1,
                     t=decision.question)
                narrate(decision.question, state='confirm')
                if hub is not None:
                    hub.broadcast({
                        'type': 'needs_confirm', 'v': 1, 'job': jid,
                        'question': decision.question,
                        'actions': decision.actions,
                        'expires_at': int(time.time() * 1000)
                        + int(engine.confirmer.timeout_s * 1000),
                    })
                answer = await engine.confirmer.request(
                    rowid, decision.question, decision.actions)
                store.set_pending_confirm(rowid, False)
                if answer != 'yes':
                    spoken = ('Aborted.' if answer == 'no'
                              else 'Aborted — confirmation timed out.')
                    code = 'E_CANCELLED' if answer == 'no' else 'E_CONFIRM_TIMEOUT'
                    store.transition(rowid, 'cancelled', stage='done',
                                     progress=1.0, error_code=code, result=spoken)
                    emit('cancelled', stage='done', progress=1.0, t=spoken,
                         error_code=code)
                    narrate(spoken)
                    return
                # scoped grant recorded on the job record (PROTOCOL §9.3)
                store._log_event(rowid, {'event': 'confirm_granted',
                                         'question': decision.question,
                                         'reason': decision.reason})

            # ---- 2. fast path (deterministic, no LLM) ----------------------
            ctx = fastpath.IntentCtx(engine=engine, mode=mode)
            res = fastpath.run_intent(text, ctx)
            tool_name: Optional[str] = None
            tool_args: Dict[str, Any] = {}
            needs_lock = False
            if res is not None and res.done:
                narrate(res.text)
                if res.tool:
                    tool_name, tool_args = res.tool, dict(res.tool_args or {})
                    needs_lock = bool(res.needs_lock)
                else:
                    store.transition(rowid, 'done', stage='done', progress=1.0,
                                     result=res.text)
                    emit('done', stage='done', progress=1.0, t=res.text)
                    return
            else:
                # ---- 3. router seam → plan (graceful degradation) ----------
                if mode.private:
                    llm_res = llm.LLMResult(
                        ok=False, code='E_OFFLINE',
                        error='private mode suppresses cloud providers')
                else:
                    llm_res = await llm.plan(text)
                if not llm_res.ok:
                    narrate("I can't reach any model provider right now.")
                    if hub is not None:
                        hub.broadcast({'type': 'error', 'v': 1, 'job': jid,
                                       'code': llm_res.code or 'E_OFFLINE',
                                       'detail': llm_res.error})
                    store.transition(rowid, 'failed', stage='done', progress=1.0,
                                     error_code=llm_res.code or 'E_OFFLINE',
                                     result=llm_res.error)
                    emit('failed', stage='done', progress=1.0,
                         t='Provider unavailable', error_code=llm_res.code)
                    return
                narrate(llm_res.text)
                tool_name, tool_args = _extract_tool_call(llm_res.text)
                store.transition(rowid, 'done', stage='done', progress=1.0,
                                 result=llm_res.text)
                emit('done', stage='done', progress=1.0,
                     t=(llm_res.text or 'Task complete')[:160])
                return

            # ---- 4. tools (input-lock arbitration handled in engine) -------
            fn = tool_reg.get(tool_name) if tool_name else None
            if fn is None:
                store.transition(rowid, 'failed', stage='done', progress=1.0,
                                 error_code='E_BAD_MSG',
                                 result=f'unknown tool {tool_name}')
                emit('failed', stage='done', progress=1.0,
                     t=f'Unknown tool: {tool_name}', error_code='E_BAD_MSG')
                return
            meta = tool_reg.describe(tool_name)
            needs_lock = needs_lock or bool(meta.get('needs_lock'))
            if needs_lock:
                # FIFO queue behind the current lock owner; cancel-while-waiting
                # is safe (lock.acquire drops the waiter on CancelledError)
                await engine.lock.acquire(rowid)
            emit('running', stage='tool', progress=0.6,
                 t=f'Running {tool_name}', tool=tool_name)
            try:
                out = await asyncio.to_thread(lambda: fn(**tool_args))
            except Exception as e:  # noqa: BLE001 — job failure, not loop failure
                store.transition(rowid, 'failed', stage='done', progress=1.0,
                                 error_code='E_INTERNAL', result=str(e)[:300])
                emit('failed', stage='done', progress=1.0,
                     t=f'{tool_name} failed: {type(e).__name__}',
                     error_code='E_INTERNAL', tool=tool_name)
                narrate(f'{tool_name} failed.')
                return
            finally:
                if needs_lock:
                    engine.lock.release(rowid)
            summary = (str(out)[:160] if out is not None else '') or f'{tool_name} done'
            narrate(summary)
            store.transition(rowid, 'done', stage='done', progress=1.0,
                             result=summary)
            emit('done', stage='done', progress=1.0, t=summary, tool=tool_name)
        finally:
            # drop any pending confirm future (deny-by-leak safety)
            engine.confirmer.cancel(rowid)

    return run_job


def start_loop(hub=None, workers: Optional[int] = None) -> JobEngine:
    """Wire the runner to the engine and start workers (idempotent)."""
    engine = get_engine()
    engine.runner = build_runner(hub)
    if not engine.started:
        engine.start(workers=workers)
    return engine


async def stop_loop():
    await get_engine().shutdown()

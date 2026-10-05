"""FastAPI application for the Brain core (PROTOCOL.md §1–§4).

Endpoints:
- GET  /health              supervisor probe (token required)
- WS   /ws                  real WebSocket hub (auth/roles/ping/keepalive)
- GET  /jobs                job snapshots
- POST /jobs                create job {text|task, source, priority, input_lock}
- GET  /jobs/{job_id}       job snapshot
- POST /jobs/{job_id}/cancel  {scope: gui|full}
- POST /control             {action, persist} (PROTOCOL §3 control actions)
- GET  /status              mode + engine stats

Lifespan wires the agent loop (fastpath → router seam → tools → narrate) to the
WS hub and marks interrupted jobs at startup (PROTOCOL §5).
"""
import os
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket
from pydantic import BaseModel

from . import auth as auth_mod
from . import tools as tool_reg  # noqa: F401 — registers built-in tools on import
from .control import apply_control
from .jobs import store
from .jobs.engine import get_engine
from .loop import start_loop, stop_loop
from .mode import get_mode
from .ws import SERVER_V, get_hub

hub = get_hub()


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = get_engine()
    hub.engine = engine
    # narration fanout: job_event → all roles; orb_state refresh on transitions
    engine.sink = lambda frame: hub.broadcast(frame)
    engine.on_state = lambda frame: hub.refresh_orb_state()
    start_loop(hub=hub)            # wires runner, starts workers, marks interrupted
    await hub.start()
    get_mode()                     # load persisted mode flags
    # Pre-warm Fish TTS in the background: a COLD fish server made the user's
    # first spoken reply silent in the wild (spawn window + empty fallback
    # after the phrase cache was cleared). warmup() never raises.
    async def _warm_tts():
        try:
            from .voice import get_voice
            await get_voice().warmup()
            print("[tts] fish pre-warmed at startup", flush=True)
        except Exception as _e:  # noqa: BLE001 — warmup must never block boot
            print(f"[tts] fish pre-warm skipped: {type(_e).__name__}: {_e}",
                  flush=True)
    import asyncio as _aio
    _aio.create_task(_warm_tts())
    # Authoritative pidfile for supervisor's process-mode recycle: written by
    # the RUNNING uvicorn itself (the launch-time shell `echo $$` drifted by
    # one process layer; supervisor verifies the cmdline before any kill).
    try:
        with open('/tmp/raphael-brain.pid', 'w') as _pf:
            _pf.write(str(os.getpid()))
    except OSError:
        pass
    try:
        yield
    finally:
        await hub.stop()
        await stop_loop()


app = FastAPI(lifespan=lifespan)
app.state.hub = hub
app.state.engine = get_engine()


# Token handling — RAPHAEL_TOKEN_PATH lets tests point at a temp file so the
# REAL ~/.raphael/token is never written or deleted (the original test did).
get_token = auth_mod.get_token


def token_auth(x_raphael_token: Optional[str] = Header(None),
               authorization: Optional[str] = Header(None)):
    # Missing header must be 401 (auth), not 422 (validation).
    cand = x_raphael_token or auth_mod.bearer_from_header(authorization)
    if not auth_mod.check_token(cand):
        raise HTTPException(status_code=401, detail='Invalid token')
    return True


@app.get('/health')
async def health(auth: bool = Depends(token_auth)) -> Dict[str, Any]:
    return {'status': 'ok'}


@app.websocket('/ws')
async def ws_endpoint(ws: WebSocket):
    await hub.handle(ws)


# ---- Jobs API (PROTOCOL §5 shapes) -----------------------------------------
@app.get('/jobs')
async def get_jobs(auth: bool = Depends(token_auth)) -> List[Dict[str, Any]]:
    return store.list_jobs()


class JobIn(BaseModel):
    text: Optional[str] = None
    task: Optional[str] = None          # phase-1 alias for text
    source: str = 'text'
    priority: Any = 'normal'            # 'user_facing'|'normal'|'background' or legacy int
    input_lock: bool = False
    job_id: Optional[str] = None        # pre-allocated id ack (PROTOCOL §3)


@app.post('/jobs')
async def post_job(body: JobIn, auth: bool = Depends(token_auth)) -> Dict[str, Any]:
    text = (body.text or body.task or '').strip()
    if not text:
        raise HTTPException(status_code=422, detail='text is required')
    engine = get_engine()
    snap = await engine.submit(text=text, priority=body.priority,
                               source=body.source, input_lock=body.input_lock,
                               session=None, task=text)
    return {'job_id': snap['job'], 'job': snap}


@app.get('/jobs/{job_id}')
async def job_status(job_id: str, auth: bool = Depends(token_auth)) -> Dict[str, Any]:
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail='Job not found')
    return job


class CancelIn(BaseModel):
    scope: str = 'full'                 # gui releases the input lock only


@app.post('/jobs/{job_id}/cancel')
async def cancel(job_id: str, body: Optional[CancelIn] = None,
                 auth: bool = Depends(token_auth)) -> Dict[str, Any]:
    scope = body.scope if body and body.scope in ('gui', 'full') else 'full'
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail='Job not found')
    if job['status'] in store.TERMINAL:
        # terminal states are immutable — report as-is, do not re-cancel
        raise HTTPException(status_code=400, detail=f"Job already {job['status']}")
    job = get_engine().cancel(job_id, scope=scope)
    return {'cancelled': True, 'job': job}


# ---- Control / status (PROTOCOL §3) ----------------------------------------
class ControlIn(BaseModel):
    action: str
    persist: bool = True


@app.post('/control')
async def control(body: ControlIn, auth: bool = Depends(token_auth)) -> Dict[str, Any]:
    try:
        result = apply_control(body.action, persist=body.persist)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    hub.refresh_orb_state()
    return result


@app.get('/status')
async def status(auth: bool = Depends(token_auth)) -> Dict[str, Any]:
    engine = get_engine()
    return {'ok': True, 'server_v': SERVER_V, 'mode': get_mode().label(),
            'sessions': get_hub().session_counts(), **engine.stats()}

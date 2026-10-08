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
- POST /say                 {text, job?} speak + subtitle (CLI voice-out)

Lifespan wires the agent loop (fastpath → router seam → tools → narrate) to the
WS hub and marks interrupted jobs at startup (PROTOCOL §5).
"""
import os
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from . import auth as auth_mod
from . import tools as tool_reg  # noqa: F401 — registers built-in tools on import
from .control import apply_control
from .jobs import store
from .jobs.engine import get_engine
from .loop import narrate_now, start_loop, stop_loop
from .mode import get_mode
from .ws import SERVER_V, get_hub

hub = get_hub()


def _pidfile_targets():
    """Paths the lifespan writes its pid to — EMPTY during test runs
    (PYTEST_CURRENT_TEST), so TestClient boots never touch a live brain's
    pidfiles. Production (uvicorn via run.py) always writes."""
    if os.environ.get('PYTEST_CURRENT_TEST'):
        return []
    from . import config as appcfg
    targets = [appcfg.pidfile()]
    legacy = appcfg.legacy_pidfile()
    if legacy is not None:
        targets.append(legacy)
    return targets


@asynccontextmanager
async def lifespan(app: FastAPI):
    # SEC-7 / [56] FAIL-CLOSED BEFORE SERVING: qa's guard tool + local verify
    # must both pass, else RuntimeError aborts startup (refuse to serve).
    from . import coreguard
    coreguard.check_at_boot()
    # instance-derived boot line (INTERFACES §d; tripwire: app.py derives via
    # RAPHAEL_INSTANCE through brain/config.py, never a hardcoded path)
    try:
        from . import config as _cfg
        from .logjson import slog
        slog('brain_boot', instance=_cfg.instance(),
             pidfile=str(_cfg.pidfile()), legacy=bool(_cfg.legacy_pidfile()))
    except Exception:  # noqa: BLE001 — boot observability must not block
        pass
    engine = get_engine()
    hub.engine = engine
    # computer-use hook (ACCEPTED 2026-10-06): sync tools run via to_thread —
    # they need the brain's MAIN loop for the act pipeline (hub.broadcast /
    # engine.expect_act). Supported hook replaces their private-attr fallback.
    try:
        import asyncio as _aio
        from .tools.computer_use import wiring as _cu_wiring
        _cu_wiring.bind_loop(_aio.get_running_loop())
    except ImportError:
        pass                      # computer-use lane not present yet
    except Exception as _e:        # noqa: BLE001 — loud, never fatal
        print(f'[tools] bind_loop failed: {type(_e).__name__}: {_e}', flush=True)
    # AUD-05 (P0 + dispatch 2026-10-08): wire the PRODUCTION foreground hook
    # into the router chat egress gate — push-cache first (fresh <5s), vision
    # ring second, else UNKNOWN (router fails closed). The push comes from
    # pc-control/body via the ws `foreground` frame (brain/foreground.py).
    try:
        from brain.router import set_foreground_check as _set_fg
        from . import foreground as _fg
        _set_fg(_fg.provider)
    except ImportError:
        pass                             # router not present yet
    from . import orbstate
    orbstate.attach(hub)
    # narration fanout: job_event → all roles; orb_state refresh on transitions
    engine.sink = lambda frame: hub.broadcast(frame)

    def _on_job_state(frame):
        # INTERFACES §e: failed jobs put the orb into `error` (transient).
        if frame.get('status') == 'failed':
            orbstate.mark_error()
        hub.refresh_orb_state()

    engine.on_state = _on_job_state
    # INTERFACES §b: re-run tool auto-discovery at lifespan so subpackages
    # (e.g. brain/tools/pc) that landed after the first import register on a
    # LIVE Brain without touching any shared file. Idempotent; failures are
    # recorded in brain.tools.load_errors(), never fatal.
    try:
        tool_reg.discover()
    except Exception as _e:  # noqa: BLE001 — discovery must never block boot
        print(f'[tools] lifespan discovery failed: {type(_e).__name__}: {_e}',
              flush=True)
    # boot snapshot while the engine is not ready (INTERFACES §e `starting`)
    orbstate.emit('starting', hub=hub, engine=engine)
    start_loop(hub=hub)            # wires runner, starts workers, marks interrupted
    # AUD-22 (tools-memory request APPROVED): re-arm persisted schedules so
    # timers/reminders survive a restart (fire path = their engine.submit seam).
    try:
        from .tools.schedule import arm_all as _arm_all
        _arm_all()
    except ImportError:
        pass                       # schedule package not present
    except Exception as _ae:        # noqa: BLE001 — boot must proceed
        from .logjson import slog
        slog('schedule_arm_failed', error=type(_ae).__name__)
    await hub.start()
    get_mode()                     # load persisted mode flags
    orbstate.finish_boot()
    orbstate.refresh(hub=hub, engine=engine)
    # Notice emitter 1 (PROTOCOL §3, approved 2026-10-07): restart recovery —
    # queued PENDING because ui/cli clients authenticate AFTER boot; the
    # first one drains it (ws._handle_auth -> notice.flush_pending).
    try:
        n_boot = len(getattr(engine, 'interrupted_at_boot', None) or [])
        if n_boot:
            from . import config as _ncfg
            from . import notice as _notice
            greeting = _ncfg.cfg_get(
                _ncfg.get_config(), 'voice_personality.greeting_recovered',
                'Raphael online. Recovered from an unexpected shutdown.')
            _notice.emit(f'{greeting} Interrupted tasks: {n_boot}.',
                         level='warn', key='boot_recovery', pending=True)
    except Exception as _ne:  # noqa: BLE001 — a notice can never break boot
        print(f'[notice] boot notice skipped: {type(_ne).__name__}: {_ne}',
              flush=True)
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
    # Instance isolation (INTERFACES §d): the real pidfile lives in the
    # instance data-dir (out of world-writable /tmp). Instance `main` ALSO
    # writes the legacy /tmp/raphael-brain.pid so the current supervisor keeps
    # byte-compatible behavior until the infra lane adopts config.pidfile().
    # Wave-4 safety: NEVER written from tests — a TestClient lifespan runs in
    # the pytest process and must not clobber the LIVE brain's pidfiles
    # (live stack up by user directive).
    try:
        for _pf_path in _pidfile_targets():
            _pf_path.parent.mkdir(parents=True, exist_ok=True)
            _pf_path.write_text(str(os.getpid()))
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
    kind: Optional[str] = None          # Wave-5 APPROVED: chat|analysis|simulation|act
    parent: Optional[str] = None        # Wave-5 APPROVED: fan-out correlation


@app.post('/jobs')
async def post_job(body: JobIn, auth: bool = Depends(token_auth)) -> Dict[str, Any]:
    text = (body.text or body.task or '').strip()
    if not text:
        raise HTTPException(status_code=422, detail='text is required')
    engine = get_engine()
    if body.kind is not None and body.kind not in engine.KINDS:
        raise HTTPException(status_code=422,
                            detail=f'kind must be one of {list(engine.KINDS)}')
    snap = await engine.submit(text=text, priority=body.priority,
                               source=body.source, input_lock=body.input_lock,
                               session=None, task=text,
                               kind=body.kind, parent=body.parent)
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
    # router usage/rate block (router request APPROVED 2026-10-07): additive
    # key only; usage_status() reads a local file + in-memory state (no
    # network, no keys, never raises). Lazy import: the router lane's branch
    # may not be merged yet — then the key stays {} and fills in on merge.
    router_block: Dict[str, Any] = {}
    try:
        from brain.router import usage_status
        router_block = await usage_status()
    except ImportError:
        router_block = {}
    except Exception:  # noqa: BLE001 — /status must stay up
        router_block = {'error': 'unavailable'}
    from . import coreguard, latency
    return {'ok': True, 'server_v': SERVER_V, 'mode': get_mode().label(),
            'sessions': get_hub().session_counts(), 'router': router_block,
            'latency': latency.snapshot(), 'core_guard': coreguard.status(),
            **engine.stats()}


# ---- POST /say (CLI voice-out; request: docs/requests/brain-core__to__
# integrator__rest-say-endpoint.md) ------------------------------------------
class SayIn(BaseModel):
    text: str
    job: Optional[str] = None        # correlation id for the frames (optional)


@app.post('/say')
async def say(body: SayIn, auth: bool = Depends(token_auth)):
    """Speak + subtitle an arbitrary line (CLI voice-out). 202 — narration is
    async; TTS fallback/notice handles a cold Fish server."""
    import uuid
    text = (body.text or '').strip()
    if not text:
        raise HTTPException(status_code=422, detail='text is required')
    if len(text) > 4000:
        raise HTTPException(status_code=422, detail='text too long (4000 max)')
    job_id = (body.job or '').strip() or f'say_{uuid.uuid4().hex[:8]}'
    narrate_now(hub, job_id, text, engine=get_engine())
    return JSONResponse(status_code=202,
                        content={'ok': True, 'job': job_id,
                                 'chars': len(text)})

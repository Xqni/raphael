# Wave 2 — Brain phase 2 handoff (brain-dev, Tier-1 Go fallback)

Date: 2026-10-05. Status: **IMPLEMENTED + VERIFIED (real outputs below)**.

## What was built (brain/** — router/ and voice/ untouched)

| File | Purpose |
|---|---|
| `brain/auth.py` | shared token helpers (hmac.compare_digest, RAPHAEL_TOKEN_PATH) |
| `brain/memory/__init__.py` | WAL + synchronous-NORMAL SQLite, additive schema migration (text/source/stage/progress/priority_label/input_lock/pending_confirm/error_code/session/event_seq + `state` table for mode persistence), RAPHAEL_DB_PATH override |
| `brain/jobs/store.py` | canonical job ids `j_YYYYMMDD_NNNN`, guarded terminal-immutability transitions (`UPDATE ... WHERE status NOT IN (terminal)`), per-job monotonic event seq, journal JSON frames |
| `brain/jobs/lock.py` | InputLock FIFO arbiter — single-owner, NEVER stolen, waiter cleanup on cancel, `force_release` for kill_gui/shutdown |
| `brain/jobs/engine.py` | concurrent JobEngine: asyncio.PriorityQueue admission (user_facing rank 0 preempts order only), per-job asyncio tasks, reliable cancel (queued → guarded transition; running → task.cancel() → lock released + terminal + event; worker survives its own job's cancellation), pause gate, cancel_all/cancel_session/cancel_gui, startup `interrupted` marking (never auto-resume), shutdown marks leftovers `cancelled` (no orphaned tasks — worker cancels+gathers its current job on the way out) |
| `brain/confirm.py` | REAL confirmation: classify() risky patterns (shell/exec/delete/purchase/password/publish/network/install/system-settings) + risky tool metadata; Confirmer per-job futures; approve → scoped grant journaled; deny → cancelled "Aborted."; timeout (RAPHAEL_CONFIRM_TIMEOUT_S, default 30) → E_CONFIRM_TIMEOUT abort, NEVER auto-approve; free-text parse fails closed |
| `brain/mode.py` | pause/private/watch persisted in SQLite state table (survives restarts) |
| `brain/control.py` | shared control logic: pause/resume/private_on/off/watch_on/off (persist flag honored), kill_gui = momentary cancel of GUI jobs + force-release lock |
| `brain/llm.py` | router seam over `brain/router/core.py` (acquire_model → complete); RAPHAEL_DISABLE_ROUTER=1 forces fallback; every failure → LLMResult(ok=False, code=E_OFFLINE/E_TIMEOUT/E_PROVIDER_5XX/...) — loop never crashes |
| `brain/fastpath.py` | deterministic intents (echo/status/cancel-all/pause/resume/private on/off + register_intent/match_intent compat); IntentResult/IntentCtx |
| `brain/tools/__init__.py` | registry + describe() metadata (risky/needs_lock); shell tool marked risky |
| `brain/loop.py` | REAL agent loop: job → confirm gate (before any tool) → fastpath → router seam → plan → tools (input-lock FIFO via engine.lock) → narrate (subtitle→all, speak→role=body only, job_event→all via hub); graceful no-provider degradation (subtitle + error frame + failed job_event) |
| `brain/ws.py` | REAL /ws hub: auth handshake ≤5 s (constant-time compare), upgrade-token check (defense in depth), E_AUTH_RATE (≥5 fails/IP/60s → 5 min ban), role negotiation ui|body|cli + §4 capability enforcement (E_UNSUPPORTED), server ping every 10 s (immediate ping after auth_ok), 3 missed pongs → close + cancel session tasks, 8 MiB / 40 msgs/s (binary 125/s) limits, RAPH binary framing check, canonical shapes: auth_ok/fail, ack, job_event, needs_confirm, orb_state, subtitle, speak, error, pong, job_list/job_get, act_res, orb_input, control, state_req |
| `brain/app.py` | FastAPI rework: /health (Bearer or X-Raphael-Token), /ws, /jobs CRUD (POST {text|task,source,priority,input_lock} → {job_id, job}; GET list/snapshots; cancel {scope: gui|full} → 404 unknown / 400 terminal / 200), /control {action,persist} per PROTOCOL §3, /status; lifespan wires hub+loop, shutdown cancels cleanly |
| `brain/run.py` | entry point: bind host auto-detect (wslinfo NAT→0.0.0.0, mirrored→127.0.0.1; RAPHAEL_BIND override) → uvicorn |
| `brain/raphael-brain.service` | systemd TEMPLATE (NOT installed — needs root): ExecStart=venv python -m brain.run, Restart=always, User=dami, WorkingDirectory=/home/dami/raphael, journal logging |
| `brain/tests/conftest.py` | RAPHAEL_DB_PATH→temp file, RAPHAEL_DISABLE_ROUTER=1, RAPHAEL_CONFIRM_TIMEOUT_S=2 |
| `brain/tests/test_jobs.py` | 11 engine/lock/confirm tests |
| `brain/tests/test_ws.py` | 16 WS protocol tests (SAFETY: RAPHAEL_TOKEN_PATH temp fixture kept) |
| `brain/tests/manual_ws_client.py` | live round-trip client (not collected by pytest) |

## Public interfaces for other agents (build against these)

- **WS (role=cli/ui/body)**: connect `ws://127.0.0.1:8765/ws` → send
  `{"type":"auth","v":1,"token":"<hex>","role":"ui|body|cli","client":"...","client_v":"1"}`
  within 5 s → `{"type":"auth_ok","v":1,"session":"<sid>","server_v":"brain-0.2.0"}`
  or `auth_fail{code:E_AUTH|E_PROTO}` + close. Server pings `{"type":"ping","v":1}`
  (immediately after auth_ok, then every 10 s; 3 missed → close). Reply
  `{"type":"pong"}`. `command{text,source,priority?}` → `ack{job}` then
  `job_event` frames (PROTOCOL §5 shape: job/seq/ts/status/stage/text/progress/
  priority/tool/error_code). `state_req` → `orb_state`. `confirm_resp{job,
  answer:yes|no|free_text}`. `cancel{job: id|all, scope: gui|full}`.
- **REST** (token: `X-Raphael-Token` or `Authorization: Bearer`):
  `GET /health` `{"status":"ok"}`; `GET/POST /jobs`; `GET /jobs/{id}`;
  `POST /jobs/{id}/cancel` `{"scope":"full|gui"}`; `POST /control`
  `{"action":"pause|resume|private_on|private_off|kill_gui|watch_on|watch_off",
  "persist":bool}`; `GET /status` → mode + engine stats + input_lock.
- **Router seam** (`brain/llm.py`, for router-dev/tests): `await llm.plan(text,
  task_kind=None) -> LLMResult(ok,text,provider,model,code,error)`. Router-dev
  can swap the internals of `brain/router/core.py`; seam contract stays.
- **Tool registry** (`brain/tools`): `register(name, func, risky=..., needs_lock=...,
  description=...)`, `get(name)`, `describe(name)`, `names()`.
- **Env knobs**: RAPHAEL_TOKEN_PATH, RAPHAEL_DB_PATH, RAPHAEL_BIND,
  RAPHAEL_PORT, RAPHAEL_DISABLE_ROUTER, RAPHAEL_LLM_TIMEOUT_S,
  RAPHAEL_CONFIRM_TIMEOUT_S, RAPHAEL_WS_PING_INTERVAL_S,
  RAPHAEL_JOBS_MAX_CONCURRENT, RAPHAEL_LOG_LEVEL.

## VERIFY FOR REAL — literal outputs

### `brain/.venv/bin/python -m pytest -q brain/tests`
```
30 passed, 1 warning in 8.54s
```
(3 phase-1 health tests + 11 engine/lock/confirm + 16 WS protocol tests.
Collection: `30 tests collected in 0.29s`.)

### Live uvicorn 127.0.0.1:8765 + REST probes (curl)
```
uvicorn pid 19762
--- /health without token:
401
--- /health with token:
{"status":"ok"}
--- /status:
{"ok":true,"server_v":"brain-0.2.0","mode":"normal","jobs_active":0,"jobs_queued":0,...,"input_lock":{"held":false,"job":null,"waiting":0},...}
--- /control private_on:
{"ok":true,"action":"private_on","mode":"private","persisted":true}
--- /control private_off:
{"ok":true,"action":"private_off","mode":"normal","persisted":true}
```

### Live WS round trip (`brain/tests/manual_ws_client.py`, websockets client)
```
CONNECT ws://127.0.0.1:8765/ws  (token from /tmp/raphael-demo-token)
  [recv] {"type": "auth_ok", "v": 1, "session": "9389153aa035", "server_v": "brain-0.2.0"}
  AUTH OK session=9389153aa035 server_v=brain-0.2.0
  [recv] {"type": "ping", "v": 1}
  [recv] {"type": "orb_state", "v": 1, "state": "idle", "jobs_active": 0, "mode": "normal", ...}
  STATE mode=normal jobs_active=0
COMMAND: "echo hello raphael"
  [recv] {"type": "ack", "v": 1, "job": "j_20261005_0001", "text_id": null}
  [recv] {"type": "job_event", "v": 1, "job": "j_20261005_0001", "seq": 1, ..., "status": "queued", ...}
  [recv] {"type": "job_event", ..., "seq": 2, ..., "status": "running", "stage": "routing", ...}
  [recv] {"type": "subtitle", ..., "text": "Echo: hello raphael", "fade_ms": 4000}
  [recv] {"type": "job_event", ..., "seq": 3, ..., "status": "done", "stage": "done", "text": "Echo: hello raphael", "progress": 1.0, ...}
  DONE text='Echo: hello raphael' seq=3
COMMAND: "delete my downloads folder"
  [recv] ack job=j_20261005_0002
  [recv] job_event queued
  [recv] job_event running
  [recv] {"type": "job_event", ..., "seq": 3, ..., "status": "awaiting_confirm", "text": "About to delete files or data: “delete my downloads folder”. Confirm?", ...}
  [recv] {"type": "subtitle", ..., "text": "About to delete files or data: “delete my downloads folder”. Confirm?", ...}
  [recv] {"type": "needs_confirm", ..., "question": "About to delete files or data: “delete my downloads folder”. Confirm?", "actions": ["yes", "no"], "expires_at": 1791209783221}
  CONFIRM question='About to delete files or data: “delete my downloads folder”. Confirm?'
  [recv] {"type": "ack", ..., "answer": "no"}
  [recv] {"type": "job_event", ..., "seq": 4, ..., "status": "cancelled", "text": "Aborted.", ..., "error_code": "E_CANCELLED"}
  CANCELLED text='Aborted.' error_code=E_CANCELLED
  [recv] {"type": "subtitle", ..., "text": "Aborted.", ...}
  [recv] {"type": "orb_state", ..., "state": "idle", "jobs_active": 0, "mode": "normal", ...}
  FINAL STATE mode=normal jobs_active=0
ROUND TRIP COMPLETE
```

### Live no-provider degradation (router disabled) — loop never crashes
```
  [recv] {"type": "subtitle", ..., "text": "I can't reach any model provider right now.", ...}
  [recv] {"type": "error", ..., "code": "E_OFFLINE", "detail": "no provider (router disabled or unavailable)"}
  [recv] {"type": "job_event", ..., "status": "failed", ..., "error_code": "E_OFFLINE"}
  [recv] {"type": "orb_state", ..., "state": "idle", "jobs_active": 0, ...}
LOOP SURVIVED PROVIDER FAILURE
```

### Graceful SIGTERM + durable journal
```
INFO:     Shutting down
INFO:     Waiting for application shutdown.
INFO:     Application shutdown complete.
INFO:     Finished server process [19762]
jobs after shutdown (crash-safe journal):
  j_20261005_0001 done 'Echo: hello raphael' err= None
  j_20261005_0002 cancelled 'Aborted.' err= E_CANCELLED
  j_20261005_0003 failed 'no provider (router disabled or unavaila' err= E_OFFLINE
```

## Defects found by real test runs (fixed — do not regress)
1. **asyncio.PriorityQueue loop-binding (py3.12)**: engine singleton's queue
   created at import bound to the first event loop; on TestClient portal
   restart `queue.put` raised ValueError → WS session died silently (no ack).
   Fix: queue (re)created per running loop in `JobEngine._ensure_queue()`.
2. **Built-in fastpath intents never registered** (`register_builtin_intents`
   defined but not called) → "echo ..." fell through to the router seam →
   E_OFFLINE failed instead of instant done. Fix: called at loop.py import.
3. **starlette 1.7 API**: `WebSocketTestSession.receive_json()` has NO timeout
   kwarg → tests use `_recv_json()` wrapper (anyio.fail_after inside the portal
   on `ws._send_rx.receive`).
4. Terminal-cancel REST returned 200 for already-cancelled jobs → app now
   checks terminal BEFORE cancelling → 400 (immutable semantics).
5. `parse_free_text` was exact-match only ("yes please" → deny) → first-word
   matching (still fail-closed for anything unclear).
6. Engine shutdown left queued jobs non-terminal → shutdown now journals them
   `cancelled` (workers also cancel+gather their current job — no orphans).
7. Hub dispatch wraps handlers in try/except → handler bugs emit E_INTERNAL,
   never kill the WS session loop.

## OPEN ITEMS / NOTES for orchestrator + other agents
- systemd unit is a TEMPLATE only — NOT installed (needs root). Install cmd in file header.
- `speak` frames currently carry text + start/end only (no binary PCM chunks);
  voice-dev fills TTS chunk streaming (kind-2 binary frames, PROTOCOL §6).
- `act_req`/`act_res` body-action pipeline is NOT wired end-to-end yet (loop runs
  tools locally in WSL); act_res frames are accepted + journaled. Body-dev builds
  against `act_req{job,action,args,lock,timeout_ms}` when the seam lands.
- Audio lane (audio_start/binary kind 1) accepted + counted; STT is voice-dev's.
- Confirm free-text "modify" intent → currently fails closed (deny) — re-ask
  flow is a future refinement per PROTOCOL §9.
- Laya decision tier (fastpath miss → Laya before LLM) not wired — adapter
  point is `brain/llm.py plan()`.
- `brain/router/core.py` `complete()` is currently a stub returning fake text
  (router-dev's WIP) — when real, the seam picks it up with no brain changes.

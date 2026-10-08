# PROTOCOL.md — Raphael Brain ↔ Body/Orb/CLI contract (v1)

Status: **authoritative** — every builder works against this file. Orchestrator-owned (edits only by orchestrator / `protocol-architect` with approval). Last updated: 2026-10-05.

## 1. Transport

| Item | Value |
|---|---|
| Server | Brain (FastAPI + uvicorn) in WSL2, single port **8765** serving HTTP REST + WebSocket (`/ws`) |
| Bind | `127.0.0.1:8765` in **BOTH** networking modes (loopback contract, Wave 2). In NAT mode Windows clients reach the Brain through the supervisor's user-space relay (Windows `127.0.0.1` → VM NAT address → Brain loopback) or, once the optional narrow Hyper-V rule (`scripts/win/allow-brain-localhost.ps1`) is applied, through native WSL localhost forwarding. In mirrored mode loopback is shared natively. `RAPHAEL_BIND` is the explicit escape hatch (`0.0.0.0` only when the relay is disabled AND native forwarding is verified). Code: `brain/run.py` default (agent/infra). |
| WSL IP churn | Never hardcode the WSL IP (changes every restart). Windows side always uses `ws://127.0.0.1:8765` via the supervisor relay (or native forwarding after the narrow rule). **A direct connect to the VM's own IP on the Brain port is expected to FAIL by design** — that path is the vulnerability the loopback bind closes; there is no live-WSL-IP retry fallback anymore. WSL-internal clients use `127.0.0.1:8765` directly. Mirrored mode serves `127.0.0.1` natively. |
| CLI REST | Same port: `GET /health`, `GET /jobs`, `POST /jobs/{id}/cancel`, `POST /control`, `POST /say`, `GET /status` — all require token. (`POST /say` `{"text": str, "job": str?}` → `202 {"ok": true, "chars": N}`, speaks through the voice stack — **implemented on `agent/brain-core`, lands at its merge**; decision on `brain-core__to__integrator__rest-say-endpoint.md`, branch: agent/brain-core, not yet in main.) |
| Heartbeat | App-level WS ping initiated by server every 10 s (uvicorn does not auto-ping; this is the ONLY ping source — clients reply pong). Peer considered dead after 3 missed pongs → **max silence 30 s** → server closes session + client reconnects with exponential backoff (5 s → 30 s cap, ±20% jitter). On disconnect the server cancels that session's tasks (late `act_res` from a cancelled session → logged `E_CANCELLED`, ignored). HTTP `/health` for supervisor probes. |
| Limits | Max message 8 MiB; max 40 msgs/s per connection (except binary audio frames: 125/s); server closes on violation with `E_RATE_LIMIT`. |

## 2. Authentication

- Token: 32-byte random hex, generated once by `scripts/setup.sh` → stored WSL: `~/.raphael/token` (0600), Windows: `%APPDATA%\Raphael\token` (user-only ACL). Never in logs, prompts, orb UI, or git.
- **Handshake:** client connects WS, then MUST send within 5 s:
  ```json
  {"type":"auth","v":1,"token":"<hex>","role":"body|ui|cli","client":"body-win|orb|raphael-cli","client_v":"1.0"}
  ```
  Server replies `{"type":"auth_ok","v":1,"session":"<sid>","server_v":"..."}` or `{"type":"auth_fail","code":"E_AUTH"}` then closes.
- Constant-time token compare (`hmac.compare_digest`). ≥5 failed auths/IP in 60 s → refuse new handshakes 5 min (`E_AUTH_RATE`).
- Protocol major version mismatch (`v` ≠ 1) → `E_PROTO`, close. Role determines capabilities (§4); server enforces, never trusts the client's claim beyond the handshake.
- REST: `Authorization: Bearer <token>` header (or `X-Raphael-Token`). Same token, same rate limiting.

## 3. Message envelope (JSON control frames)

Every JSON frame: `{"type": str, "v": 1, ...fields}`. Optional correlation: `"job"`, `"seq"` (per-connection monotonic int), `"ts"` (ms epoch). Unknown `type` → `E_UNSUPPORTED` (non-fatal warning frame).

**Client → Brain (all roles unless noted):**

| type | role | fields | meaning |
|---|---|---|---|
| `auth` | all | §2 | handshake |
| `command` | cli, ui | `text`, `source: text\|voice\|orb`, `job_id?` (pre-allocated ack) | new user request → becomes a Job |
| `audio_start` | body | `sample_rate: 16000`, `channels: 1`, `encoding: pcm_s16le`, `reason: ptt\|wake\|continuation` | mic utterance begins (binary frames follow); `continuation` = resume inside the voice grace window → APPEND to the open utterance (additive, granted 2026-10-08) |
| `audio_end` | body | — | utterance ends → Brain runs VAD-final + STT |
| `confirm_resp` | ui, cli, body | `job`, `answer: yes\|no\|free_text` | answer to a `needs_confirm` (from speech STT or text) |
| `job_list` / `job_get` | all | `job?` | request job snapshot(s) |
| `cancel` | all | `job: id\|all`, `scope: gui\|full` | cancel job(s); `gui` releases input lock only |
| `control` | cli, ui, body | `action: pause\|resume\|private_on\|private_off\|kill_gui\|watch_on\|watch_off`, `persist: bool` | global controls (kill = halt GUI-driving jobs now; pause persists across restarts) |
| `act_res` | body | `job`, `ok`, `result?`, `error?` | response to an `act_req` |
| `orb_input` | ui | `kind: click\|dblclick\|menu\|submit_text`, `value?` | orb interaction (menu item names are a fixed enum) |
| `state_req` | ui, cli | — | request full state snapshot (orb state, jobs, mode flags) |

**Brain → Client:**

| type | roles | fields | meaning |
|---|---|---|---|
| `auth_ok` / `auth_fail` | all | §2 | handshake result |
| `ack` | all | `job`, `text_id?` | request accepted (used for instant cached ack) |
| `job_event` | all | see §5 + optional `kind` (`chat\|analysis\|simulation\|act`) + optional `parent` (fan-out correlation) | job lifecycle/progress (kind/parent additive 2026-10-07 integrator-approved: styling + parallel-minds tag; absent when unknown) |
| `notice` | ui, cli | `text`, `level: info\|warn`, `ts`, `job?` | proactive heads-up (additive, 2026-10-07 integrator-approved — **no state change**: `orb_state` stays the single state authority; ratelimited + fail-silent; no key/log data) |
| `answer` | ui, cli | `job`, `text`, `provider?`, `model?`, `format: answer` | THE final conversational reply (additive 2026-10-07, integrator-approved: emitted once per final reply incl. fastpath; provider/model only on router hops — omitted in Private Mode; alongside subtitle/speak, which are unchanged) |
| `report` | ui, cli | `job`, `title`, `summary` (<=500), `sections[<=10] {heading, text<=2000}`, `format: report` | long-form/Analysis on-screen artifact (additive 2026-10-07; caps enforced server-side before emit; spoken reply stays <=2 sentences; NOT an orb state) |
| `act_req` | body | `job`, `action`, `args`, `lock: bool`, `timeout_ms` | perform a Body action (§7). `lock:true` requires holding the input lock. |
| `speak` | body, ui | `job`, `seq`, `event: start\|chunk\|end`, `sample_rate: 24000`, `text?`, `amplitude?` (0–1 per chunk), `cached: bool` | TTS stream for playback; `chunk` payloads are binary frames (§6) |
| `stt_final` | body, ui | `job?`, `text`, `lang`, `rtf` | final transcript of an utterance |
| `orb_state` | ui | `state`, `jobs_active`, `mode: normal\|private\|paused`, `subtitle?`, `provider?`, `model?` | authoritative orb display state (§8) |
| `subtitle` | ui | `job?`, `text`, `fade_ms` | fading subtitle/status line |
| `needs_confirm` | all | `job`, `question`, `actions[]`, `expires_at` | voice/screen confirmation request (§9) |
| `error` | all | `code` (§10), `job?`, `detail?` | error (detail never contains secrets/raw screen content) |
| `pong` | all | — | heartbeat reply |

## 4. Role capabilities

| capability | body | ui | cli |
|---|---|---|---|
| send `command` | ✓ | ✓ | ✓ |
| receive `act_req` (act on PC) | **✓ only** | ✗ | ✗ |
| receive `speak` JSON | ✓ | ✓ | ✗ |
| receive `speak` binary audio | **✓ only** | ✗ | ✗ |
| receive `stt_final` / `orb_state` / `subtitle` | ✓ | **✓** | ✓ |
| `orb_input`, `confirm_resp`, `control` | `confirm_resp`,`control` | ✓ | **✓ all** |
| mic `audio_start/end` | **✓ only** | ✗ | ✗ |

Server drops the frame with `E_UNSUPPORTED` if a role exceeds its capabilities.

## 5. Jobs

```json
{"type":"job_event","job":"j_20261005_001","seq":12,"ts":1770000000000,
 "status":"queued|running|awaiting_confirm|done|failed|cancelled|interrupted",
 "stage":"routing|llm|tool|tts|done", "text":"≤160 chars human summary",
 "progress":0.0-1.0, "priority":"user_facing|normal|background", "tool":"open_url"}
```
- State machine: `queued → running → (awaiting_confirm → running) → done|failed|cancelled|interrupted`. Terminal states are immutable; `interrupted` = crashed/restarted mid-run → **reported at startup, never auto-resumed** (brief §6).
- `seq` is per-job monotonic; clients drop stale out-of-order events.
- **Cancellation vs in-flight `act_req`:** on cancel/kill the Brain stops issuing new actions; an already-sent `act_req` completes (Body executes it atomically) or is dropped by Body if it hasn't started — either way the late `act_res` is accepted, logged, and ignored for job progress. Body never leaves a partial input sequence dangling (atomic key-chord/mouse-step units).
- Completion announcements: Brain emits `job_event(done)` with short `text` ("Task complete: YouTube search") and queues it behind any ongoing speech (never interrupts mid-sentence).

## 6. Binary frames (WS binary messages)

All binary frames: `[4-byte magic "RAPH"][u8 kind][u32 seq][payload]`.

| kind | direction | payload |
|---|---|---|
| 1 | body→brain | raw PCM `s16le`, 16 kHz, mono (mic utterance chunk, ≤50 ms each) |
| 2 | brain→body | raw PCM `s16le`, 24 kHz, mono (TTS chunk, ≤500 ms each; preceded by `speak` JSON with same `seq`) |

Text transcription of audio always travels as JSON (`stt_final`); binary audio is never persisted unless debug capture is enabled (default off).

## 7. Body action API (`act_req`)

`action` enum (allow-list; server never sends free-form shell strings — structured args only):
`launch_url{url}`, `search_youtube{query}`, `open_app{name}`, `open_path{path}`, `powershell{script_id, args}` (script_id must exist in a fixed registry — NOT arbitrary strings), `screenshot{max_px:1280, quality:70}`, `uia{op, element, args}` (structured UI Automation ops), `input{keys|mouse, dx, dy}`, `window{op}`, `clipboard{op}`, `media{op}`, `volume{level}`, `brightness{level}`, `notify{text}`, `list_windows{}`, `foreground_info{}`, `list_running_apps{}`, `report{op, title, body, format}` (Report-format delivery: save into `Documents\Raphael\reports` / list saved reports — fixed directory only, never an arbitrary path, `lock:false`; added 2026-10-07 integrator-approved, request pc-control__to__integrator__protocol-report-act) (read-only inspection: window/app enumeration — all three `lock:false` and non-destructive, returning structured JSON; `foreground_info` feeds the `privacy.blocklist_apps` check before any screenshot leaves the machine). Added 2026-10-06 by integrator decision on `pc-control__to__integrator__protocol-act-req-enum.md` (branch: agent/pc-control, not yet in main; the three handlers live in `body/win/actions.py` there — **land at agent/pc-control's merge**).
- `lock:true` actions (anything touching mouse/keyboard/foreground): Body **queues** the request if another job holds the input lock → `act_res{ok:false, error:"E_LOCK_BUSY", queued:true}`; Brain handles queuing at job level anyway (input lock is Brain-arbitrated; Body is last-line enforcement).
- Every executed action is logged locally `logs/actions.log` with `job`, `action`, args-summary (no secrets), result.
- Mouse failsafe (pyautogui corner) applies to `input` actions.
- **Screenshots — TEMPORARY cloud exception (profile `cloud_temp`, 2026-10-05 RAM pivot):** a downscaled capture (`config.yaml → vision.max_px: 1280, quality: 70`) MAY be sent to the CLOUD vision provider, and ONLY when all of: (1) profile is `cloud_temp`; (2) the foreground window matches nothing in `privacy.blocklist_apps`; (3) `privacy.redact` scrubbing ran on any extracted text; (4) the image is never logged or persisted (`privacy.debug_capture` stays false); (5) Private Mode is off — Private Mode disables ALL model calls (LLM + vision), leaving only the fastpath. **Under profile `local` (Wave 6 cutover): screenshots never leave the machine — local vision only, ever.** Marked TEMPORARY; the integrator removes this exception at cutover.

## 8. Orb states & rendering contract

Semantic states (server-authoritative): `starting | reconnecting | offline | idle | listening | thinking | acting | speaking | confirm | error | private_overlay`. `orb_state` always carries base `state`; private/paused are `mode` (rendered as tint/ring overlay so cloud-availability is always visible). `jobs_active` → orbiting dots (cap display at 9).
**Additional `orb_state` fields:** `shape_hint: circle|triangle|square|pentagon|hexagon|octagram` (morph target chosen by the current foreground job's task kind — mapping lives in `config.yaml → orb.shape_map`; orb falls back to `circle` when absent) and `task_kind: system|files|web|media|llm|gui|none`.
**Speaking sync:** `speak` chunks carry `amplitude` (0–1, required) and optional `pitch_hz` (float, may be absent) — the renderer pulses scale/brightness from amplitude and tints/breath-rate from pitch. If `pitch_hz` is never sent, amplitude alone drives the pulse (graceful).
Orb renders its own smooth transitions (state crossfade ~300 ms, shape morph ~600 ms ease) from these discrete events; the server never pushes frames.

## 9. Confirmation flow (voice-first, brief §7 + addendum §7)

1. Brain's confirmation module (code-enforced, per-job, before tool dispatch) emits `needs_confirm{job, question, actions[], expires_at}` → orb shows amber + speaks the question.
2. User replies by speech (Body mic → `stt_final`) or text/orb menu. Free text goes through a small intent check (yes/no/modify).
3. `confirm_resp` resolves the job: yes → job continues with a scoped grant recorded in the job record; no → job `cancelled` with spoken "Aborted."; timeout (default 30 s, configurable) → **abort** (never auto-approve).
4. Concurrent jobs each carry their own pending confirmation; confirming one never grants another.

## 10. Error codes

`E_AUTH`, `E_AUTH_RATE`, `E_PROTO`, `E_BAD_MSG`, `E_UNSUPPORTED`, `E_RATE_LIMIT`, `E_LOCK_BUSY`, `E_TIMEOUT` (action/step timeout), `E_CONFIRM_TIMEOUT`, `E_CANCELLED`, `E_PROVIDER_429` (rate limit), `E_PROVIDER_5XX`, `E_PROVIDER_AUTH`, `E_LOCAL_OOM` (GPU/RAM), `E_LOCAL_DOWN` (ollama dead), `E_OFFLINE` (no network, local fallback unavailable), `E_BUDGET` (spend ceiling reached — refuse until the reset), `E_INTERNAL`.
**Retry semantics:** retryable (transient — client/Brain may retry after backoff): `E_RATE_LIMIT`, `E_LOCK_BUSY`, `E_TIMEOUT`, `E_PROVIDER_429`, `E_PROVIDER_5XX`, `E_LOCAL_DOWN`, `E_OFFLINE`. Fatal (never auto-retried): `E_AUTH`, `E_AUTH_RATE`, `E_PROTO`, `E_PROVIDER_AUTH`, `E_CANCELLED`, `E_CONFIRM_TIMEOUT`, `E_BAD_MSG`, `E_UNSUPPORTED`, `E_BUDGET` (auto-retry cannot help until the ledger window resets), `E_LOCAL_OOM` (recover by unloading models, not by retrying the call), `E_INTERNAL`.
Recoverable vs fatal is defined per-callsite; clients surface `error.detail` as subtitle text only when `code` ∈ {E_LOCK_BUSY, E_TIMEOUT, E_CONFIRM_TIMEOUT, E_PROVIDER_429, E_BUDGET, E_LOCAL_OOM, E_LOCAL_DOWN, E_OFFLINE} (brief communication rules).

## 11. Security invariants (protocol level)

- Everything is localhost-only; **no other listeners** exist (security-reviewer checks this).
- Token never appears in any frame after `auth`, in logs, or on the orb.
- `powershell` actions use a fixed script registry (no arbitrary command strings cross the wire).
- All text arriving from tools/web/screenshots is tagged untrusted by the Brain before it reaches any model (brief §7).
- Frames are validated with pydantic models server-side; malformed → `E_BAD_MSG`, repeated abuse → close.
- **TEMPORARY (profile `cloud_temp`):** the "screenshots never leave the machine" invariant is relaxed exactly as specified in §7 (downscale + blocklist + redaction + no image logging + Private Mode disables all model calls). This is the ONLY cloud data-egress exception in the protocol and it disappears at the Wave 6 local cutover. Local model paths stay in the repo the whole time — never deleted.

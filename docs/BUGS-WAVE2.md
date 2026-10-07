# BUGS-WAVE2 — live E2E gate findings (integrator, 2026-10-07 ~00:00)

Evidence from the LIVE Wave-2 E2E run (real stack: supervisor + brain + body + orb +
fish + relay). Gate result: **3/5 WAVES exit criteria PASS** (2 spoken answers,
6 distinct orb states, pause/private/kill). Criteria 1 & 3 blocked by bugs below.
Every bug is assigned to a lane — see `docs/lanes/*.md` Wave-3 sections.

**Speed mandate (user, 2026-10-07):** cloud models are paid and authorized
(`docs/PAID_USAGE.md`) — every lane aims for NEAR-INSTANT responses: fast cloud
model ids by default (flash-class / `opencode-go/mimo-v2.5`), minimal retries/
timeouts, fish-speech stays the only local model (TTS).

---

## Bug A — vision E_OFFLINE in live brain (router lane) — **FIXED, needs regression test**

- **Symptom:** `what am I looking at` → "Vision is unavailable right now (E_OFFLINE)"
  from the live WS path; direct in-process probe of `brain.router.vision()` returned
  a REAL answer ("Blue", provider=go_vision, model=deepseek-v4-flash-vision-exp).
- **Root cause #1 (fixed):** `GoVisionProvider` did not send the mandatory
  `x-opencode-session` header → Go endpoint returned
  `HTTP 400 MissingSessionID` (docs: opencode.ai/docs/go → "Where can I use it").
  Fix landed in `brain/router/zen.py` (`extra_headers={"x-opencode-session":
  f"raphael-brain-{os.getpid()}"}`) — committed by integrator as glue.
- **Root cause #2 (test hygiene):** the "brain restart" during E2E silently no-oped —
  `kill $(cat /tmp/raphael-brain.pid)` used a STALE pid file (6459; process gone).
  Real listener was pid 6114 from bring-up, i.e. every live test pre-restart ran
  against pre-fix code. After a REAL restart (pid 17539, pid file updated): E_OFFLINE
  gone. **Lesson: resolve the real listener via `ss -tlnp | grep :8765`, never trust
  the pid file alone.**
- **Lane task:** router adds a regression test asserting every go_vision HTTP request
  carries `x-opencode-session` (+ custom User-Agent already from httputil); confirm
  live E2E path end-to-end when the stack is next up.

## Bug B — `open_app` fails for "open YouTube and search lo-fi" (pc-control + router)

- **Symptom:** job `j_20261007_0033` (+ 2 retests post-restart) → `Running open_app`
  → `open_app failed.` The USER saw a **blank Windows terminal window open, then
  error** — i.e. body DID launch something (cmd-style spawn) and it failed.
- **Evidence:** `logs/body.log`: `act_req: open_app for job ...` with **no act_res**
  line; subtitle "open_app failed."; retested after genuine brain restart — same.
- **Suspects:**
  1. body `open_app` implementation shells out via cmd (blank window) and fails on
     non-existent/URL targets — needs `Start-Process`/`os.startfile` semantics,
     correct error act_res, and no console window flash.
  2. Router/fastpath tool SELECTION: a YouTube search should map to
     `search_youtube` / `launch_url`, not `open_app`.
- **Lane split:** pc-control owns body's open_app robustness + act_res error
  surfacing; router owns the intent→tool mapping for "open <site> and search <q>".

## Bug C — orb speaking visuals: no pulse + "cages stuck in weird shape" (orb lane)

User observed while she spoke: (1) orb did not pulse with her voice,
(2) lattice/cage visual stuck in a weird shape.
- **Verified working:** full chain brain→main→preload→renderer — instrumented logs
  showed `[ws-status] rx orb_state -> speaking` → `preload rx orb_state -> speaking`
  → `[renderer] rx orb_state -> speaking` → `[renderer] STATE CHANGE -> speaking`,
  zero exceptions in `~/.config/raphael-orb/main-errors.log`.
- **Suspects:**
  1. **Pulse:** speak-frame amplitude events reach MAIN (`[ws-status] rx speak ->
     chunk seq=N`) but renderer `[renderer] rx speak` console lines were NOT seen —
     check `window.raphael.onSpeak` wiring / preload 'speak' forwarding / the
     `ev.seq <= lastSpeakSeq` stale-seq guard in `renderer.js` (initial value +
     fresh utterances starting at seq 0 can drop the first full utterance).
  2. **Stuck cages:** state flickers `speaking → listening → speaking` BETWEEN
     sentences (see Bug E) → repeated `startMorphTo` restarts mid-ramp; morph ramp
     may wedge when interrupted (also check poseLock paths).
  3. **History:** for most of the E2E window the orb was a stale process from the
     23:23 supervisor launch (possibly wedged GPU/render loop — states applied in
     JS but frame never updated). The relaunch fixed delivery; the RENDER polish
     bugs above remained in user testing.
- **Re-instrumentation guide (was reverted for clean lanes):**
  - `ws-status.js` case `'orb_state'`: `console.log('[ws-status] rx orb_state ->', msg.state, ...)`
  - `ws-status.js` case `'speak'`: same for speak frames
  - `renderer.js` `onOrbState` entry + state-change block (line ~718): `[renderer] ...`
  - `preload.js` onOrbState: appendFileSync('/home/dami/raphael/logs/orb-renderer.log', ...)
  - relaunch electron with `--enable-logging` or renderer console never reaches stdout.

## Bug D — live TTS did not use the JP slime reference (voice lane)

- **User decision (2026-10-07):** the JP slime voice is PERMANENT ("keep the
  japanese please ... soooo much better"); Zira is retired as too robotic.
  `config.yaml → voice.tts_voice = assets/raphael_reference_jp.wav` (committed).
- **Symptom:** direct fish renders using `assets/reference/raphael_reference_jp.wav`
  as reference sound exactly like the approved samples (user heard + approved
  A/B; master line for Insta), but LIVE brain answers during E2E sounded like a
  NON-Japanese/generic voice.
- **Suspects (voice lane):**
  1. `VoiceConfig.tts_voice_path` resolution — relative path vs brain's CWD; if the
     file is "missing" `_references()` silently returns `[]` → fish DEFAULT voice
     (tts.py:343-348, no error logged).
  2. brain phrase cache (tts.py `PhraseCache`, keyed by TEXT only) replaying old
     Zira-era wavs for repeated texts.
  3. fish-side `use_memory_cache: on` keyed by text across different references.
- **Live-proof step (wave-3 close gate checklist, voice request ACCEPTED 2026-10-07):**
  at the next user-gated bring-up run
  `brain/.venv/bin/python brain/voice/scripts/prove_reference.py` — PASS = exit 0 +
  `[tts] ref sent: path=.../assets/raphael_reference_jp.wav bytes=751686 sha1=f64bd512ea1e`.
- **Task:** make ref-loading LOUD (log ref path + bytes sent per synthesis; a
  missing ref must fail or warn), clear/namespace the phrase cache after ref
  changes, verify live speak uses the JP ref (log evidence), then re-run the
  spoken-answer gate step.

## Bug E — `speaking → listening → speaking` flicker between sentences (brain-core)

- **Evidence:** renderer logs during a 2-sentence answer:
  `STATE CHANGE -> speaking` … `-> listening` … `-> speaking`.
- **Cause area:** `brain/orbstate.py derive_state()` reads engine/mic state during
  the TTS pause between sentence chunks and derives `listening` instead of holding
  `speaking` for the utterance's duration.
- **Task:** hold `speaking` until the utterance (all sentence chunks) ends
  (speak end event), never derive mid-utterance; unit test the flicker sequence.

## Bug F — foreground verification refuses vision on a normal window (computer-use)

**ROOT CAUSE CORRECTED (computer-use, 2026-10-07, evidence-backed — original hypothesis
below disproven):** `capture_screen` masked a body-WS disconnect (log: `1012 service
restart` between jobs 42–44) as `E_NO_FOREGROUND`. Job 43 (the refusal) has NO
`foreground_info` record in logs/actions.log while jobs 35/41 succeeded in 16ms with
real window titles — the tool never ran; `hub.get_body_session()` was None mid-restart.
Fix in flight: split reachability vs privacy verdicts, close the UIA-path blocklist hole,
terminal-foreground tests.

- **Symptom (post-restart, fresh code):** `what am I looking at` →
  "I can't verify which window is in front, so I won't send a screenshot."
  Foreground at that moment = Windows Terminal title "Ubuntu-26.04" (queried from
  PowerShell: GetForegroundWindow works, title non-empty, NOT a blocklist app).
- **Task:** find why body's `foreground_info` returns unverifiable/failed here
  (process resolution returned empty for the terminal host?), fix or relax the gate
  for non-blocklisted windows, add a test with a terminal foreground.

## Bug G — supervisor/orb ownership stale after integrator relaunch (infra)

- Integrator killed the supervisor-tracked wsl wrapper (old orb pid 85756) and
  relaunched orb manually (`electron . --no-sandbox --disable-gpu-sandbox
  --ignore-gpu-blocklist --enable-logging`, currently pid ~15449) for debugging.
  Supervisor heartbeats may show a stale orb pid; a real orb exists.
- **Task:** next bring-up, launch orb ONLY via supervisor; ensure heartbeat tracks
  the actual pid; `raphael stop` + verify full teardown leaves zero processes.

## Gate status (honest record for WAVES.md)

| # | Criterion | Result |
|---|-----------|--------|
| 1 | text command "open YouTube and search lo-fi" executes | **FAIL** (Bug B) |
| 2 | free-form answer spoken in her voice | **PASS** (speak chunks + subtitle, fish engine) |
| 3 | vision answer via Go paid slot ≤$1/day | **PARTIAL** — paid slot verified with real answer in-process (Bugs A fixed); live WS path blocked by Bug F |
| 4 | orb states distinct live | **PASS** (6 states: idle/listening/thinking/acting/speaking/error) |
| 5 | pause / private / kill work | **PASS** (acks verified; private blocks cloud: "Private mode is on — cloud models are disabled. Fast path only.") |

`wave-2-gate` tag NOT created — re-run full gate at wave-3 close after Bugs B/D/F.

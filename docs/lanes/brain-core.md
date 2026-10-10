# brain-core — lane task list (owner: brain-core lane)

Read: docs/AGENT_RULES.md -> docs/WAVES.md -> this file. Status log: docs/status/brain-core.md. Requests to you: `ls docs/requests/*__to__brain-core__*.md`.

Merge-order position: see docs/WAVES.md

## Wave 2 tasks (docs/WAVES.md (current_wave: 2))
- [x] Config loader: config.d/*.yaml deep-merge + profile overlay + defaults (INTERFACES §c). → `brain/config.py`
- [x] Instance derivation: RAPHAEL_INSTANCE -> port/pidfile/lock/mutex/CDP/data-dir (INTERFACES §d); unset = main, zero behavior change. → `brain/config.py` (pidfile moved out of /tmp, main dual-writes legacy — see docs/requests/brain-core__to__integrator__pidfile-out-of-tmp.md)
- [x] Conversational loop with persona: chat(stream=True) sentence streaming, ack-first, length-adaptive (persona per addendum §10). → `brain/loop.py` (persona from config.voice_personality, multi-turn trimming, tool loop w/ step cap, tokens→sentences→speak events, fastpath first)
- [x] Tool auto-discovery: walk brain.tools.* at import, validate strict JSON-Schema specs (INTERFACES §b). → `brain/tools/__init__.py` (+ `tool_specs()`, `validate_args()`, `as_untrusted()`)
- [x] orb_state emission audit vs INTERFACES §e (every state provably emitted; jobs_active/mode/shape_hint/task_kind/provider/model). → `brain/orbstate.py` + fake-ui sequence tests
- [x] Typed input channel: command source=text + orb submit_text path end-to-end. → ws handlers + tests
- [x] Confirmation hardening: high-risk (config safety.confirm_actions) needs NON-voice confirm; voice yes only low-risk; timeout aborts. → `brain/confirm.py` (§8 review notice filed)
- [x] Private Mode under cloud_temp = fast path only + spoken/subtitled notice (no LLM calls). → `brain/loop.py`
- [x] REST `POST /say` (status/jobs/cancel/control exist) — `brain/app.py`, request filed.
- [x] Mock tests only; no live providers, no real stack. **TTS hermetic (2026-10-06):** `brain/tests/conftest.py` mocks `VoiceStack.speak/warmup` — brain tests never touch/spawn Fish (INTERFACES §d); a live fish on :8777 had made speak-bound tests slow/flaky.
- [x] pc-control request `tool-discovery-and-llm-tools` (4 items, APPROVED 2026-10-06):
  - [x] (1) pkgutil auto-discovery at import + **lifespan** re-run → `brain/app.py` (brain/tools/pc registers on a live Brain; tests/ modules skipped).
  - [x] (2) native `chat(messages, tools=..., purpose='tool')` preferred + `llm.prompt_block()` textual fallback in the system prompt (extractor now balanced-brace/nested-args safe).
  - [x] (3) dispatch-time confirm: `classify(text, tool=...)` + registry `risky` metadata via new `confirm.tool_decision()` (Core Guard strengthening).
  - [x] (4) registry-level load-time rejection: name/category/description/schema all validated in `register()`.

## Coord task batch (2026-10-06, 5 assigned — all resolved)
- [x] (1) ws `_on_audio_end` `reason=reason` → **LANDED ON MAIN by integrator (8e2d9fb); skipped, not re-implemented.**
- [x] (2) `confirm.voice_safe(job_id)` predicate (voice request piece 1): pending + risk=='low' only; unknown/high/no-pending → False (fail-closed, Core Guard split not re-derived by voice).
- [x] (3) no-screenshot-result-journaling: `ws._on_act_res` journals `<omitted N b64 chars>` summary; PLUS source-level guard in `loop._execute_tool` (b64 never reaches results/job_events either — PROTOCOL §7(4)); delivery to the waiter stays full.
- [x] (4) tool-integration-hooks x3: SPECS convention in the loader (raw-schema dicts AND pc ToolSpec objects; validate+fail loud, SPECS precedence over register(schema=)), `wiring.bind_loop(running_loop)` in app lifespan (guarded import), six fastpath `see_screen` intents (question = full utterance, needs_lock false).
- [x] (5) `validate_schema` accepts EMPTY properties iff `required=[]` + `additionalProperties:false` (zero-arg PROTOCOL §7 tools); missing/invalid `required` still rejects (t_bad2/t_bad3 keep passing).

## Wave 3 (start only when WAVES.md says so — current_wave: 3)

Wave 2 is MERGED; live gate was 3/5 — evidence + bug dossiers: `docs/BUGS-WAVE2.md`. SPEED MANDATE: cloud is paid now — near-instant responses, fast model defaults (AGENT_RULES Rule 15, WAVES.md constraints).

- [P0-BugE] No `speaking → listening → speaking` flicker between sentence chunks: `orbstate.derive_state()` must hold `speaking` until the whole utterance ends (evidence: docs/BUGS-WAVE2.md Bug E). Unit test the exact frame sequence. **[x] DONE 2026-10-07** — precedence speaking > listening in `derive_state()` + `emit('listening')` guarded while a speak pipeline is active; barge-in (speak_end) still reaches listening; confirm still beats speaking; exact-sequence unit tests in `brain/tests/test_orb_states.py`.
- [x] **Wave-3 goal: job-concurrency polish** (WAVES.md wave 3 — queue/priority/cancel edge cases you own). DONE 2026-10-07: lock fairness guard (ownerless-with-waiters promotes OLDEST waiter), `engine.on_job_cancelled` full-scope hook interrupting only the cancelled job's speech, `stats().input_lock.job` real-id fix; 8 tests incl. HTTP e2e (37b8571).
- [x] **Wave-3 goal: proactive `Notice` events** (WAVES.md wave 3 — brain-core emits). DONE 2026-10-07 (APPROVED scope: frame as proposed, roles ui+cli only, emitters 1+2, emitter 3 deferred): `brain/notice.py` (ratelimited, fail-silent, presence-only) + `llm.py` outage/recovery wiring + boot-recovery pending-flush to the first ui/cli auth + `engine.interrupted_at_boot`; 9 tests in `brain/tests/test_notice.py`.
- [x] **Wave-3 goal: memory hooks** (WAVES.md wave 3 — seams for tools-memory's wave-3 work; contract via docs/requests/ if you need anything cross-lane). DONE 2026-10-07: producer seam `brain/loop.py::_conversation_hook` → `brain.memory.conversation.on_turn(...)` (fail-silent; absent = no-op, raising hook cannot fail a job; e2e tested), API proposed for tools-memory in `docs/requests/brain-core__to__tools-memory__conversation-hook.md` (afdc682).
- [SPEED] Near-instant command→ack→first-subtitle on the fast path (Rule 15) — trim any gratuitous waits you own. **[x] AUDITED 2026-10-07** — no gratuitous waits in brain-core: ack is a sync frame, queue put→get wakes immediately (the 0.5 s in `_worker_loop` is an empty-queue poll cap, not a delay), fastpath classify is sync regex, subtitle broadcast is sync; every timeout in loop/confirm/llm/ws is a failure deadline, never an initial delay. Documented in status.

## Wave 3 — approved requests (both router)
- [x] `fastpath open+search mapping` (Bug B router half, APPROVED): "open youtube and search lo-fi" → `search_youtube{query}`, new `search `/`search for `/`youtube ` intents, all existing open branches unchanged → `brain/fastpath.py` + `brain/tests/test_fastpath_open_search.py`.
- [x] `surface-usage-in-status` (APPROVED): additive `router` key on `GET /status` via lazy `brain.router.usage_status()` — `{}` until router's branch merges, `{'error': 'unavailable'}` on failure, endpoint never goes down → `brain/app.py` + test.

## Wave 3 — goals (after P0)
- [x] Job concurrency polish (input-lock fairness, per-job cancel) — `brain/jobs/lock.py` fairness guard + `engine.on_job_cancelled` per-job speech interrupt + `stats().input_lock.job` fix; 8 tests (fbb9d07).
- [x] Conversation-memory hooks to tools-memory — producer side wired in `brain/loop.py::_conversation_hook` (fail-silent, absent-module no-op), API proposed in `docs/requests/brain-core__to__tools-memory__conversation-hook.md`; e2e test w/ fake module incl. raising-hook survival.
- [x] Proactive Notice events — **DONE + APPROVED + merged**: contract `brain-core__to__integrator__notice-events.md` approved same-day; `brain/notice.py` emitters (ui+cli only, per-key ratelimit, fail-silent, presence-only) + boot-recovery pending-flush + provider outage pair + SEC-3 cloud-upload indicator; PROTOCOL §3 rows landed by the integrator at merge. Tests `brain/tests/test_notice.py` (13: exact shapes, ratelimit, 1-pair/10min outage, redaction-free text, boot-notice e2e, storm bounds).

## Wave 4 (start only when WAVES.md says so — current_wave: 4)

Wave 3 is MERGED + **GATE PASSED** (tag `wave-3-gate`, all six criteria live, acoustic voice included). Wave-4 theme per WAVES.md: hardening, resilience tests, audit fixes, crash recovery, evolution infrastructure. Rule 15 speed mandate still binds.

- [x] Crash-recovery: interrupted-job journal replay hardening (post-restart task resume), engine kill-safety matrix, Notice emitter outage-storm drill (Wave-3 addition), input-lock arbitration stress. DONE 2026-10-07 — see `brain/tests/test_resilience.py` (8) + storm drills in `test_notice.py` (+4); fixes: stale `pending_confirm` cleared on interrupted rows, `engine.shutdown()` now fires the per-job kill hook (speech stops on engine kill), TestClient never writes live pidfiles (`_pidfile_targets()` empty under pytest). NOTE: actual auto-RESUME of interrupted jobs stays forbidden by PROTOCOL §5 — journal is verified fully replayable for explicit resume only.

## Wave 5 (start only when WAVES.md says so — current_wave: 5)

Wave 4 is MERGED + **GATE PASSED** (tag `wave-4-gate`, 10/10 lanes, mock 308 green). Wave-5 theme per WAVES.md: Raphael features — Answer/Notice/Report formats, Analysis, Simulation, parallel-minds visuals, persona tiers. Rule 15 speed mandate binds; shared-contract changes go through integrator requests. Carried items are noted in WAVES.md gate record (shadow row; C1+C2 residual).

- [x] Output-format engine: Answer/Notice/Report format emitters per WAVES wave 5, Analysis + Simulation job kinds (fastpath + engine), parallel-minds job fan-out seams. **DONE 2026-10-07** (contract APPROVED as proposed): `brain/formats.py` answer/report emitters (roles ui+cli, caps sections≤10/summary≤500/text≤2000 trimmed pre-emit, answer on EVERY final reply, provider/model omitted when no router hop); engine validated `kind`/`parent` metadata + `submit_fanout()` seam + `job_event` kind/parent echo (absent when unknown); WS `command` + REST `POST /jobs` accept validated optional `kind`/`parent` (typos → E_BAD_MSG/422); fastpath `analyze/analyse/simulate` triggers; Simulation = tools[] + no prompt-block, Analysis keeps tools + report frame. Tests: test_formats.py (5) + test_agent_loop e2e (4) + kind/fanout units (2).

## Wave 5H — audit hardening sprint (inside wave 5; gate `wave-5h-gate`)

- [x] Read `docs/audit-tasks/brain-core.md` → your IDs: **SEC-3, ARCH-5, ARCH-6** — VERIFY-FIRST, reported with file:line + green CI (QA-4 ✓). **SEC-3: CONFIRMED→FIXED** — evidence `brain/ws.py` (`audio_reason = 'wake'` fabricated default, `else 'wake'` label coercion, straight into `voice.transcribe_result`) + `brain/voice/activation.py:147-150` (`return GateDecision(True, reason or "unknown")` / `error_fail_open` = FAIL OPEN, voice's file → request `brain-core__to__voice__sec3-gate-fail-closed.md`); brain-core half fixed (`Session.audio_started` fail-closed guard, `Voice input sent to cloud STT.` notice, upload gated inside `transcribe_result`), tripwire `brain/tests/test_sec3_cloud_stt_gate.py` **4/4**. **ARCH-5: DESIGN-ONLY** (per packet rule) — evidence `config.yaml:174-180` (`cloud_temp: {}` + `local` only, header still "TEMPORARY PIVOT") → request `arch5-profile-shape-design.md`; DECISION received (keep-name-canonical, integrator applies the hybrid block, alias skipped) → nothing left to code. **ARCH-6: NOT-APPLICABLE-as-found (zero pre-existing instrumentation) → IMPLEMENTED** — `brain/latency.py` (stages stt/routing/llm_first_token/tool_start/tts_first_audio + bounded histograms count/p50/p95/max, `/status.latency`) + `brain/logjson.py` (value-blind slog, every string via `privacy.redact`, redactor-broken ⇒ drop), emission points in ws/engine/loop, tests `test_latency_logging.py` **6/6**. QA-4 CI: tests-heavy **37714371665** + **37778951946**, ci **37778966595** (all SUCCESS). Source register: `docs/AUDIT-2026-10-07.md`. Rules followed: stack never spawned for the audit, one suite at a time, heavy suites in cloud, Rule 15.

## Later waves
- Per docs/WAVES.md — do not start early (AGENT_RULES §11).
- Wave 3 (when current_wave=3): job concurrency polish (input-lock fairness, per-job cancel), conversation-memory hooks to tools-memory, proactive Notice events.

## Wave 5P — persona adoption (ACTIVE 2026-10-09; full spec: docs/research/persona/06-CODE-ADOPTION-PLAN.md)
- [ ] **P1 tier assembly**: read `config.yaml → persona` (tier + tiers map); select the tier's prompt file (`docs/evolution/persona/tier-*.md`) when assembling LLM messages; add a `tier` field to `/control` (set/get persona.tier at runtime; invalid tier = loud error). Tests: tier selection, mid-session switch, missing prompt file = fail-closed to great_sage with a warn Notice.
- [ ] **P3 confirm policy**: `brain/confirm.py` consults `config.yaml → safety.confirm_policy` (default + classes) BEFORE the risk regex; unclassified tools fall back to the regex (R1 config-driven-risk finding). "what requires your confirmation" answers this map. Tests: policy matrix, fallback, and qa's pinned confirm/act tests stay green.
- [ ] **P4 clarify-on-ambiguity**: fastpath-miss + weak-intent path emits ONE tier-toned clarifying question (`clarify.max_questions:1` default in config.d); after 1 repeat → best-effort act + report or refusal, never N guesses. Tests: ambiguous fixtures, clarify→answer, no-clarify-when-confident.
- [ ] **P5 slot-aware injection**: memory retrieval injection respects the active context slot (tools-memory provides the API; default slot = today's behavior byte-for-byte).

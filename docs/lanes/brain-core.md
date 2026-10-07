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
- [ ] **Wave-3 goal: job-concurrency polish** (WAVES.md wave 3 — queue/priority/cancel edge cases you own).
- [ ] **Wave-3 goal: proactive `Notice` events** (WAVES.md wave 3 — brain-core emits).
- [ ] **Wave-3 goal: memory hooks** (WAVES.md wave 3 — seams for tools-memory's wave-3 work; contract via docs/requests/ if you need anything cross-lane).
- [SPEED] Near-instant command→ack→first-subtitle on the fast path (Rule 15) — trim any gratuitous waits you own. **[x] AUDITED 2026-10-07** — no gratuitous waits in brain-core: ack is a sync frame, queue put→get wakes immediately (the 0.5 s in `_worker_loop` is an empty-queue poll cap, not a delay), fastpath classify is sync regex, subtitle broadcast is sync; every timeout in loop/confirm/llm/ws is a failure deadline, never an initial delay. Documented in status.

## Wave 3 — approved requests (both router)
- [x] `fastpath open+search mapping` (Bug B router half, APPROVED): "open youtube and search lo-fi" → `search_youtube{query}`, new `search `/`search for `/`youtube ` intents, all existing open branches unchanged → `brain/fastpath.py` + `brain/tests/test_fastpath_open_search.py`.
- [x] `surface-usage-in-status` (APPROVED): additive `router` key on `GET /status` via lazy `brain.router.usage_status()` — `{}` until router's branch merges, `{'error': 'unavailable'}` on failure, endpoint never goes down → `brain/app.py` + test.

## Later waves
- Per docs/WAVES.md — do not start early (AGENT_RULES §11).
- Wave 3 (when current_wave=3): job concurrency polish (input-lock fairness, per-job cancel), conversation-memory hooks to tools-memory, proactive Notice events.

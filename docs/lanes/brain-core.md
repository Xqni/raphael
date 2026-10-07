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

## Later waves
- Per docs/WAVES.md — do not start early (AGENT_RULES §11).
- Wave 3 (when current_wave=3): job concurrency polish (input-lock fairness, per-job cancel), conversation-memory hooks to tools-memory, proactive Notice events.

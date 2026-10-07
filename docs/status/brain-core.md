# brain-core — status

Updated: 2026-10-06 (coord round 2: pc-control's APPROVED 4-item request done on rebased branch — re-posting wave_done)

## Done
- (bootstrap) shared contracts read (AGENT_RULES/WAVES/OWNERSHIP/INTERFACES).
- **Wave 2 task 0 — FOUNDATIONS (committed first, other lanes unblocked):**
  1. **Instance isolation** — `brain/config.py`: `RAPHAEL_INSTANCE` → port (§d table), CDP port, data-dir `~/.raphael/<instance>/`, body-lock/supervisor-mutex names, pidfile. Pidfile = `<data-dir>/brain.pid` (out of world-writable /tmp); instance `main` ALSO writes legacy `/tmp/raphael-brain.pid` so supervisor keeps working byte-identically → request `pidfile-out-of-tmp.md`.
  2. **Config loader** — `config.yaml` → `config.d/*.yaml` (filename-sorted deep-merge: maps merge, lists/scalars replace) → `profiles.<profile>` (env `RAPHAEL_PROFILE` > file `profile:` > `cloud_temp`) → env overrides. API `get_config()/cfg_get()/load_config()/reset_config_for_tests()`.
  3. **Tool auto-discovery** — `brain/tools/__init__.py`: pkgutil walk of `brain.tools.*` at import, module-level `register()` picked up (0-arg or registry-arg), strict JSON-Schema validation (typed+described properties, `required` ⊆ properties, `additionalProperties:false`) rejecting loudly, `validate_args()` strict at call time, `tool_specs()` for the model, `as_untrusted()` provenance wrap (§9), broken modules recorded in `load_errors()` (never fatal; `strict_discover()` raises for tests).
  4. **Router seam** — `brain/llm.py` calls ONLY INTERFACES §a `brain.router.chat(...)`; structured stub (`E_OFFLINE`) until the router lane lands `chat`; `RouterError.code` → PROTOCOL §10; `plan()` compat kept; stream path never raises.
- **Wave 2 task 1 — orb_state emission audit** → `brain/orbstate.py` (ONE frame builder so §e is provable) + triggers: `starting` boot snapshot / `idle` after boot / `listening` on audio_start(+off on audio_end) / `thinking` on job stats / `acting` on act_req+input-lock / `speaking` on first speak start→end / `confirm` on pending (now REAL — see side-fix) / `error` transient-3s-then-idle / reconnecting+offline stay orb-client-owned. EVERY frame: `jobs_active`, `mode`, `shape_hint` (config `orb.shape_map`), `task_kind`, `provider`/`model` once known; private/paused = overlays, never states.
- **Wave 2 task 2 — conversational agent loop** (`brain/loop.py`): persona built from `config.voice_personality` (character/style/speech_forms/banned/`spoken_reply_max_sentences`); multi-turn context with message+char trimming (`config.d/brain-core.yaml → agent.*`); tool-calling loop (`chat(tools=specs)` → strict arg validation → confirm → gui act_req/local thread → UNTRUSTED feed-back → repeat, cap `agent.max_tool_steps: 6`); **stream tokens → sentence chunks → speak events** (sync subtitles, queued `_SentenceSpeaker`, barge-in aware, spoken-sentence cap with full text on screen); fastpath stays FIRST; `command` from ui/cli incl. typed + `orb_input submit_text` end-to-end; zero canned replies — failures are honest (provider/step-cap/notice strings).
- **Wave 2 task 3 — confirmation hardening** (`brain/confirm.py` + ws): high-risk = `config.safety.confirm_actions` (config authority); voice YES rejected on high-risk (`rejected_channel`, pending survives, hint subtitle), voice NO always works, low-risk voice yes allowed, click/typed always allowed, timeout still aborts; dispatch-time gate for model-picked risky tools; voice answers also route from voice-source commands and `audio_end` STT. → review notice `confirm-hardening.md`.
- **Wave 2 task 4 — Private Mode** under cloud_temp: fastpath first, then NO LLM call + spoken/subtitled notice (`PRIVATE_NOTICE`), job done honestly; test asserts ZERO chat calls.
- **Wave 2 task 5 — REST for the CLI**: `POST /say` added (status/jobs/cancel/control already present) → request `rest-say-endpoint.md`.
- **Side fix (pre-existing bug found by the new tests)**: jobs now actually transition to store status `awaiting_confirm` (back to `running` on grant) — before, only the *event* said so, `stats.jobs_pending_confirm` was always 0 and the orb could never derive §e `confirm`.
- **coord round 2 (2026-10-06) — pc-control request `tool-discovery-and-llm-tools`, all 4 items APPROVED by decision, on branch rebased onto main:**
  1. **Discovery at import + lifespan** — `brain/app.py` lifespan re-runs `tool_reg.discover()` (idempotent, never fatal, `tests`/`conftest` modules skipped) so `brain/tools/pc` registers on a live Brain; test proves a subpackage landing after first import appears on lifespan.
  2. **Tools reach the model** — native `llm.chat(messages, tools=specs, purpose='tool')` stays preferred; NEW `llm.prompt_block(specs)` renders the catalog into the system prompt in the exact `{"tool": name, "args": {...}}` format for providers without native tools; `_extract_tool_call` rewritten as a balanced-brace scanner (nested args + key-order safe — the old `[^{}]*` regex silently broke on nesting).
  3. **Dispatch-time confirm** — `classify(text, tool=...)` (existing) + NEW registry-`risky` fallback `confirm.tool_decision()`: a tool flagged `risky=True` outside `RISKY_TOOLS` still prompts (Core Guard strengthening; §8-approved direction).
  4. **Registry-level load rejection** — `register()` now rejects non-string/empty names, empty/descriptless entries and non-string categories on top of the existing strict schema validation.
- **TTS hermeticity fix (rules compliance + determinism)** — `brain/tests/conftest.py` mocks `VoiceStack.speak`/`warmup`: a LIVE Fish server on :8777 was making speak-bound tests depend on real GPU synthesis (slow/flaky), and without one, lifespan warmup would have SPAWNED fish (INTERFACES §d forbids: "Never spawn Fish TTS … voice tests mock TTS"). brain tests now run hermetically (agent suite 19 s → 1 s).

## In progress
- — (Wave 2 lane tasks all checked off)

## Blocked
- — (live providers only: router lane's `brain.router.chat` facade; tests mock at the seam)

## Next
- Wave 3 (only when docs/WAVES.md `current_wave` = 3): job concurrency polish (input-lock fairness, per-job cancel), conversation-memory hooks to tools-memory, proactive Notice events.

## Requests — all DECIDED (coord round 2)
- `brain-core__to__integrator__pidfile-out-of-tmp.md` → **APPROVED + APPLIED** (INTERFACES §d updated, infra dual-reads; no action for me)
- `brain-core__to__integrator__rest-say-endpoint.md` → **APPROVED + APPLIED** (PROTOCOL §1 lists POST /say; infra nudged for the CLI)
- `brain-core__to__integrator__confirm-hardening.md` → **APPROVED** (§8: all six changes strengthen; request closed)
- pc-control's `tool-discovery-and-llm-tools` → **APPROVED, all 4 items = my remaining Wave 2 work → DONE this round** (above)
- RAPHAEL_PIDFILE request → **SUPERSEDED** (my lifespan dual-write already matches infra's export; nothing to do)
- Nudge: PROTOCOL §7 act_req gained `list_windows`/`foreground_info`/`list_running_apps` — auto-covered once pc's tools register through discovery; no change needed from me.

## Test output (real runs only — never claim unrun tests)
- `./brain/.venv/bin/python -m pytest -q brain/tests brain/router/tests brain/voice/tests` → **147 passed** (per-file: agent 17, config 20, confirm 16, health 3, jobs 10, llm 11, orb 6, say 4, tools 13, ws 17, router 10, voice 20 — round-2 new: tools +3, llm +1, agent +4)
- `cd tests && ./.venv/bin/python -m pytest -q .` → **10 passed**
- Hermetic: no live providers, no real stack, **no Fish touched or spawned** (TTS mocked in `brain/tests/conftest.py`), no Ollama (AGENT_RULES §5/§7); router faked at the INTERFACES §a seam, STT faked at `voice.transcribe_result`.

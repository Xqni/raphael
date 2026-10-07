# brain-core — status

Updated: 2026-10-06 (Wave 2 foundations landed — INTEGRATOR: items 1-4 below are the "foundations other lanes wait on"; they are committed on `agent/brain-core`, ready to merge)

## Done
- (bootstrap) shared contracts read (AGENT_RULES/WAVES/OWNERSHIP/INTERFACES).
- **Wave 2 task 0 — FOUNDATIONS (committed, other lanes can start):**
  1. **Instance isolation** — `brain/config.py`: `RAPHAEL_INSTANCE` → port (§d table), CDP port, data-dir `~/.raphael/<instance>/`, body-lock/supervisor-mutex names, pidfile. Pidfile is now `<data-dir>/brain.pid` (out of world-writable /tmp); instance `main` ALSO writes legacy `/tmp/raphael-brain.pid` so supervisor keeps working byte-identically — table-update request filed: `docs/requests/brain-core__to__integrator__pidfile-out-of-tmp.md`.
  2. **Config loader** — `config.yaml` → `config.d/*.yaml` (filename-sorted, deep-merge: maps merge, lists/scalars replace) → `profiles.<profile>` overlay (env `RAPHAEL_PROFILE` > file `profile:` > `cloud_temp`) → env overrides. API: `get_config()/cfg_get()/load_config()/reset_config_for_tests()`.
  3. **Tool auto-discovery** — `brain/tools/__init__.py`: pkgutil walk of `brain.tools.*` at import, module-level `register()` picked up (0-arg or registry-arg), strict JSON-Schema validation (`type:object`, typed+described properties, `required` ⊆ properties, `additionalProperties:false`) rejecting loudly at load, `validate_args()` strict at call time, `tool_specs()` for the model, `as_untrusted()` provenance wrap (AGENT_RULES §9), broken modules recorded in `load_errors()` — never fatal, `strict_discover()` raises for tests.
  4. **Router seam** — `brain/llm.py` now calls ONLY the INTERFACES §a facade `brain.router.chat(...)` (chat/vision/transcribe/health are the only doors). Until the router lane lands `chat`, a structured stub returns `LLMResult(ok=False, code='E_OFFLINE')`; `RouterError.code` → PROTOCOL §10 codes; `plan()` kept as compat wrapper; stream path normalizes deltas + final frame and never raises.
- Requests filed for the integrator: pidfile table update (above), `POST /say` PROTOCOL §1 line (`.../rest-say-endpoint.md`).

## In progress
- Wave 2 task 1: orb_state emission audit vs INTERFACES §e (fake-ui-client sequence test).

## Blocked
- — (nothing; router `chat()` facade arrival only affects live providers, tests mock it)

## Next
1. orb_state audit (starting/idle/listening/thinking/acting/speaking/confirm/error + jobs_active/mode/shape_hint/task_kind/provider/model on EVERY transition).
2. Conversational loop (persona from `config.voice_personality`, multi-turn trimming, tool-call loop with step cap, token→sentence→speak streaming, fastpath first).
3. Confirmation hardening (non-voice confirm for `safety.confirm_actions`), Private-Mode notice, `POST /say`.

## Test output (real runs only — never claim unrun tests)
- `./brain/.venv/bin/python -m pytest -q brain/tests brain/router/tests` → **80 passed** (baseline 40 + 40 new: config 20, tools 10, llm seam 10)
- `./brain/.venv/bin/python -m pytest -q brain/voice/tests` → **20 passed**
- `cd tests && ./.venv/bin/python -m pytest -q .` → **10 passed**
- No live providers, no real stack, no Fish/Ollama spawned (AGENT_RULES §5/§7).

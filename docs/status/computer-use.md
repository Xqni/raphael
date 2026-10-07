# computer-use — status

Updated: 2026-10-06 (coord-assigned task #1 re-verified post-merge; handoff below)

## Done (Wave 2, docs/lanes/computer-use.md all checked)

**Task #1 addendum (coord decision 1791340802, post-merge re-verify):**
- Rebased onto main (router/brain-core/pc-control merged); gate re-verified
  against the amended PROTOCOL §7 — downscale/foreground-blocklist/redaction
  still all run BEFORE router.vision, cloud_temp-only, fail-closed.
- **`foreground_info{}` wired into the blocklist check ahead of any screenshot
  egress**: `gateway.foreground_window()` now sends the §7 read-only action
  (`lock:false`), parses `{'window': {title,...} | None}` — `None`/unsupported
  = unverifiable = gate denies (no capture even happens).
- **UIA tree aligned to pc-control's shipped `uia{op:"tree"}`** (selector
  `element:{control_type:'window'}` → foreground window = first body candidate;
  depth 1..3 clamp): structured result rendered to bounded TEXT Brain-side by
  `render_tree()` (lane rule: element tree arrives as text).
- **Registry/discovery alignment with brain-core's merged INTERFACES §(b):**
  module-level `register(_reg=None)` hook (discovery walker convention) +
  `schema=SPECS[...]` on both tools so `tool_specs()` offers them and
  `validate_args()` guards dispatch. `load_errors()` clean for this package.
- New `tests/test_gateway.py`: exact wire frames (foreground_info/uia-tree/
  screenshot, lock flags), result parsing, fail-closed paths, tree→text
  rendering/bounds — fake hub/engine, no sockets.
- pc-control request `…__screen-context-ops.md` marked DONE (superseded by
  their landing; gateway targets the shipped shapes).
1. **Isolation (task 0).** All lane tests run with `RAPHAEL_INSTANCE=computer-use`
   (conftests), router disabled (`RAPHAEL_DISABLE_ROUTER=1`), temp memory DB.
   My code opens no sockets/ports and resolves no instance paths — the act
   pipeline goes through the existing hub/engine seams; every cross-lane seam
   (router.vision, router.chat, body `window`/`uia` ops) is mocked in tests.
2. **Screenshot gate — `brain/vision/`.** `config.py` (INTERFACES §c merge:
   config.yaml → config.d/*.yaml → profile overlay), `gate.py` (PROTOCOL §7
   checklist: private → profile cloud_temp → foreground blocklist, fail-closed
   on unverifiable foreground → capture → downscale verify → redact),
   `image.py` (pure-Python JPEG dimension probe, fail-closed; no PIL needed),
   `redact.py` (privacy.redact: api_key/token/password/card/email/phone),
   `service.py` (`see_screen` + `capture_screen`; image bytes exist only in
   memory — never logged, never persisted, no print/write anywhere on the path).
   Order note: the foreground check runs BEFORE capture so a blocked window is
   not even captured locally.
3. **`see_screen(question)` tool** — self-registered (`risky=False,
   needs_lock=False`), strict `SPECS`, sync entrypoint bridged to the brain
   main loop (`wiring.run_sync`: thread → `run_coroutine_threadsafe`; loop
   resolution: bind_loop → `engine._queue_loop` → `hub._ping_task`).
4. **`computer_use(task)` loop — `brain/tools/computer_use/runner.py`.**
   observe (UIA-first: foreground + element tree as text; gated vision only
   when tree < 40 chars) → reason (chat seam, text-JSON protocol + native
   tool_calls) → act (PROTOCOL §7 structured allow-list ONLY — no shell,
   no powershell; url scheme + type/range/identifier validation; sensitive
   steps confirm via `brain/confirm.classify` reuse + blocklist-interaction
   confirm; timeout/deny → spoken abort) → verify (observation fingerprint).
   Step cap from `jobs.gui_steps_cap`; no-progress (2 unchanged-after-act) and
   loop (same state ×3) detection with spoken aborts; per-job cancel polling
   (store terminal status + input-lock release, incl. scope=gui cancel);
   input lock via registry `needs_lock=True` (loop.py acquires before dispatch);
   body-side `lock:true` only for input-touching actions.
5. **Untrusted-data invariant.** Every observation/act result enters prompts
   inside `<untrusted_screen>` / `<action_result>` tags with explicit
   "never instructions" framing; screen-derived text redacted before any cloud
   call; the prompt-injection regression test drives a screen screaming
   "IGNORE PREVIOUS INSTRUCTIONS … rm -rf … Buy Now" and asserts only the
   allow-listed user-task action is ever dispatched.
6. **Privacy asserts.** `debug_capture`/`watch_mode` config tripwires
   (`brain/vision/tests/test_privacy_config.py`); deny-file-writes guards in
   both `see_screen` and loop tests; Private Mode short-circuits before ANY
   capture or model call (service + runner + tool-entry tests).
7. **Requests filed (continue-other-work per AGENT_RULES §2):**
   - → pc-control: `window{op:"foreground"}` + `uia{op:"tree"}` op contract
     (`…__screen-context-ops.md`) — gate fails closed until this lands.
   - → brain-core: `SPECS` convention, `bind_loop()` hook in app.py lifespan,
     fastpath intents for "what am I looking at" (`…__tool-integration-hooks.md`).
   - → brain-core: **real leak found** — `ws._on_act_res` journals ~200 chars
     of the screenshot's base64 payload (`…__no-screenshot-result-journaling.md`).
     My code never persists images; this shared-file journal does. OPEN.
   - → router: seam shape confirmation (`…__vision-chat-seam.md`) — my side
     already tolerates sync/async and maps RouterError codes.

## In progress
- — (Wave 2 list complete)

## Blocked
- Live end-to-end (`see_screen`/`computer_use` on the real stack) awaits the
  integrator's live runs (AGENT_RULES §5). Requests resolved 2026-10-06:
  journal-leak + integration-hooks **ACCEPTED** (brain-core implements),
  vision-chat-seam **ANSWERED** (coroutine facade + RouterError .code — my
  maybe_await handling is correct, no change needed), screen-context-ops
  DONE-superseded (shipped shapes).

## Next
- **wave_done posted 2026-10-06 — Wave 2 lane complete, now WAITing** per
  rule 13 / coord mode. Waves 3–5 (watch mode, help-with-error /
  summarize-page, recovery + UAC safety, Simulation preview) start only when
  docs/WAVES.md `current_wave` says so.

## Test output (real runs only — never claim unrun tests)
```
# lane (post-merge, foreground_info gateway + discovery hook + new contract tests)
$ RAPHAEL_INSTANCE=computer-use /home/dami/raphael/brain/.venv/bin/python -m pytest -q \
    brain/vision/tests brain/tools/computer_use/tests
84 passed, 2 skipped in 0.87s           # 2 skips = jsonschema-absent spec checks

# everything merged (brain-core + router + voice + pc-in-tools + mine)
$ RAPHAEL_INSTANCE=computer-use /home/dami/raphael/brain/.venv/bin/python -m pytest -q \
    brain/tests brain/router/tests brain/voice/tests brain/vision/tests brain/tools
1 failed, 302 passed, 2 skipped in 43.06s

$ RAPHAEL_INSTANCE=computer-use /home/dami/raphael/brain/.venv/bin/python -m pytest -q tests/conformance
2 passed in 0.01s
```
- **The 1 failure is pre-existing on main, NOT this lane** (verified: fails
  with my changes `git stash`ed on the clean merged tree):
  `brain/tests/test_tools_registry.py::test_tool_specs_only_offers_conforming_schemas`
  — `assert 'shell' in specs and 'launch_url' in specs`.
  Root cause: `import brain.tools` registers the gui stubs WITH schema, then
  `discover()` imports `brain/tools/pc` whose `_register_all()` re-registers
  `launch_url` (and the other pc tools) **without `schema=`**, so
  `tool_specs()` stops offering them. Owners: brain-core (test/expectation) +
  pc-control (drops schema on re-registration — they keep model-facing specs
  in `pc.openai_tools()`); a schema-preserving re-register or passing
  `schema=s.to_schema()` fixes it. Reported via coord `test_result`.
- `brain/tests/test_agent_loop.py::test_persona_streamed_reply_and_multi_turn_history`
  failed once in the first combined run and passed on every rerun (isolation
  + combined) — timing flake, same class as the disclosed brain-suite flake.
- `tests/body_win/test_hotkeys_envelope.py` collection error (`No module named
  pip`, shared venv) — pre-existing, qa-security's area, unrelated.

## Handoff (integration points for the integrator / next waves)
- Tool registration: `import brain.tools.computer_use` registers both tools;
  brain-core's auto-discovery will pick the package up; `SPECS` exposed for
  validation (convention proposed in the brain-core request).
- Production wiring is lazy (`wiring.get_deps()`): gateway→hub/engine,
  chat/vision→`brain.router`, private→`brain.mode`, confirm→engine.confirmer
  (job rowid from the input-lock owner — fails closed when no job context).
- Reusable seams for Wave 3+: `brain/vision/service.capture_screen` (gated
  capture), `gateway.BodyGateway.{foreground_window,uia_tree,run_action}`,
  `runner.{validate_action, sensitive_reason, wrap_observation, parse_reply}`.
- Live-run checklist for the integrator: (1) pc-control ops answered; (2)
  app.py calls `wiring.bind_loop(...)` (or engine `_queue_loop` fallback
  verified); (3) fastpath see_screen intents landed; (4) journaling request
  merged before any real screenshot; (5) one real `see_screen` + one real
  short `computer_use` run under RAPHAEL_INSTANCE=computer-use.

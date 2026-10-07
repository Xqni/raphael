# computer-use — status

Updated: 2026-10-06 (Wave 2 complete — handoff below)

## Done (Wave 2, docs/lanes/computer-use.md all checked)

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
- Live end-to-end (`see_screen` on the real stack) awaits: the pc-control ops,
  router `vision()/chat()` seams, and the integrator's live runs (AGENT_RULES §5).

## Next
- STOP at wave end (AGENT_RULES §11). Waves 3–5 (watch mode, help-with-error /
  summarize-page, recovery + UAC safety, Simulation preview) start only when
  docs/WAVES.md `current_wave` says so.

## Test output (real runs only — never claim unrun tests)
```
$ RAPHAEL_INSTANCE=computer-use /home/dami/raphael/brain/.venv/bin/python -m pytest -q \
    brain/vision/tests brain/tools/computer_use/tests
69 passed, 2 skipped in 0.20s          # 2 skips = jsonschema-absent spec checks

$ RAPHAEL_INSTANCE=computer-use /home/dami/raphael/brain/.venv/bin/python -m pytest -q \
    brain/tests brain/router/tests brain/voice/tests brain/vision/tests \
    brain/tools/computer_use/tests tests/conformance
131 passed, 2 skipped in 20.08s
```
- Note: `tests/body_win/test_hotkeys_envelope.py` fails at COLLECTION with
  `No module named pip` (shared venv has no pip) — pre-existing, qa-security's
  area, untouched by this lane.
- Note: one earlier full-suite run showed an intermittent
  `brain/voice/tests::test_round_trip_tts_to_stt` failure; it passes in
  isolation and in the rerun above — flagged here for the voice lane, no
  computer-use code involved.

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

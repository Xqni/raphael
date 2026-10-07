# computer-use — status

Updated: 2026-10-07 (Wave 3: P0-BugF + SPEED done — handoff below)

## Wave 3 (2026-10-07)

**Bug F fixed (P0 gate bug) — root cause with live evidence:**
- `foreground_info` was NEVER the failure: `logs/actions.log` shows jobs 35/41
  probing successfully in 16 ms with real titles (`window.title [chars=26]`),
  while the refusing job 43 has **no fg record at all** — `logs/body.log`
  shows `Connection error: received 1012 (service restart)` between jobs
  42↔44, i.e. the body was **disconnected during a brain restart** when
  `see_screen` ran. `hub.get_body_session()` → None → `ActError` →
  my `capture_screen` collapsed it into `title=None` → gate spoke the
  **privacy** verdict for an **availability** failure. (The dossier's
  process-resolution hypothesis is disproven by evidence.)
- **Fix:** new `gate.unreachable(detail)` (E_UNREACHABLE, "I can't reach the
  Body right now (detail) — try again in a moment.") + `gate.err_hint()`
  (speech-safe: structured detail/code or type name, never raw `str(e)`).
  Applied in `service.capture_screen` AND `runner._observe` (fg probe AND
  screenshot probe). `{'window': None}`/missing title keeps the fail-closed
  "can't verify which window" message; blocklist refusal untouched.
- **Gate hole found & closed while fixing:** the blocklist check only ran on
  the *vision* path — a blocklisted window with a rich UIA tree would have
  sent its text to cloud chat (ARCHITECTURE §4: blocklisted foreground forces
  local models). `_observe` now checks `check_foreground(fg)` BEFORE accepting
  ANY observation (UIA or vision); refusal covers both paths.
- **Terminal-foreground tests (dossier ask):** `Ubuntu-26.04` reaches vision
  (service) and the full loop (runner) with exactly ONE fg probe; probe-failure
  and missing-window verdicts asserted distinctly; blocklist refuses before
  UIA/vision/chat.
- **SPEED (Rule 15):** zero added round trips — happy path stays
  1× `foreground_info` + 1× `screenshot` (asserted in tests), no retries/sleeps.
- Reported via coord: heartbeat (task start), `error` (root cause + evidence).

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
# Wave 3 (2026-10-07), one suite at a time (Rule 14), RAPHAEL_INSTANCE=computer-use:
lane:            brain/vision/tests + brain/tools/computer_use/tests
                 88 passed, 2 skipped in 1.68s     # skips = jsonschema-absent
brain:           brain/tests                -> 152 passed in 11.67s
conformance:     tests/conformance          -> 2 passed in 0.22s
(No orphan pytest processes after the runs — Rule 14 checked.)

# Wave 2 reference (kept for history):
# lane 84 passed/2 skipped; merged suite 302 passed/1 failed (pre-existing on
# then-base, resolved by later merges per handler verification) + conformance 2.
```
- Historical note: the Wave-2-era `test_tool_specs_only_offers_conforming_schemas`
  failure and the persona-streamed-reply flake no longer reproduce — `brain/tests`
  ran 152 passed / 0 failed today (handler verified the merged tree too).
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

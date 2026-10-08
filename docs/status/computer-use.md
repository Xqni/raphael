# computer-use — status

Updated: 2026-10-07 (Wave 5: Analysis context + 2 brain-core requests closed — handoff below)

## Wave 5 (2026-10-07)

1. **brain-core request `test-hardening-relative-import` → DONE** (already
   fixed on main by integrator `c60c23c`; re-verified with the exact CI step:
   `pytest -q brain --collect-only` = 771 collected, 0 errors at the time).
2. **brain-core request `vision-loader-authority-guard` → IMPLEMENTED + DONE**
   (`14f49a9`): `AUTHORITY_KEYS` = safety/privacy/providers/profiles/profile/
   **vision** (vision+profile added: they ARE the §7 gate surface) stripped
   from config.d fragments, `{file, keys}` recorded via
   `authority_violations()`, loud print, never raises; fragment dir is now
   path-relative for hermetic tests; 3 tests (hostile fragment keeps base
   values + records + prints / clean fragment merges / real tree violation-
   free).
3. **Analysis-mode context gathering (lane checkbox):**
   - New **`gather_context`** tool (`brain/vision/context.py` + registration
     in `brain/tools/computer_use/`): foreground + open-window list + recent
     window history + optional gated screen description, composed as one
     redacted, bounded (3000 chars), untrusted-wrapped-by-the-loop payload.
   - Window history: in-process ring (32 stored / 12 emitted, consecutive
     dedup, timestamps) fed by every production `BodyGateway.foreground_window`
     probe — memory only, never disk/logs.
   - **Redaction/privacy discipline:** every section passes `gate.redact`;
     blocklist entries filtered from windows AND history; blocked/unknown
     foreground announced with GENERIC wording (app names never reach cloud
     payloads — caught a leak where the Screen refusal reason would have
     echoed "KeePass" into the model prompt); Private Mode = zero probes;
     probe failures = honest E_UNREACHABLE text; optional screen pass runs
     the full §7 gate chain (blocklist → profile → debug_capture → image
     size → vision).
   - No new frames/contracts needed (read-only §7 actions + self-registered
     tool) → no integrator request required.
4. **Known non-mine failure:** `tests/regression/test_instance_isolation.py::
   test_interfaces_instance_table_is_collision_free` fails on current main
   (table now has the APPROVED `shadow` row = 12 instances; test asserts 11).
   Tracked by `brain-core__to__qa-security__shadow-row-count.md`.

## Wave 4 (2026-10-07)

**Observation hardening (lane checkbox, all four sub-items):**
- **UIA crash recovery:** `uia_tree` raising → gated-vision fallback (pixel
  path still passes fg + debug-capture + downscale gates); UIA crash +
  debug-capture → refusal before any pixels; UIA crash + body gone → honest
  E_UNREACHABLE ("no body session connected"), chat never called.
- **Blocklist bypass suite (privacy audit) — one real bypass found & fixed:**
  the gateway returned ONLY the window title, so an untitled KeePass dialog
  titled "Enter Master Key" (process `KeePass.exe`) would have matched
  nothing. `foreground_window()` now returns a normalized
  `"title | process"` composite; a real window with ZERO identity → None →
  fail-closed. Audited: casefold substring, literal (non-regex) entries,
  empty entries never match-everything.
- **Foreground-probe failure matrix** (runner + service level): timeout /
  no-body-session / unsupported op / malformed result → E_UNREACHABLE
  (availability wording, code or type hint); vanished window (`{'window':
  None}` / zero identity) → E_NO_FOREGROUND (privacy wording). Both refuse
  before uia/screenshot/chat.
- **Screenshot redaction re-verify:** vision answers, UIA tree text, and
  action feedback all pass `gate.redact` before reaching a model — asserted
  for all six configured kinds (api_key/token/password/card/email/phone);
  window content itself (non-secret) stays intact.
- **qa-security vision-gate request flipped DONE:** items 1-3 landed in
  Wave 2 (their tripwires already strict-green); item 4 implemented NOW —
  `gate.check_debug_capture()` (§7(4) enforced in code: cloud send denied
  while debug_capture is on; local vision unaffected), wired into
  `see_screen`, `capture_screen` and the runner pixel path.
- Rule 15: zero new round trips (happy path still 1 fg probe + 1 capture,
  asserted); live stack untouched (mock-only, no servers spawned).

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
# Wave 5 (2026-10-07), one suite at a time (Rule 14), RAPHAEL_INSTANCE=computer-use:
lane:            brain/vision/tests + brain/tools/computer_use/tests
                 120 passed, 3 skipped in 1.83s    # skips = jsonschema-absent (3 specs)
brain:           brain/tests                       -> 184 passed in 14.73s
regression:      tests/regression                  -> 47 passed, 4 xfailed,
                 1 FAILED (pre-existing, non-mine: instance-table now has the
                 APPROVED shadow row = 12; test asserts 11 — tracked by
                 brain-core__to__qa-security__shadow-row-count.md)
CI collect:      pytest -q brain --collect-only    -> 785 tests, 0 errors
(No orphan pytest processes — Rule 14 verified via ps/grep.)

# Wave 4 reference: lane 107/2skipped, regression 47+4xf, brain 164 (f5e5079).
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

# pc-control — lane task list (owner: pc-control lane)

Read: docs/AGENT_RULES.md -> docs/WAVES.md -> this file. Status log: docs/status/pc-control.md. Requests to you: `ls docs/requests/*__to__pc-control__*.md`.

Merge-order position: see docs/WAVES.md

## Wave 2 tasks (docs/WAVES.md (current_wave: 2))
- [x] brain/tools/pc/ namespace + self-registered tools (open_app, launch_url, volume, media, window, clipboard, notify) per INTERFACES §b.
      → shipped all 17 pc tools (one file per group: launch/system/window/automation/powershell), strict JSON-schema, needs_lock parity with body actions, confirm categories (`powershell` = risky/system_settings_change). Live-Brain auto-discovery is brain-core's half → docs/requests/pc-control__to__brain-core__tool-discovery-and-llm-tools.md.
- [x] Body act_req coverage for those tools (body/win minus audio_*), incl. queue/busy semantics (E_LOCK_BUSY).
      → body/win/actions.py dispatcher: all 17 actions of PROTOCOL §7 (+ list_windows/foreground_info/list_running_apps requested in docs/requests/pc-control__to__integrator__protocol-act-req-enum.md), `act_res{ok:false, error:"E_LOCK_BUSY", queued:true}` fail-fast, per-action timeout (E_TIMEOUT, atomic input exempt), §7 action log (redacted, structural results).
- [x] Hotkeys (pause/private/kill) contract-tested WITHOUT registering real hotkeys (instance rule).
      → pure `build_bindings()` + `register_hotkeys()` exercised against a stub `keyboard` module in sys.modules; envelopes checked against the PROTOCOL §3 control enum parsed from the doc (body/win/tests/test_pc_hotkeys.py).
- [x] Lock names derive from RAPHAEL_INSTANCE (INTERFACES §d) — main defaults unchanged.
      → body/win/instance.py: body lock / WS port / token candidates / data dir / action log / supervisor mutex; `main` (unset) = 8765, `%TMP%\raphael_body.lock`, `~/.raphael/token` byte-for-byte. Unknown instance without RAPHAEL_PORT raises (never defaults a port). Covered by body/win/tests/test_pc_instance.py; brain-side token half + supervisor half are open requests.
- [x] Mock/unit tests only; never inject real input outside mocks.
      → 78 body tests + 10 spec tests, all against FakeWin; e2e_control.py mock mode (default) uses FakeWS+FakeWin; `--live` refuses to run unless RAPHAEL_INSTANCE is set and ≠ main.

## Wave 3 (start only when WAVES.md says so — current_wave: 3)

Wave 2 is MERGED; live gate was 3/5 — evidence + bug dossiers: `docs/BUGS-WAVE2.md`. SPEED MANDATE: cloud is paid now — near-instant responses, fast model defaults (AGENT_RULES Rule 15, WAVES.md constraints).

- [x] [P0-BugB] Body half of BUGS-WAVE2 Bug B: `open_app` for "open YouTube and search lo-fi" opens a BLANK cmd window then fails with NO `act_res`. Make Windows launch robust (`Start-Process`/`os.startfile`, no console flash), always return an act_res (success or precise error), cover with a test.
      → (1) console flash: `winlayer.hidden_popen_kwargs()` (CREATE_NO_WINDOW + hidden STARTUPINFO) on EVERY PowerShell child spawn + `.bat/.cmd/.ps1/.vbs/.wsf` excluded from open_app launch candidates (explicit `open_path` still honors the default handler); UWP scan timeout 30→15 s. (2) act_res: ws_client act_req branch wraps dispatch — a dispatcher crash now answers `E_INTERNAL` instead of killing the receive loop, and prints a greppable `[body-win] act_res: <action> job=… ok=… ms=…` line (the gate grepped body.log and found none). (3) precise errors: not-found reports stage counts ("tried N PATH, N Start Menu, N App Paths, N UWP candidates; console scripts excluded"). Tests: +7 (act_res-always, evidence line, bat-skip, exe-over-bat, stage counts, hidden kwargs, UWP fail-fast).
- [x] [SPEED] Tool acts fire immediately on request (Rule 15).
      → dispatch has no artificial waits (0.1 s lock fast-fail only); slowest launch stage (PowerShell UWP scan) now fails at 15 s; router half (fastpath open+search mapping) landed with brain-core.
- [x] Flip follow-up: all 17 pc tools register `schema=` (zero-arg three included after brain-core's empty-properties relaxation merged; request `allow-empty-properties-schema` → DONE, parity test updated).

## Wave 4 (start only when WAVES.md says so — current_wave: 4)

Wave 3 is MERGED + **GATE PASSED** (tag `wave-3-gate`, all six criteria live, acoustic voice included). Wave-4 theme per WAVES.md: hardening, resilience tests, audit fixes, crash recovery, evolution infrastructure. Rule 15 speed mandate still binds.

- [x] Act-layer hardening: timeout/kill recovery per tool, partial-failure matrix (act_res always truthful under crash), Windows E2E failure injection (each pc tool: happy/missing-denied/locked).
      → `body/win/failure_cases.py` = single source (INVALID_ARGS + CRASH_CASES for all 17 tools), shared by unit + e2e. Dispatcher now audit-logs `E_CANCELLED` on kill/disconnect mid-action (outer finally still releases the lock — PROTOCOL §5). Matrix: every tool × {E_BAD_MSG with zero OS calls, E_LOCK_BUSY side-effect-free, E_INTERNAL truthful + recovery dispatch} + timeout-release + cancel-release tests → `test_pc_failure_matrix.py` 54 passed. E2E injection phase: 123 checks PASS (0 fail). FakeWin gained a `delays` knob for timeout drills.

## Wave 5 (start only when WAVES.md says so — current_wave: 5)

Wave 4 is MERGED + **GATE PASSED** (tag `wave-4-gate`, 10/10 lanes, mock 308 green). Wave-5 theme per WAVES.md: Raphael features — Answer/Notice/Report formats, Analysis, Simulation, parallel-minds visuals, persona tiers. Rule 15 speed mandate binds; shared-contract changes go through integrator requests. Carried items are noted in WAVES.md gate record (shadow row; C1+C2 residual).

- [x] Report-format delivery acts (save/share report outputs) + any GUI affordances the Answer/Report formats need; failure-matrix discipline from wave 4 applies to every new act.
      → new `report{op: save|list}` act (`body/win/act_report.py`): FIXED `Documents\Raphael\reports` dir (model never chooses a path), slugified timestamped filenames (traversal-proof), atomic `.part`→replace writes, format md|txt|json (json validated), list newest-first cap 100; share/open composes from EXISTING acts (`open_path`/`clipboard`/`notify`). §7 enum change requested FIRST per wave-open rule (`pc-control__to__integrator__protocol-report-act.md`, tracked in `PENDING_PROTO_ADDITIONS=('report',)`, conformance test now checks ANY pc request file covers each pending name). Tool spec `brain/tools/pc/report.py` (18 tools, lock:false, no confirm). Report `body` logged length-only (content redaction extended). Wave-4 matrix auto-covers the new act: invalid/locked/crash+recovery params added to failure_cases (+3), dedicated `test_pc_report.py` (8), e2e injection now 130 checks PASS.

## Wave 5H — audit hardening sprint (inside wave 5; gate `wave-5h-gate`)

- [x] Read `docs/audit-tasks/pc-control.md` → your IDs: **SEC-9, F-3** — VERIFY-FIRST (verbatim file:line, then CONFIRMED / NOT-APPLICABLE / ALREADY-DONE), QA-4: link a green CI run with your wave_done. Source register + dedupe: `docs/AUDIT-2026-10-07.md`. Rules: stack down (spawn only for your test), one suite at a time, heavy suites in cloud (`gh workflow run tests-heavy.yml`), Rule 15 speed, cost not a factor.
      → **SEC-9: CONFIRMED** — `body/win/capture.py:25-26` `_ensure_pkg('mss', pin='10.2.0')` / `_ensure_pkg('Pillow', 'PIL', '12.3.0')` (module-level!), `body/win/clipboard.py:19` `_ensure_pkg('pywin32', 'win32api', '312')`, `body/win/system.py:21` `subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--quiet', name])`, `body/win/automation.py:28` + `body/win/winlayer.py:63` same check_call, `body/win/ws_client.py:51` `'websockets==16.1.1'` pip fallback, `body/win/hotkeys.py:134` `'PyYAML==6.0.3'` pip fallback. FIXED: `body/win/depfail.py` (`require()` = find_spec only, fail-loud) + `body/win/requirements.txt` hash-pinned win_amd64 cp310-314 (`--require-hashes`, validated `pip --dry-run` rc=0 on 310/312/313), AST test `test_sec9_dep_hygiene` (5 tests: no pip/network constructs, req complete, fail-loud), voice coordination → `pc-control__to__voice__sec9-audio-pip-helpers.md` (audio_* is voice-owned; their pins already in requirements).
      → **F-3: CONFIRMED** — pre-fix `body/win/act_system.py:66` `await asyncio.to_thread(backend.set_volume, args['level'])` (set WITHOUT reading previous → no inverse possible) and `body/win/actions.py:276` `path = instance.action_log_path()` (append-only audit, zero undo state — grep for `undo|previous_level` found none). FIXED: `body/win/journal.py` (append-only JSONL schema + truthfulness: inverse-before-mutate, record-only-on-success, undo-applies-first) with inverse ops for volume/brightness/window (`get_volume`/`get_brightness`/`window_placement`/`set_placement` backend reads added), new `activity{op: list|undo}` act (`PENDING=('activity',)` + §7 request), 19th tool, co-share requests → integrator (§7) / brain-core (`GET /activity`+`POST /activity/undo` relay) / orb (viewer schema); 12 journal tests + wave-4 matrix auto-covers `activity` + e2e rows. Confirmations untouched (AGENT_RULES §8: journaling adds no bypass).
      → **AUD-05 foreground push (dispatch [32]): DONE** — `body/win/foreground.py` (connect snapshot + SetWinEventHook focus events, 1s poll fallback, 30s resync, dedupe/retry, lock-free proven <100ms) + ws_client wiring + PROTOCOL §3/§4 `foreground` frame (grant) + brain-core consumer request. Bug F verified NOT body-side (BUGS-WAVE2:116-122 — WS-disconnect masked as E_NO_FOREGROUND, computer-use fix in flight; fg_info ran 16ms on jobs 35/41). Status detail: docs/status/pc-control.md.
      → Raw 5-item intake note: PS-script-manifest + open_app-hijack have NO IDs in `docs/AUDIT-2026-10-07.md`, and ARCH-4 ("infra + all lanes") is excluded by this packet's "Scope = ONLY the IDs below" — flagged, not worked.

## Later waves
- Per docs/WAVES.md — do not start early (AGENT_RULES §11). Wave 6 is **NOT NOW** (local-model cutover after the RAM upgrade).

## Cross-lane requests addressed to pc-control
- (none open — checked at session start and per task)

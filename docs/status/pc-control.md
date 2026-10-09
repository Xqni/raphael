# pc-control — status

Updated: 2026-10-06 (Wave 2 complete — handoff below)

## Done (Wave 2, all committed on agent/pc-control)

1. **Instance isolation (task 0 / lane task 4).** `body/win/instance.py`
   derives body lock, WS port, token candidates, data dir, action-log path and
   supervisor mutex from `RAPHAEL_INSTANCE` (INTERFACES §d table). Unset/`main`
   = today's exact values (8765, `%TMP%\raphael_body.lock`,
   `%APPDATA%\Raphael\token` → `~/.raphael/token`). Unknown instance without
   `RAPHAEL_PORT` raises — never defaults a port (AGENT_RULES §5).
   `main.py` (lock) and `ws_client.py` (URL + token) consume it.
   Brain-side token derivation + supervisor mutex/env → 2 open requests.
2. **Full PROTOCOL §7 act_req coverage (task 1).** `body/win/actions.py`
   dispatcher + one module per group (`act_launch/act_powershell/act_capture/
   act_uia/act_input/act_window/act_system`) = 17 actions: launch_url,
   search_youtube, open_app (PATH → Start Menu → App Paths → UWP staged
   resolution), open_path (local-only, no UNC/shell:), powershell (fixed
   script registry, env-var args — no injection), screenshot, uia
   find/click/type/read/tree (structured selectors), input (atomic
   chords/text/mouse units, modifier-release guarantees, mouse failsafe),
   window list/focus/min/max/restore/snap, clipboard, media, volume,
   brightness, notify, plus list_windows / foreground_info /
   list_running_apps (§7 enum additions requested from the integrator).
   Semantics: allow-list → strict validation (no value echo) → input-lock
   (`E_LOCK_BUSY` + `queued:true`, lock acquired even if the sender forgets,
   released in `finally`) → timeout `E_TIMEOUT` (atomic input exempt so a
   chord is never cut in half) → redacted JSONL action log
   (`logs/actions[_<instance>].log`: args summarized w/ secret keys + content
   text reduced to lengths, results structural only, 5 MB rotation).
   All OS calls sit behind `body/win/winlayer.py` (lazy Windows imports,
   ctypes keyboard/mouse/window/process, pywinauto UIA, NullBackend off-Windows)
   with `body/win/fakewin.py` as the mock.
3. **LLM-facing tools (task 2).** `brain/tools/pc/` — one file per group
   (launch/system/window/automation/powershell) + `_spec.py`; 17 ToolSpecs
   with strict JSON schemas (typed + described properties, required ⊆ props,
   `additionalProperties:false`, provider-portable keywords only), loud
   import-time validation, self-registration into `brain.tools` with
   `category='gui'`, `needs_lock` parity with the body action (asserted),
   and confirm categories (`powershell` risky → `system_settings_change`,
   everything else None). Exports `openai_tools()` + `prompt_block()` for the
   router. Live-Brain discovery/LLM wiring is brain-core's half → open request.
4. **Tests + e2e (task 3).** `body/win/tests/` (78 tests) and
   `brain/tools/pc/tests/` (10 tests), all mocked — no real input, no
   sockets, no hotkey registration anywhere. `body/win/e2e_control.py`
   extended: default **mock mode** drives the whole §7 matrix through
   `ws_client.handle_message` (FakeWS+FakeWin, action-log checks, exit 0/1);
   `--live` keeps the original control-frame flow but **refuses to run**
   unless `RAPHAEL_INSTANCE` is set and ≠ `main`.
5. **Hotkeys (lane task 3).** `hotkeys.py` refactored: pure
   `build_bindings(config)` + `register_hotkeys()` as the only `keyboard`
   touchpoint; contract tests run registration against a stub `keyboard`
   module and check every frame against the PROTOCOL §3 control enum parsed
   from the doc.
6. **Cross-lane requests (AGENT_RULES §2).** 4 written:
   - `pc-control__to__integrator__protocol-act-req-enum.md` (§7 additions)
   - `pc-control__to__integrator__instance-token-path.md` (auth token path)
   - `pc-control__to__brain-core__tool-discovery-and-llm-tools.md`
     (auto-discovery, feed tool specs to the model, risky/confirm enforcement)
   - `pc-control__to__infra__instance-env-supervisor.md` (mutex + env)

## In progress
- — (Wave 2 lane tasks complete)

## Blocked
- Live-Brain use of `brain/tools/pc` awaits the brain-core auto-discovery
  request (tools are registered + tested; the Brain must import the package).

## Next
- Per AGENT_RULES §11: handoff written, lane STOPS here. Waves 3-5
  (browser/CDP, recycle-bin+activity viewer, dry-run) start only when
  `docs/WAVES.md current_wave` advances.

## Test output (real runs, 2026-10-06, on this worktree)

```
$ tests/.venv/bin/python -m pytest -q tests
10 passed in 0.33s                      # qa-security's root suite — unchanged baseline

$ tests/.venv/bin/python -m pytest -q body/win/tests brain/tools/pc/tests
88 passed in 0.67s                      # 78 body + 10 tool-spec tests

$ /home/<wsl-user>/raphael/brain/.venv/bin/python -m pytest -q brain
70 passed, 3 warnings in 18.98s         # baseline 60 + 10 new pc spec tests

$ python3 body/win/e2e_control.py
... 54 PASS lines, 0 FAIL ...
E2E-MOCK: PASS (0 checks failed)
exit=0

$ cd body/win && python3 -c "import ws_client, actions; print(len(actions.action_names()), 'actions')"
17 actions                              # script-mode (supervisor) import path
```

Honest note: ONE earlier run of the brain suite reported `1 failed, 69 passed`
before any name could be captured (the `.pytest_cache/lastfailed` was cleared
by the next green run). The identical sequence was then repeated 9 times — all
`70 passed`, `lastfailed = {}`. The pc-control tests (88) were green in every
single run; the transient sits in the pre-existing brain suite (timing-class),
not in this lane's tests. Re-run `pytest brain` if it reappears and report the
name to the owning lane.


## Handoff (for the integrator / next pc-control session)

- **Ownership respected:** only `body/win/**` (except `audio_*`),
  `brain/tools/pc/**`, `docs/lanes|status/pc-control.md`, `docs/requests/*`
  were touched. `docs/PROTOCOL.md`, `brain/auth.py`, `brain/tools/__init__.py`,
  `supervisor/` are NOT edited — changes proposed via the 4 request files.
- **What the next session needs to know:**
  - The act_req action registry is `body/win/actions.py::ACTIONS`;
    conformance test parses §7 from the doc + `PENDING_PROTO_ADDITIONS`.
    When the integrator accepts the enum request, delete the tuple (the test
    keeps passing either way).
  - `body/win/fakewin.py` ships in the body (test support, documented) —
    never bind it outside tests/e2e; `winlayer.get_backend()` only auto-selects
    the real backend on `os.name == 'nt'`.
  - Live Windows verification NOT run here (Linux worktree, AGENT_RULES §5):
    `e2e_control.py --live` (with `RAPHAEL_INSTANCE`), `e2e_phase3.py` and a
    real screenshot/clipboard/volume pass still need an integrator go on the
    Windows host — expected to pass unchanged: legacy response shapes
    (`result.b64/bytes`, clipboard string result, exact `E_LOCK_BUSY`) were
    kept for them.
  - Test invocations that work on this machine: `tests/.venv` for
    `tests` + `body/win/tests` + `brain/tools/pc/tests`; `brain/.venv` for
    `brain/**` (no PyYAML in tests/.venv).

---

# Wave 3 log

## 2026-10-07 — P0-BugB (body half) + approved schema flip — DONE

**Bug B body half** (`docs/BUGS-WAVE2.md` — blank cmd window + no act_res):
1. **No console flash:** `winlayer.hidden_popen_kwargs()` = CREATE_NO_WINDOW +
   hidden STARTUPINFO on every PowerShell child; open_app's launch candidates
   exclude console scripts (`.bat/.cmd/.ps1/.vbs/.wsf` — explicit `open_path`
   unaffected); UWP scan timeout 30→15 s (Rule 15 fail-fast).
2. **act_res always surfaced:** ws_client's act_req branch wraps dispatch —
   any crash answers `act_res{ok:false, E_INTERNAL}` instead of killing the
   receive loop, and prints `[body-win] act_res: <action> job=… ok=… ms=…`
   (the exact evidence the gate grepped for and didn't find).
3. **Precise errors:** not-found now reports stage counts ("tried N PATH,
   N Start Menu, N App Paths, N UWP candidates; console scripts excluded").

**Approved flip** (allow-empty-properties → merged): all 17 pc tools now pass
`schema=s.schema()` to the registry — `tool_specs()` offers every pc tool
incl. `list_windows`/`foreground_info`/`list_running_apps`; request file →
DONE with implementation note.

**Tests (Rule 14: smallest target first, one suite at a time, all real):**
```
$ pytest body/win/tests/test_pc_ws_actreq.py            9 passed   (7+2 new)
$ pytest body/win/tests/test_pc_actions_launch.py      11 passed   (8+3 new)
$ pytest body/win/tests/test_pc_actions_powershell.py  10 passed   (8+2 new)
$ pytest body/win/tests                                85 passed
$ pytest brain/tools/pc/tests                          11 passed
$ pytest tests                                        187 passed, 9 xfailed, 2 xpassed
$ python3 body/win/e2e_control.py              E2E-MOCK: PASS (0 failed)
$ pytest brain                                    431 passed, 4 skipped
```

**Blocked/next:** waiting for merge (pc-control is next after brain-core),
then the coord ping for the next task. The `--live` Windows re-verification of
Bug B (real "open YouTube and search lo-fi") stays the integrator's gate step.

## 2026-10-07 — Wave 4: act-layer hardening — DONE

**What shipped:**
1. `body/win/failure_cases.py` — per-tool failure tables (INVALID_ARGS,
   CRASH_CASES) shared by unit tests and the E2E harness (one source of
   truth for the partial-failure matrix).
2. Dispatcher: `E_CANCELLED` audit line when a kill/disconnect interrupts an
   in-flight action (PROTOCOL §5) — lock release already in `finally`,
   now proven by test; act_res truthfulness holds under cancel too.
3. `test_pc_failure_matrix.py` — for all 17 tools: invalid args → E_BAD_MSG
   with **zero OS calls**; locked → exact E_LOCK_BUSY + queued, side-effect
   free; backend crash → E_INTERNAL + failing call observable + lock
   released + **recovery dispatch succeeds**; plus timeout-release and
   cancel-release+audit. **54 passed.**
4. `e2e_control.py` injection phase — same three matrices through the real
   `handle_message` path + timeout drill. **123 checks PASS, 0 failures.**
5. FakeWin: `delays` knob (timeout injection).

**Tests (real, one suite at a time per Rule 14):**
```
$ pytest body/win/tests/test_pc_failure_matrix.py    54 passed
$ pytest body/win/tests                             139 passed
$ pytest tests                                     197 passed, 9 xfailed
$ python3 body/win/e2e_control.py          123 PASS / 0 FAIL
$ pytest brain                       615 passed, 2 failed (see below)
```
Brain-suite failures are `brain/memory/tests/{test_tools_files,
test_tools_shell}` (tools-memory lane): they PASS in isolation, and a
throwaway worktree of clean `origin/main` (1485836) fails the same 2 PLUS
`brain/vision` (3 failed there) → pre-existing on main, NOT pc-control.
Worktree removed after the check.

## 2026-10-07 — Wave 5: Report-format delivery acts — DONE

**What shipped:**
1. Integrator request FIRST (wave-open rule): `pc-control__to__integrator__
   protocol-report-act.md` — adds `report{op}` to the §7 allow-list; the act
   is implemented behind `PENDING_PROTO_ADDITIONS = ('report',)`.
2. `body/win/act_report.py` — `report{op: save|list}`:
   - save: FIXED `Documents\Raphael\reports` dir (backend-provided; the model
     can NEVER choose a path), slugified title + timestamp (traversal-proof),
     dedupe suffix, atomic `.part`→replace (crash-safe), format md|txt|json
     (json body validated pre-write), truthful result {path,name,bytes,lines};
   - list: newest-first, cap 100, ignores debris (.part/other exts);
   - content redaction: report `body` logged length-only (`_CONTENT_KEYS`).
3. `brain/tools/pc/report.py` — 18th pc tool (lock:false, no confirm),
   shares/opening composed via existing open_path/clipboard/notify.
4. Wave-4 failure-matrix discipline applied: `failure_cases` tables grew the
   report row → the parametrized matrix (invalid/locked/crash+recovery)
   covers it AUTOMATICALLY; plus dedicated `test_pc_report.py` (slug/atomic/
   json/dedupe/list-order/cap/log-redaction).
5. Conformance test generalized: every pending §7 name must be covered by
   SOME `pc-control__to__*.md` request (was hardcoded to the 2026-10-06 file).

**Tests (real, sequential per Rule 14):**
```
$ pytest body/win/tests/test_pc_report.py                8 passed
$ pytest body/win/tests/test_pc_failure_matrix.py \
         body/win/tests/test_pc_dispatch.py             70 passed
$ pytest body/win/tests                                150 passed
$ pytest brain/tools/pc/tests                           11 passed
$ python3 body/win/e2e_control.py              130 PASS / 0 FAIL
$ pytest tests                        203 passed, 1 failed (pre-existing)
$ pytest brain                                768 passed, 3 skipped
```
The root failure is `tests/regression/test_instance_isolation.py::
test_interfaces_instance_table_is_collision_free` — asserts the INTERFACES
instance table has EXACTLY 11 rows; the table now has 12 (the APPROVED
shadow-instance row, port 8911). Verified identical failure on a clean
`origin/main` worktree (3996d31) → qa/integrator drift, NOT pc-control;
worktree removed after the check. Reported to the bus with the exact cause.

---

# Wave 5H log (audit packet: SEC-9 + F-3)

## 2026-10-07 — SEC-9: CONFIRMED + FIXED

**Verification (verbatim pre-fix quotes):**
- `body/win/capture.py:25-26`: `_ensure_pkg('mss', pin='10.2.0')` /
  `_ensure_pkg('Pillow', 'PIL', '12.3.0')` — module-level runtime pip on import.
- `body/win/clipboard.py:19`: `_ensure_pkg('pywin32', 'win32api', '312')`.
- `body/win/system.py:21`: `subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--quiet', name])`.
- `body/win/automation.py:28` and `body/win/winlayer.py:63`: `subprocess.check_call([sys.executable, '-m', 'pip', 'install', ...])`.
- `body/win/ws_client.py:51`: `subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--quiet', 'websockets==16.1.1'])`.
- `body/win/hotkeys.py:134`: `subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--quiet', 'PyYAML==6.0.3'])`.
- `brain/tools/pc/**`: none (clean).

**Fix:** `body/win/depfail.py` (find_spec-only probe, fail-loud RuntimeError
pointing at the env — no subprocess/network in the module, asserted by test);
all 7 call sites refactored; `body/win/requirements.txt` = `--require-hashes`
win_amd64 CPython 3.10-314 (11 pins incl. voice's sounddevice/numpy, sha256 of
every supported wheel). **Validation (real):** `pip install --dry-run
--require-hashes -r requirements.txt --platform win_amd64 --python-version
{310,312,313} …` → rc=0 each (hashes verified against live wheels); cp314
documented (numpy 2.2.6 has no cp314 wheel — flagged to voice). Voice
coordination: `docs/requests/pc-control__to__voice__sec9-audio-pip-helpers.md`.

## 2026-10-07 — F-3: CONFIRMED + FIXED (co-share with orb)

**Verification (verbatim pre-fix quotes):**
- `body/win/act_system.py:66`: `await asyncio.to_thread(backend.set_volume, args['level'])`
  — wrote state without ever reading it → no inverse op possible.
- `body/win/actions.py:276`: `path = instance.action_log_path()` — append-only
  audit log; repo-wide grep for `undo|previous_level|restore_state` in
  body/win found ZERO undo machinery (only the read-only
  `recycle_bin_status` script and window op name `restore`).

**Fix:** `body/win/journal.py` — append-only JSONL at
`instance.activity_log_path()` (`logs/activity[_<instance>].jsonl`,
`RAPHAEL_ACTIVITY_LOG` override), schema {seq, ts, kind, act, job, summary,
inverse, undone[, undo_seq]}; truthfulness guarantees (inverse captured
before mutation; record only after success; undo applies inverse first,
marks undone only on success; journal I/O never fails the act).
Inverse ops wired: **volume/brightness** (new `get_volume`/`get_brightness`
backend reads; set now returns bool → truthful E_INTERNAL on failure) and
**window** (new `window_placement`/`set_placement`; snap/min/max/restore
journaled, focus deliberately not — foreground races). New act
`activity{op: list|undo}` + 19th tool (`brain/tools/pc/activity.py`);
`PENDING_PROTO_ADDITIONS=('activity',)`; requests: integrator (§7),
brain-core (`GET /activity`, `POST /activity/undo` relay for orb/CLI),
orb (viewer schema + render rules). `recycle_move` reserved in the schema
(no producer act exists — would need §7 + confirm `delete_files`).
Confirmations stay enforced in code: journaling adds no bypass; tools keep
their risky/confirm metadata (AGENT_RULES §8).

**Tests (real, one suite at a time):**
```
$ pytest body/win/tests/test_sec9_dep_hygiene.py            5 passed
$ pytest body/win/tests/test_pc_journal.py                 12 passed
$ pytest body/win/tests                                  170 passed
$ pytest brain/tools/pc/tests                             11 passed
$ python3 body/win/e2e_control.py              136 PASS / 0 FAIL
$ pytest tests                           214 passed, 7 xfailed
$ pytest brain                                902 passed, 5 skipped
```
Note: the previously-reported root `test_instance_isolation` failure is
GREEN again on this branch (fixed upstream). No repo `logs/` created by any
run (both logs redirected to tmp).

## 2026-10-08 — AUD-05 (my half): foreground push producer — DONE

**Verify-first (dispatch [32] requirements):**
- **Bug F state (checked first):** `docs/BUGS-WAVE2.md:116-122` — *"ROOT CAUSE
  CORRECTED (computer-use …): `capture_screen` masked a body-WS disconnect …
  Job 43 … has NO `foreground_info` record … the tool never ran"*
  → body's `foreground_info` was NEVER broken (jobs 35/41 succeeded in
  **16 ms** with real window titles); the fix is computer-use's (in flight).
  So the query is proven fast + healthy — safe to use as the push source.
- **Lock-free proof:** `body/win/act_window.py` registers
  `register_action('foreground_info', …, needs_lock=False, …)` and the
  dispatch only takes the input lock under `if lock or spec.needs_lock`
  (`body/win/actions.py:396-397`) → push path never acquires it (test
  `test_push_never_touches_the_input_lock` monkeypatches
  `acquire_input_lock` to RAISE — push still works).

**Shipped:**
1. `body/win/foreground.py` — connect snapshot + focus-change push:
   - primary: Win32 `SetWinEventHook(EVENT_SYSTEM_FOREGROUND)` on a daemon
     message-pump thread (event-driven detection, ms-level);
   - fallback (non-Windows / hook failure): 1 s poll; **30 s force-resync**
     in both modes (ring ts refresh even when idle);
   - dedupe (hwnd+title+process), retry-on-send-failure, never raises into
     the client loop; local change→frame→send measured **< 100 ms**
     (`test_push_latency_under_100ms`).
2. `body/win/ws_client.py` — `set_sender(_send_frame)` +
   `fg.start(loop)` in `start_client` (logs `hook=… poll=…`) + connect
   snapshot right after `auth_ok` in `client_once`.
3. **PROTOCOL §3 granted edit landed:** new `foreground` frame row
   (`window{hwnd,title,process,pid}|null`, `ts`, role=body) with the
   brain-core consumer contract (`record_foreground("title | process")` —
   the identity shape `brain/tools/computer_use/gateway.py:134` already
   produces) + §4 capability row `send foreground push … **✓ only**`.
4. Consumer request → brain-core: `pc-control__to__brain-core__
   foreground-frame-consumer.md` (ws.py handler: role=body only, null
   window = unverifiable = don't record = gate stays fail-closed).

**Tests (real, sequential):**
```
$ pytest body/win/tests/test_pc_foreground.py             9 passed
$ pytest body/win/tests                                 183 passed
$ pytest brain/tools/pc/tests                            11 passed
$ python3 body/win/e2e_control.py              142 PASS / 0 FAIL (fg:connect/dedupe/change/lock-free)
$ pytest tests                     213 passed, 1 failed (qa's uia-confirm test = their P0 in flight)
$ pytest brain                               1046 passed, 6 skipped
```

## 2026-10-08 — F-3 orb co-share: journal-schema agreement + my half — DONE

**Agreement** written into `docs/requests/orb__to__pc-control__act-journal-schema.md`
(Status DONE): entry shape ACCEPTED as orb proposed; 3 corrections —
(1) `window` **snap** is reversible (rect captured pre-change), (2) `media`
toggles accepted per their default rule (play_pause/mute only), clipboard
"partial" deferred to false-for-now, (3) `undo` wire payload =
`activity{op:undo, seq}` (universal executor; placements can't replay as raw
`window{op}`); transport = REST accepted (matches my brain-core endpoint
request, updated to `op:"log"` + id-based undo + error-code map).

**Implemented (my half):**
- `actions.py::next_entry_id()` — stable `a_<ms>_<hex>` id generated ONCE
  per dispatch, stored in BOTH the §7 action log (`id` field) and the F-3
  journal record → restart-stable join key for the viewer.
- `journal.py` — records gain `id` + `undo{action,args}` payload; undo
  markers now carry `ok:true|false` → `undo_ok` (in-memory + rehydrated),
  failed undo appends marker AND flips `undo_ok:false` while `undone` stays
  false (button stays offered, honestly); `resolve_id()`; **`log_entries()`**
  = the joined per-act orb view (all acts, exact 12-field shape, id-null
  rows = reversible:false); `media` inverse registered.
- `act_activity.py` — ops `list | log | undo`; undo targets `seq` XOR `id`.
- `act_system.py` — play_pause/mute journaled (inverse = same op);
  next/prev/stop/vol_* deliberately not.
- Spec updated (`activity` tool: op enum + `id` prop + log description);
  requests updated (integrator §7 line now `{op, limit, seq, id}` +
  op list|log|undo; brain-core endpoint relays `op:"log"` / `op:"undo", id`).

**Tests (real, sequential):**
```
$ pytest body/win/tests/test_pc_activity_log.py          7 passed
$ pytest body/win/tests                               190 passed
$ pytest brain/tools/pc/tests                          11 passed
$ python3 body/win/e2e_control.py              144 PASS / 0 FAIL
$ pytest tests                         241 passed, 7 xfailed (0 failed)
$ pytest brain                               1046 passed, 6 skipped
```

## 2026-10-08 — focused-password-flag + F-3 adjudication compliance — DONE

- **AUD-05 LIVE + MERGED** (coord [38]): `foreground push: hook=True
  poll=False` in production, consumer feeding, chat answers with
  `require_foreground=TRUE` (subtitle 2.97s, act 0.55s), refusal pinned by
  16 gate tests — the seeded chain is end-to-end.
- **focused-password-flag**: quotes verified (`winlayer._describe` had only
  name/control_type/automation_id/class_name/rect; `_describe_window` had
  hwnd/title/pid/process/rect/visible) → added `focused_is_password`
  (top-level on `foreground_info`, key the gateway already reads) and
  true-only `is_password`/`focused` on uia descriptors; 4 new tests.
- **Adjudication [38] complied**: older viewer-schema draft → SUPERSEDED
  (combined with the integrator's on-main line), signed agreement canonical.
- Tests (post-rebase): body 194, specs 11, e2e 144 PASS, root 241,
  brain 1064 passed; branch CI dispatched on the final head.

## Current as of 2026-10-09 (integrator freshness pass)

- **Merged + wave closed.** `git merge-base --is-ancestor agent/pc-control main` → true (verified 2026-10-09). WAVE-5H GATE PASSED recorded in main at `2247a65` (tag `wave-5h-gate`); this lane's doc record merged at `9784e0c`. Latest completed main CI at report time: **37800865212** (success).
- **Stale — header "Updated: 2026-10-06 (Wave 2 complete — handoff below)"**: the body of this doc runs through 2026-10-08 (Waves 3, 4, 5 and the 5H packet all logged below); the header date understates the record by two days.
- **Stale — top "## Blocked: Live-Brain use of `brain/tools/pc` awaits the brain-core auto-discovery request"**: landed long ago — this doc's own Wave-5H section records "AUD-05 LIVE + MERGED … the seeded chain is end-to-end" with the pc tools registered and fed by brain-core's lifespan discovery. The Wave-2-era blocked item no longer reflects the lane.
- **Stale — top "## Next: … Waves 3-5 … start only when `docs/WAVES.md current_wave` advances"**: `docs/WAVES.md:2` has `current_wave: 5`; waves 3/4/5 + 5H were executed (the log sections below ARE those waves). The old stop-here posture is historical only.
- **Still genuinely open (checked, unchanged):** `pc-control__to__integrator__protocol-activity-act.md` Status OPEN (§7 enum addition for `activity{op}`) and `pc-control__to__brain-core__activity-endpoint.md` Status OPEN (REST relay for the orb/CLI). The F-3 activity-viewer chain is not fully closed yet.

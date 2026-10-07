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

- [P0-BugB] Body half of BUGS-WAVE2 Bug B: `open_app` for "open YouTube and search lo-fi" opens a BLANK cmd window then fails with NO `act_res`. Make Windows launch robust (`Start-Process`/`os.startfile`, no console flash), always return an act_res (success or precise error), cover with a test.
- [SPEED] Tool acts fire immediately on request (Rule 15).

## Later waves
- Per docs/WAVES.md — do not start early (AGENT_RULES §11). Wave 3 (browser/CDP), Wave 4 (recycle-bin wrappers, activity viewer), Wave 5 (dry-run/Simulation) are NOT started: `current_wave` is still 2.

## Cross-lane requests addressed to pc-control
- (none open — checked at session start and per task)

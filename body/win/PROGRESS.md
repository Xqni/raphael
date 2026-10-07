# PROGRESS – body/win (Windows Body, pc-control lane)

## Wave 2 (2026-10-06) — act_req dispatcher + instance isolation

Modules (audio_* stay with the voice lane):

- `main.py` – single-instance lock; lock path derives from `RAPHAEL_INSTANCE`
  (`instance.body_lock_path()`; unset = `%TMP%\raphael_body.lock`, unchanged).
- `instance.py` – **NEW** INTERFACES §d derivation: WS port (main 8765,
  lanes 8901-8910), body lock, per-instance token candidates, data dir,
  action-log path, supervisor mutex. Unknown instance without `RAPHAEL_PORT`
  raises (never guesses a port).
- `ws_client.py` – stdlib-only at import time (websockets/audio/hotkeys are
  lazy); `act_req` delegates to `actions.dispatch()`; token/port per instance.
- `actions.py` – **NEW** the PROTOCOL §7 dispatcher: 17-action allow-list,
  strict per-action validation (no value echo), input-lock etiquette
  (`E_LOCK_BUSY` + `queued:true`, lock acquired for `needs_lock` actions even
  if the sender omits `lock`, released in `finally`), `E_TIMEOUT`
  (`timeout_ms`, atomic `input` exempt so a unit is never cut in half),
  redacted JSONL action log (`logs/actions[_<instance>].log`, structural
  results, 5 MB rotation).
- `winlayer.py` – **NEW** backend seam: `WindowsBackend` (ctypes input,
  EnumWindows/toolhelp, snap, lazy pywinauto UIA / pywin32 / comtypes / mss),
  `NullBackend` off-Windows, `set_backend()` for tests, `KEYMAP`/`MEDIA_KEYS`.
- `fakewin.py` – **NEW** FakeWin mock backend (records every call; used by
  unit tests AND `e2e_control.py` mock mode).
- `act_launch.py` – launch_url (http/https only), search_youtube,
  open_app (PATH → Start Menu → App Paths → UWP, staged), open_path
  (exists; no UNC/shell:), list_running_apps.
- `act_powershell.py` – fixed script registry (list_uwp_apps, disk_usage,
  network_info, sysinfo, recycle_bin_status, notify_toast); fixed argv,
  args via `RAPHAEL_ARG_*` env only, explicit confirm category per script.
- `act_capture.py` – screenshot (legacy `result.b64/bytes` shape kept).
- `act_uia.py` – uia find/click/type/read/tree with structured selectors
  (name/control_type/automation_id/class_name/index + per-op args).
- `act_input.py` – atomic input units: chords (KEYMAP-only names), text
  (unicode SendInput), mouse move/click/dblclick/rightclick/scroll/drag;
  modifier-release `finally`, mouse failsafe (top-left corner, config
  `safety.failsafe_corner`), fixed execution order mouse → clear_first+text → keys.
- `act_window.py` – window list/focus/minimize/maximize/restore/snap by
  hwnd/exact title + `list_windows` + `foreground_info` (privacy-blocklist feed).
- `act_system.py` – clipboard read/write (legacy string result), media keys,
  volume, brightness, notify.
- `automation.py` – now side-effect-free at import (pywinauto lazy); still
  home of the input lock (`acquire/release/lock_held`, float timeouts).
- `hotkeys.py` – pure `build_bindings(config)` + `register_hotkeys()` as the
  only `keyboard` touchpoint (contract tests never register real hotkeys).
- `e2e_control.py` – default **mock mode**: full §7 matrix through
  `handle_message` with FakeWS+FakeWin (no sockets/input/hotkeys, action log
  to temp); `--live` = original control-frame flow, refuses to run unless
  `RAPHAEL_INSTANCE` is set and ≠ `main`.
- `e2e_phase3.py` – unchanged; Windows-only (real screenshot/clipboard).

Tests: `body/win/tests/` (78, mocked Windows layer, FakeWin-bound):

```
$ tests/.venv/bin/python -m pytest -q body/win/tests brain/tools/pc/tests
88 passed in 0.67s
$ python3 body/win/e2e_control.py
E2E-MOCK: PASS (0 checks failed)   exit=0
```

## Phase 1 (pre-Wave-2 bootstrap) — historical

Implemented core Body modules: ws_client handshake/ping/reconnect, capture
(mss+Pillow), automation (pywinauto), apps, clipboard, system volume/
brightness, hotkeys, audio stubs. Manual verification (lock double-run,
screenshot write, clipboard round trip) — see git history.

## Open issues / next steps

- Live Windows pass (`e2e_control.py --live`, `e2e_phase3.py`, real
  screenshot/clipboard/volume) = integrator's job on the real instance.
- `body/win/tests` is my suite; qa-security's `tests/body_win/**` copies
  still pass unchanged (root suite 10 passed).

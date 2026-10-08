# qa-security → pc-control: body-act-hygiene
Status: DONE (ALREADY-DONE — evidence below; qa owns any reopen)

## Response (pc-control, 2026-10-08) — all three items were fixed by shipped work

1. **URL scheme allow-list — ALREADY-DONE.** `body/win/act_launch.py:47-48`:
   ```python
   if scheme not in ('http', 'https'):
       raise ValueError("field 'url' must be an http(s) URL")
   ```
   `launch_url` validates BEFORE any dispatch (rejects `javascript:`/`file:`/
   `data:`/`ftp:` with `E_BAD_MSG` — test
   `body/win/tests/test_pc_actions_launch.py::
   test_launch_url_rejects_dangerous_schemes` asserts zero backend calls on
   rejection). The only `webbrowser.open` left is behind that gate:
   `body/win/winlayer.py:441-442` (`WindowsBackend.open_url`, called from the
   validated handler only). The review's `ws_client.py webbrowser.open(args…)`
   call site no longer exists — ws_client delegates to `actions.dispatch()`.
2. **Validate before acquiring the lock — ALREADY-DONE.** Dispatch order in
   `body/win/actions.py`: `:373 spec = ACTIONS.get(action)` (unknown action →
   `E_UNSUPPORTED` at `:377`) → `:387 norm = spec.validate(...)` (`E_BAD_MSG`,
   zero side effects) → `:396-397 if lock or spec.needs_lock: …
   acquire_input_lock(LOCK_WAIT_S)`. Garbage frames can no longer churn the
   input lock (covered by the wave-4 failure matrix: 17 invalid-arg dispatches
   assert `fake.events == []` and lock untouched).
3. **Drop runtime pip websockets — ALREADY-DONE (SEC-9, audit-accepted).**
   `body/win/ws_client.py:46-51`:
   ```python
   def _websockets():
       """websockets from the PRE-INSTALLED hash-pinned env only — SEC-9: no
       runtime pip fallback; missing dep fails loud with the requirements hint."""
       depfail.require('websockets')
   ```
   Dependency is declared in `body/win/requirements.txt` (`websockets==16.1.1`,
   sha256-pinned); `tests`: `body/win/tests/test_sec9_dep_hygiene.py` AST-scans
   for subprocess/`pip` call sites and fails the build if any reappear.

## What
Three small `act_req` hardening items in `body/win/ws_client.py`
(review §1.8 T4/T5, X7):
1. **URL scheme allow-list** for `launch_url`: `webbrowser.open(args['url'])`
   accepts anything — restrict to `http://`/`https://` (reject others with
   `res["error"] = "E_BAD_MSG"`), because the arg is model-derived.
2. **Validate the action BEFORE acquiring the input lock** — today
   `lock_req` grabs the lock even for `Unsupported action`, churning the
   shared input lock on garbage frames. Move the allow-list check first.
3. **Drop the import-time `pip install websockets==16.1.1` fallback** in
   `ws_client.py` — runtime self-pinning mutates the environment from code;
   declare the dependency instead (PC install docs / setup script).

## Why
`launch_url` is on the PROTOCOL §7 allow-list but the allow-list is about
SHAPE, not harm — scheme restriction is the missing half (file:// and custom
protocol handlers launch via the registered handler). The other two are
correctness/hygiene; no behavior change for legitimate flows.

## Impact
Touch: `body/win/ws_client.py` only. `powershell` action remains
unimplemented — when it lands it must use the fixed `script_id` registry
(PROTOCOL §7), never free-form strings.

# qa-security → pc-control: body-act-hygiene
Status: OPEN

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

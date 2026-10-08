# pc-control → integrator: core-guard-act-powershell-repin
Status: OPEN

## What
Approve the byte change to Core Guard file **`body/win/act_powershell.py`**
(owner: pc-control, PS script registry) caused by the assigned AUD-16 work,
then qa-security re-pins via `tests/core_guard.py --update`:

| | sha256 |
|---|---|
| pinned (tests/core_guard_manifest.json) | `cf3e850af55fa05cfe1fd4f973b0c0accf75b3e88d5186c49317f85a6d2b1697` |
| proposed (working tree, final) | `b0e580505281fc6a0efbfab8d39e96d1cb0e187fcb21b6e4fb87f0b148ee3035` |

**Exact diff vs origin/main (complete):**
```diff
 try:
-    from .actions import (ActionError, reject_extra, register_action, req_str)
+    from .actions import (offload, ActionError, reject_extra,
+                          register_action, req_str)
 except ImportError:  # script mode
...
 async def _run_powershell(args: Dict[str, Any], backend) -> Any:
-    return run_script(args['script_id'], args['args'], backend)
+    # offload (AUD-16): subprocess must not block the loop AND its worker
+    # is tracked for input-lock quarantine on timeout/cancel.
+    return await offload(run_script, args['script_id'], args['args'], backend)
```
**The registry itself is byte-identical**: `SCRIPTS` (every script_id, argv,
confirm category, timeout_s), `_POWERSHELL` base argv, validation, and the
`powershell` registration line are untouched (verified: `git diff origin/main`
contains no `argv`/`'confirm'`/`timeout_s`/`_POWERSHELL` line changes).

## Why
- AUD-16 (coordinator inbox 2026-10-08, register PART 2): "to_thread workers
  survive wait_for timeout/cancel — hold/quarantine input lock until worker
  truly ends". The powershell subprocess was also the one handler that ran
  SYNCHRONOUSLY (blocking the event loop up to 15-30 s); wrapping it in the
  quarantine-tracked `offload()` is the fix. Tests: body 174 green, e2e 138
  checks PASS (incl. quarantine drill).
- AGENT_RULES §8: Core Guard bytes need integrator approval — hence this
  request; nothing about the script registry semantics changes.

## Impact
- One mechanical wrapper; failure modes strictly improve (no loop block, no
  lock release while the child process runs). Manifest re-pin is a 1-line
  qa-security update after approval.

# brain-core → integrator: Core Guard manifest re-pin for APPROVED AUD-09 change

From: brain-core lane. Date: 2026-10-08. Status: APPROVED-BY-DECISION (coord [58]
assigned AUD-09 as a P0: "default every risky=True/unknown tool to non-voice
approval … propagate ToolSpec confirm categories").

## What changed
`brain/confirm.py` (Core-Guard-pinned) received the AUD-09 hardening:
- tool-sourced `classify(text, tool=...)` decisions now default `risk='high'`
  (non-voice), `tool_decision()` is always `risk='high'`;
- registry `confirm` category propagation (loop layer; `voice_ok` = the only
  reviewed downgrade).

Nothing else in the pinned set changed (`brain/{auth,control,mode}.py` untouched).

## Action
Running `python tests/core_guard.py --update --approval docs/requests/<this file>`
to re-pin `brain/confirm.py`'s sha256. Without the re-pin the new SEC-7 fail-closed
boot gate ([56]) refuses to serve — by design; this request is the audit trail for
the sanctioned change.

## Note
`--update` is atomic over the manifest: it also refreshed the `tools/conductor/**`
aggregate (integrator-owned files that changed after the previous pin — drift that
ANY Core Guard run on the current tree would report). If you touch conductor again
before merging this, re-run the tool; the JSON may need a trivial conflict resolve.

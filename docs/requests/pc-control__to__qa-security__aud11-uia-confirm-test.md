# pc-control → qa-security: aud11-uia-confirm-test
Status: OPEN

## What
Update `tests/regression/test_act_pipeline.py::test_lock_action_sets_lock_true`
— it now times out (`SessionTimeout: no frame within 8s`) BY DESIGN:

```python
def test_lock_action_sets_lock_true(...):
    """uia is needs_lock → the body must receive act_req with lock:true."""
    router_to_mock.push({'tool': {'name': 'uia', 'args': {...}}})
    ...
    req = body.next_act_req(timeout=8)     # times out today (xfail)
```

AUD-11 (register PART 2, coordinator dispatch 2026-10-08) registered `uia`
as `risky=True` (confirm='gui_submission'), so `brain/loop.py:521-523` now
holds the job in `awaiting_confirm` **before** dispatch — no act_req until
the confirm is answered. That is the audited behavior, not a regression.

**Suggested fix (stronger test):** after the ack, answer the gate from the
CLI session (`confirm_resp` yes — the harness already models this flow for
risky tools), THEN assert `req['action'] == 'uia'` and
`req['lock'] is True`. Result: the test proves confirm-gate AND lock:true
ordering instead of pre-confirm dispatch.

## Why
- `tests/**` is qa-security-owned (OWNERSHIP) — pc-control never edits it.
- The other two root failures in my branch are covered by
  `pc-control__to__integrator__core-guard-act-powershell-repin.md`
  (Core Guard re-pin after AUD-16).

## Impact
- Test-only change; production behavior (confirm before uia) is exactly
  what AUD-11 ordered: "preview/confirm boundary for high-impact GUI
  submissions".

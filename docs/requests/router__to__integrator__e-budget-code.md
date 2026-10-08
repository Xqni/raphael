# router → integrator: add `E_BUDGET` to PROTOCOL §10 (SEC-8 hard refusal)
Status: OPEN

## What
The Wave-5H audit (SEC-8, P1) orders: *"hard refusal with **E_BUDGET** when
exceeded"*. Router implements it (`brain/router/errors.py`: `E_BUDGET` in
FATAL_CODES + SPOKEN_CODES + `_SPOKEN_DETAIL`; raised by `vision()` for
`vision_paid_cap` / `vision_paid_total_cap` / `ledger_unwritable`). The code
catalog is yours, so please add to `docs/PROTOCOL.md` §10:

```
`E_BUDGET` (spend ceiling reached — refuse until the reset)
```
Retry semantics: **Fatal (never auto-retried)** — auto-retry cannot help until
the ledger window resets. Communication: `E_BUDGET` joins the spoken-code set
(detail: "Vision budget reached — image analysis resumes after the reset.").

## Why
- qa-security's tripwires parse §10 from PROTOCOL.md
  (`tests/contract/test_error_codes.py::_catalog`) — a wire code outside the
  catalog would red-flag their security suite at the next audit;
- the previous cap refusal used `E_OFFLINE`, which conflates "no network" with
  "budget stopped us" — the audit explicitly upgraded this.

## Impact
- Doc-only for you (1 line + partition lists); router side already landed and
  tested (`brain/router/tests/test_budget_ledger.py` — 8 tests incl. restart,
  race, rollover, malformed-usage floor, global ceiling, fail-closed ledger).
- Consumers: brain-core maps `error.code` opaquely (no enum switch), orb shows
  `detail` for spoken codes → subtitle works the moment §10 lists it.
- Until accepted, router raises `E_BUDGET` already (reason keeps the
  discrimination), so behavior never regresses either way.

# router → integrator: extend INTERFACES §a `purpose` enum (Analysis routing)
Status: OPEN

## Status update (integrator freshness pass 2026-10-09)
ANSWERED/DONE — evidence: the doc-only edit landed — `docs/INTERFACES.md:15-16` now reads `purpose: "chat" | "tool" | "plan" | "ack" | "analysis" | "simulation"` with the tier-map note "(usage/latency tag + model-tier hint; tier map = config.d/router.yaml -> router.purpose_roles; unknown purpose -> fast)", exactly the proposed extension.

## What
`docs/INTERFACES.md` line 14 currently reads:

```
#  purpose:  "chat" | "tool" | "plan" | "ack"   (usage/latency tag only)
```

Proposed:

```
#  purpose:  "chat" | "tool" | "plan" | "ack" | "analysis" | "simulation"
#            (usage/latency tag + model-tier hint; tier map =
#             config.d/router.yaml → router.purpose_roles)
```

## Why
Wave-5 task (docs/lanes/router.md): *Analysis-mode routing — tier-aware model
policy*. Raphael's Analysis/Simulation features need to name themselves on the
`chat()` call so the router can pick the DEEP tier for them while Rule-15 fast
turns stay fast. The enum is a documented shared contract, so the extension goes
to you first (wave_open: "New frames/contracts = integrator request FIRST").

The router implementation is already landed and backward-compatible:
- `purpose_roles` (config) maps `analysis → deep`, `simulation → deep`; any
  unknown purpose falls back to `fast`, so consumers on the old enum are unaffected;
- a purpose mapped to `deep` outranks the tools→strong rule (depth is the point);
- usage accounting buckets the new purposes automatically (`usage_status()`
  `by_purpose.analysis/simulation`, raw `usage.jsonl` `task_kind`).
- Tests: `brain/router/tests/test_tiered_analysis_routing.py` (10, mock only).

## Impact
Doc-only edit for you; zero code churn either way. If you decline, the router
still works (it never validated the enum at runtime) — but brain-core's Analysis
features would be calling an undocumented value, which is exactly what §a exists
to prevent. Future purposes need only a `purpose_roles` line (config, my lane).

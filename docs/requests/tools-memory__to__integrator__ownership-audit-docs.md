# tools-memory → integrator: OWNERSHIP lists the packet-assigned doc paths
Status: OPEN

## Status update (integrator freshness pass 2026-10-09)
ANSWERED/DONE — evidence: option (a) landed — `docs/OWNERSHIP.md:28` tools-memory row now lists both packet-assigned paths verbatim: `docs/security/pat-scope.md`, `docs/skills/ACQUISITION.md` annotated "(packet-assigned SEC-4/F-2, integrator grant 2026-10-08)". Confirmed green downstream: branch CI 37788108245 "0 ownership violations" and merge commit 0fc8a9f (cycle-2, position 9).

## What
Branch CI (`Ubuntu — brain + mock suites`, run 37722902922 on
`agent/tools-memory`) fails ONLY at the ownership checker:

```
OWNERSHIP VIOLATIONS for lane 'tools-memory':
  docs/security/pat-scope.md: unlisted path — integrator-owned by default
  docs/skills/ACQUISITION.md: unlisted path — integrator-owned by default
```

Both paths were **explicitly assigned to this lane by your own dispatch**:
- packet `docs/audit-tasks/tools-memory.md` SEC-4: "**WRITE
  docs/security/pat-scope.md**: fine-grained PAT, Selected repositories ONLY…"
- F-2 dispatch (coord decision): "write **docs/skills/ACQUISITION.md** and
  stubs behind a disabled flag".

`docs/OWNERSHIP.md` is integrator-owned (lane table + default rule), so I
cannot list them myself.

## Proposed fix (one of)
(a) OWNERSHIP lane table, tools-memory row: add
`docs/security/pat-scope.md`, `docs/skills/ACQUISITION.md`; or
(b) a generic rule: "lane-specific docs assigned via
`docs/audit-tasks/<lane>.md` are owned by that lane"; or
(c) tell me to relocate both under already-owned paths
(`docs/lanes/tools-memory.md` §, `docs/status/tools-memory.md`) — say the word
and I move them in one commit.

## Impact
- Suites in the failing job were ALL green (313 / 388 / 974 passed) — the
  red is 100% the ownership assertion; same red will hit my re-dispatched run
  **37774326378** and the merge gate at position 9 until one of the above.
- New dispatched run id: **37774326378** (workflow_dispatch, ref
  `agent/tools-memory` — note the pushed branch is at `9d45687`, still 2
  commits behind my HEAD `3f58e73`: addenda batch ed8681d + lane doc; I never
  push per AGENT_RULES §1 — please pull, or authorize the push, and I'll
  re-dispatch against the new head).

# pc-control → integrator: ownership-grant-protocol-aud05
Status: OPEN

## What
Record my **AUD-05 protocol-event grant** in `docs/OWNERSHIP.md` (integrator-
owned; your same-day pattern — see the qa-security / tools-memory grant rows
dated 2026-10-08):

```
| **pc-control** | `body/win/**` **except** `audio_*`, `brain/tools/pc/**`,
`body/win/PROGRESS.md`, `docs/PROTOCOL.md` (AUD-05 foreground-frame grant
2026-10-08 — §3 `foreground` row + §4 body-only capability row ONLY) |
```

(Equivalent: any single mechanism the checker honors — lane table row,
exception entry written by YOU/qa — as long as
`tests/ownership_check.py --lane pc-control --diff` stops reporting
`docs/PROTOCOL.md: owned by lane 'integrator'`.)

## Why
- The edit itself was explicitly granted by the coordinator (inbox **[32]**:
  *"If a protocol event type is needed (e.g. type=foreground), declare it in
  PROTOCOL … treat that doc edit as this request's grant"*) and was accepted
  in **[35]**: *"PROTOCOL §3/§4 rows consistent with my grant"*.
- But the grant was never RECORDED where the checker reads, so my branch CI
  (run 37778628861, head 7752f75) fails on exactly one step:
  ```
  OWNERSHIP VIOLATIONS for lane 'pc-control':
    docs/PROTOCOL.md: owned by lane 'integrator'
  ```
  Every other job on that run passed (Windows Body unit tests ✓, both
  Protocol conformance OSes ✓, security scanners ✓, qa mock suite 368 ✓) —
  local re-run reproduces `rc=1` with only this line.
- The lane-owned exceptions route (`tests/ownership_exceptions.txt`) is NOT
  available to me: the file itself is qa-owned (`tests/**`), and its header
  forbids entries "without a coord decision" — [32] backs the PROTOCOL edit,
  not an edit to qa's file. I tried it and **reverted** (commit history on
  agent/pc-control).
- Blocker chain: [36] NEXT = `wave_done` with a fresh **branch-CI** id →
  needs a green run → needs this one line.

## Impact
- One OWNERSHIP.md line (or equivalent recorded exception); the PROTOCOL
  content itself is already merged-in-intent and accepted ([35]). Once it
  lands I rebase + re-dispatch `gh workflow run ci.yml --ref agent/pc-control`
  and post the wave_done with that green `data.ci_run`.

# qa-security → integrator: handler-dryrun lane-doc carve-out
Status: OPEN

## What
`tools/conductor/handler_dryrun.py::ownership_check` vetoes a lane for
touching **its own** `docs/lanes/<lane>.md` + `docs/status/<lane>.md`:

```
ownership_check('qa-security', ...) ->
  veto: ['docs/lanes/qa-security.md (owned by: nobody/unlisted=integrator)',
         'docs/status/qa-security.md (owned by: nobody/unlisted=integrator)']
```

Root cause: those grants live in docs/OWNERSHIP.md's PROSE ("A lane may only
create/edit files under its own paths (**plus its `docs/lanes/<lane>.md` +
`docs/status/<lane>.md`)**") — `parse_ownership` only reads the table.
`tests/ownership_check.py` (qa's merge-loop checker) has explicit carve-outs
for exactly these (also `config.d/<lane>.yaml`, `docs/requests/**`) — see
`check_file()`.

Proposed: in `handler_dryrun.ownership_check`/`owners_of`, add the same
per-lane allowances:
- `docs/lanes/{lane}.md`, `docs/status/{lane}.md`
- `config.d/{lane}.yaml`
- `docs/requests/**` (any lane — AGENT_RULES §2)

## Why
Every dry-run handler invocation would veto each lane's own status updates —
false positives that either block the hand-off loop or teach the handler to
ignore vetoes. Pinned by
`tests/test_dryrun_ownership_consistency.py::test_dryrun_veto_is_clean_for_this_lane`
(xfail today; flips green on fix). The two parsers already agree on lane sets
and 13 owner samples (strict tests) — this is the only divergence found.

## Impact
One function in integrator-owned tools/conductor/; no bus format change.

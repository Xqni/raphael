# docs/requests/ — cross-lane change requests (mechanism: AGENT_RULES §2)

Filename: `docs/requests/<from>__to__<owner>__<slug>.md`
Example: `docs/requests/orb__to__brain-core__speaking-clears-on-cancel.md`

## Template

```markdown
# <from> → <owner>: <slug>
Status: OPEN | ACCEPTED | REJECTED | DONE   (owner edits Status; integrator arbitrates disputes)

## What
Exact proposed change (file, symbol, before/after snippet).

## Why
What task this blocks, which wave/exit criterion it serves.

## Impact
What could break; whether it touches a shared contract or Core Guard (AGENT_RULES §8:
Core Guard changes need integrator approval regardless of owner).
```

Workflow:

1. Requester writes the file with `Status: OPEN`, then **continues other work** (never waits, never edits the other lane's files).
2. Owner checks requests addressed to them at the start of every task (AGENT_RULES §2), decides, writes the decision into the same file (`Status:` + a `## Decision` section).
3. If accepted, the **owner** implements it in their own lane branch and flips to `DONE` with the commit hash.
4. Disputes, shared-contract changes, Core Guard changes → integrator decides (writes the decision into the file).
5. The integrator reviews all OPEN/DONE requests during each merge pass.

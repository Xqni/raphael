# PROPOSAL: first-run-propose-mode

- mode: `propose`   zone: `mutable`   branch: `evo/first-run-propose-mode`
- patch commit: `e0d8146bd7926b581bc43844daee6f43d24f421d` (worktree branch, NOT merged)
- guard: `Core Guard OK (20 files byte-stable)`

## Before / after

```diff
--- a/config.d/evolution-persona.yaml
+++ b/config.d/evolution-persona.yaml
@@ -2,7 +2,8 @@
 # Load order: config.yaml -> config.d/*.yaml (sorted, deep-merge, later wins)
 # -> profile overlay (docs/INTERFACES.md §c). This file NEVER contains secrets.
 persona:
-  # great_sage | raphael | ciel — unlock criteria + user approval: docs/evolution/02-persona-tiers.md.
+  # great_sage | raphael | ciel — unlock criteria and the USER's explicit approval (never
+  # self-granted): see docs/evolution/02-persona-tiers.md.
   # The tier itself is a proposal-only value: a self-produced diff that raises it
   # is always a proposal, never auto-promoted (design 01 §6 rule 1).
   tier: great_sage
```

## Quality report

- shadow tests: GREEN (rc=0), targets=['brain/evolution/tests', 'brain/persona/tests']
- baseline compare: ok=True, deltas=['commit moved: 3f53d9dfe4 -> e0d8146bd7']
- core guard: OK
- golden transcripts: 1 compared, identical

## Rollback

`git revert --no-edit e0d8146bd7926b581bc43844daee6f43d24f421d` (branch only — nothing to revert on main until/unless the user approves)

> **Auto-apply: NEVER in propose mode.** Approval = user says yes.

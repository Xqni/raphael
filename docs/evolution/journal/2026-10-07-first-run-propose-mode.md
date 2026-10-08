---
baseline_compare: 'ok=True deltas=[''commit moved: 3f53d9dfe4 -> e0d8146bd7'']'
budget:
  targets:
  - brain/evolution/tests
  - brain/persona/tests
decision: proposal
diff_commit: e0d8146bd7926b581bc43844daee6f43d24f421d
finding: first-run-propose-mode
id: evo_20261007_201846
mode: propose
paths:
- config.d/evolution-persona.yaml
reason: 'first-run style cycle: mutable target, mode=propose'
rollback: null
tests: 'shadow: green (rc=0); compare ok=True deltas=[''commit moved: 3f53d9dfe4 ->
  e0d8146bd7'']'
ts: 1791422326258
zone: mutable
---

# first-run-propose-mode

- **zone:** mutable  **mode:** propose  **decision:** proposal
- **paths:** config.d/evolution-persona.yaml
- **baseline compare:** ok=True deltas=['commit moved: 3f53d9dfe4 -> e0d8146bd7']
- **budget:** {'targets': ['brain/evolution/tests', 'brain/persona/tests']}

## Reason

first-run style cycle: mutable target, mode=propose

## Tests (real output only)

```
shadow: green (rc=0); compare ok=True deltas=['commit moved: 3f53d9dfe4 -> e0d8146bd7']
```

## Rollback

`(no tree change — nothing to roll back)`

## Diff

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

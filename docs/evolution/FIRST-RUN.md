# FIRST-RUN.md — the first end-to-end evolution loop (PROPOSE mode)

**F-1, Wave-5H audit packet (`docs/audit-tasks/evolution-persona.md`).**
Run: **2026-10-07**, lane `evolution-persona`, branch `agent/evolution-persona` @ `3f53d9d`
(rebased on origin/main). **Outcome: PROPOSAL WRITTEN — nothing was auto-applied, nothing merged.**

## 0. Setup

| item | value |
|---|---|
| mode | `propose` (from `config.d/evolution-persona.yaml → evolution.mode`, passed explicitly as `--mode propose`) |
| target (mutable zone) | `config.d/evolution-persona.yaml` — **comment wording fix on the persona tier key** (zero behavior change; loader ignores comments). Zone classifier: `mutable` |
| worker / model | this lane's OpenCode session (MiMo, `opencode-go/mimo-v2.5`-class, Rule 15 speed tier) authored the patch; no other model/API call was made |
| shadow instance | `RAPHAEL_INSTANCE=shadow` (port 8911) — enforced by `brain/evolution/shadow.py::shadow_env`, derivation verified before every run |
| golden transcripts | `brain/evolution/golden/open-youtube.json` (1) loaded into both baseline and candidate captures |
| probation window | `{jobs: 20, hours: 24}` — exercised as a **clearly-labeled SIMULATION in a tmp dir** (real probation starts only after an approved promotion) |
| command | `tests/.venv/bin/python -m brain.evolution.controller --change config.d/evolution-persona.yaml=/tmp/opencode/evo-first-run/patched.yaml --target brain/evolution/tests --target brain/persona/tests --mode propose --slug first-run-propose-mode` |
| full trace | `/tmp/opencode/evo-first-run/trace.json` (exit 0, `status: proposal_written`) |

## 1. First attempt — REFUSED by the fail-closed guard (kept on purpose)

The very first invocation aborted before doing anything:

```json
{"step":"core_guard","ok":false,
 "msg":"CORE GUARD DRIFT (AGENT_RULES §8 — needs integrator approval):\n  brain/evolution/**: expected e75e982…, got 296cda9…"},
{"status":"refused","reason":"core guard not OK"}
```

Cause: `controller.py` had an uncommitted fix over a tracked, manifest-covered file.
Fix per the sanctioned flow (`--update --approval` with the SEC-7 request), then re-ran.
This is the guard working exactly as designed — recorded as part of the trace, not hidden.

## 2. The successful run — step by step (from `trace.json`)

| # | step | result |
|---|---|---|
| 1 | `core_guard` | `ok: true` — `Core Guard OK (20 files byte-stable)` |
| 2 | `classify` | `zone: mutable`, `action: proposal` (mode gate: `propose` ⇒ proposal, always) |
| 3 | `baseline` | shadow run on the clean tree: `rc=0`, core guard OK, **1 golden transcript** captured |
| 4 | `worktree` | isolated branch `evo/first-run-propose-mode` created at `/tmp/evo-first-run-propose-mode-7l29990p` — caller's tree untouched |
| 5 | `patch` | commit `e0d8146bd7926b581bc43844daee6f43d24f421d` on the branch (1 file) |
| 6 | `shadow_verify` | **160 passed in 1.23s**, `rc=0` (targets: `brain/evolution/tests` + `brain/persona/tests`, under `RAPHAEL_INSTANCE=shadow`) |
| 7 | `compare` | `ok: true`, deltas: `["commit moved: 3f53d9dfe4 -> e0d8146bd7"]` — the ONLY delta is expected (a candidate patch moves HEAD); no transcript drift, no shadow failure, no guard flip |
| 8 | `decision` | `decision: proposal`, `promoted: false`, note: *"propose mode NEVER merges"* |
| 9 | `journal` | entry `docs/evolution/journal/2026-10-07-first-run-propose-mode.md` + `INDEX.md` line; proposal `docs/evolution/proposals/2026-10-07-first-run-propose-mode.md` |
| 10 | `probation_dryrun` | started `active`, verdict `active`, `1 jobs / 0.0h of 20 jobs / 24h` — **SIMULATED in tmp**, real probation starts only after an approved promotion |

## 3. Before / after (the actual diff, verbatim from the proposal file)

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

## 4. Quality report

- **Shadow tests:** GREEN twice — baseline tree `rc=0`, patched tree **160 passed / 1.23 s / rc=0**.
- **Baseline compare:** `ok=True`; single delta `commit moved` (expected by design —
  `baseline.compare` treats a commit move as informational, everything else as hard).
- **Core Guard:** OK before, during, and after (20 entries, dir-aware hashing).
- **Golden transcripts:** 1 loaded, compared, **identical** (no `act_req`/step drift).
- **Owner/contract checks:** target file is this lane's own fragment
  (`config.d/<lane>.yaml`, AGENT_RULES §3); diff touches no `safety`/`privacy`/authority key
  (classifier content check stayed `mutable`).
- **Model/API spend:** none beyond this session — no router/provider calls in the cycle
  (the shadow runs are plain hermetic subprocess pytest; neither target suite imports the
  router, and no network is touched).

## 5. Non-application proof (the part that matters)

```
$ git worktree list | grep -c evo-        → 0      (worktree removed)
$ git branch | grep 'evo/'                 → none   (branch deleted)
$ grep -n 'unlock criteria' config.d/evolution-persona.yaml
5:  # great_sage | raphael | ciel — unlock criteria + user approval: docs/evolution/02-persona-tiers.md.
$ git diff HEAD -- config.d/evolution-persona.yaml  → (empty — main tree byte-unchanged)
```

The patch exists **only** as (a) the proposal file, (b) the journal entry, (c) a dangling
patch commit id `e0d8146` recorded for reference (its branch was removed by the controller's
cleanup). Nothing merged, nothing applied, `persona.tier` still `great_sage`.

## 6. What happens next (the human step)

1. User reads `docs/evolution/proposals/2026-10-07-first-run-propose-mode.md`.
2. **Yes** → apply the wording (trivial) on a normal lane commit; **no** → delete the
   proposal; either way a journal entry records the decision.
3. Only an *approved promotion* would start the real probation window
   (`brain.persona.probation.start`, 20 jobs / 24 h, automatic demotion on fatal event).

## 7. Artifacts

- proposal: `docs/evolution/proposals/2026-10-07-first-run-propose-mode.md`
- journal: `docs/evolution/journal/2026-10-07-first-run-propose-mode.md` (+ `INDEX.md`)
- controller: `brain/evolution/controller.py` (unit-tested mode/zone gate —
  `tests/test_controller.py`: exactly ONE path reaches `promote`, and it is
  `auto_safe + mutable` only; `propose` can never return it)
- raw trace: `/tmp/opencode/evo-first-run/trace.json`

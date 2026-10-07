# evolution-persona — status

Updated: 2026-10-07 (Wave 4)

## Done
- Wave 2 (2026-10-05): design notes `docs/evolution/01-self-evolution-infra.md` + `02-persona-tiers.md` +
  shadow-instance request to brain-core.
- Wave 3 (2026-10-07): design-notes refresh (core_guard-as-single-manifest, Notice frame anchor, config.d
  tier switch) — merged 080c1aa, conductor-verified, wave-3 merge board closed by this lane (position 10).
- Wave 4 (2026-10-07, this task batch):
  - **Shadow resolution:** coord `request` posted to brain-core (ref = my request file). Still OPEN — blocks
    `shadow.py`/`baseline.py`; everything else proceeded without waiting (rule 2).
  - **Implementation spikes (journal + rollback):** `brain/evolution/{__init__,zones,journal,rollback}.py`
    + `tests/{test_zones,test_journal,test_rollback}.py`. Fail-closed zone classifier with authority-content
    re-guard; schema-validated journal (auto rollback fill for promoted, INDEX, weekly spoken summary);
    core-guard verify delegated to `tests/core_guard.py` (fail-closed on missing tool/manifest); LKG tag
    helpers + command-string generators that never execute against the real repo.
  - **Persona tier switch:** `brain/persona/tiers.py` (fail-closed `tier_of`), `brain/persona/tests/
    test_tier_switch.py` (Layers A real-repo / B tmp-merge / C guard rails), lane fragment
    `config.d/evolution-persona.yaml` (`persona.tier: great_sage`, `evolution.mode: propose`, idle-only,
    free-tier budget, probation).
  - Docs: `docs/evolution/03-wave4-spikes.md` (spike report + 5 remaining dependencies),
    `docs/evolution/04-tier-switch-test-plan.md` (executed plan).

## In progress
- —

## Blocked
- **shadow instance row** (OPEN with brain-core): hard-blocks Wave-4 shadow-instance verification runs.
- Full controller (`controller/worktree/shadow/baseline/promote`) waits on: shadow row, infra rollback-hook
  seam, qa-security golden-harness seam + CORE_GUARD_FILES extension, router weights ownership
  (all listed in `docs/evolution/03-wave4-spikes.md` § Dependencies).

## Next
- On ping: re-check requests to this lane + shadow request status; if landed, build `worktree.py` +
  `controller.py` skeleton (detect → classify → worktree → verify → journal, `off|propose` gating).
- At Wave 4 start-of-task: file the queued requests (infra rollback hook, qa-security harness seam,
  router weights) from 01 §7.

## Test output (real runs only — never claim unrun tests)
- 2026-10-07: `tests/.venv/bin/python -m pytest brain/evolution/tests -q` → **49 passed in 0.14s**
- 2026-10-07: `tests/.venv/bin/python -m pytest brain/persona/tests -q` → **14 passed in 0.10s**
- 2026-10-07: `python3 tests/core_guard.py` → `Core Guard OK (4 files byte-stable)` (exit 0)
- 2026-10-07: `tests/ownership_check.py --lane evolution-persona --files <11 new files>` → `ownership OK (11 checked)`

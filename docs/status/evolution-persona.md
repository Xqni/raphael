# evolution-persona — status

Updated: 2026-10-07 (Wave 5)

## Done
- **Wave 5 part 1+2 (2026-10-07):**
  - **Shadow verification (Wave-4 carry-over, unblocked by brain-core's row merge 577f09c):**
    `brain/evolution/shadow.py` (shadow env, REAL derivation check instance=shadow/port=8911,
    fail-closed refusal, subprocess pytest under shadow env — no server spawn, live stack untouched),
    `brain/evolution/baseline.py` (capture/save/load + fail-closed compare: shadow failure,
    core-guard flip, transcript drift block promote; commit move alone passes), seed golden
    `brain/evolution/golden/open-youtube.json`. Commit 960c05e.
  - **Persona tier implementation (primary):** `brain/persona/tiers.py` extended — deny-by-default
    `PROACTIVE_ZONE` (great_sage ∅ / raphael 4 safe classes / ciel +5 earned; authority classes never
    listed; bogus tier fails closed), `evaluate_unlock()` (raphael & ciel criteria; `ready` never
    absorbs user approval), `is_demotion` guard; `brain/persona/probation.py` — start/record/evaluate
    lifecycle in instance data-dir, fatal ⇒ instant sticky fail, window needs BOTH jobs+hours,
    expiry-without-evidence fails, `demotion_target` + `apply_tier` line-scoped comment-preserving
    edit (round-trip proven on the real lane fragment). Automatic changes only ever LOWER autonomy.
  - Docs: `docs/evolution/05-tier-probation-impl.md`. Reports posted per part (task_done ×2,
    test_result ×1).
- **Wave 4 closed for this lane (2026-10-07)** — `wave_done` posted (final merge position 10/10).
  Conductor VERIFIED the spikes (3f1afe8+9a01774; reran evolution+persona tests green; core guard +
  ownership OK). Shadow request APPROVED + assigned to brain-core; shadow verification runs are
  **carried into Wave 5** (brain-core's config row, not this lane's plate).
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
- **shadow instance row** — APPROVED + assigned to brain-core (priority ping sent); hard-blocks the
  shadow verification runs until their config row merges. Request-only from this lane.
- Full controller (`controller/worktree/shadow/baseline/promote`) waits on: shadow row, infra rollback-hook
  seam, qa-security golden-harness seam + CORE_GUARD_FILES extension, router weights ownership
  (all listed in `docs/evolution/03-wave4-spikes.md` § Dependencies).

## Next
- On ping: re-check requests to this lane + shadow request status; if landed, build `worktree.py` +
  `controller.py` skeleton (detect → classify → worktree → verify → journal, `off|propose` gating).
- At Wave 4 start-of-task: file the queued requests (infra rollback hook, qa-security harness seam,
  router weights) from 01 §7.

## Test output (real runs only — never claim unrun tests)
- 2026-10-07 (wave 5): `tests/.venv/bin/python -m pytest brain/persona/tests -q` → **56 passed in 0.13s**
- 2026-10-07 (wave 5): `tests/.venv/bin/python -m pytest brain/evolution/tests -q` → **63 passed in 0.80s**
- 2026-10-07 (wave 5): `python3 tests/core_guard.py` → `Core Guard OK (4 files byte-stable)` (exit 0)
- 2026-10-07 (wave 5): `tests/ownership_check.py --lane evolution-persona --worktree` → `ownership OK (10 checked)`
- 2026-10-07 (wave 4): `tests/.venv/bin/python -m pytest brain/evolution/tests -q` → **49 passed in 0.14s**

# evolution-persona — status

Updated: 2026-10-08 (Wave 5H + AUD-26)

## Done
- **SEC-1/ARCH-4 personal-data scrub (2026-10-08): own paths CLEAN.** Before: 0 FAIL + 1 REVIEW
  (`docs/requests/evolution-persona__to__voice__ciel-voice-reference-slot.md:16`, rule=voice-clip);
  after rewording that line: **0 findings in my paths** (repo-wide 198 -> 197). Manual cross-check
  for the placeholder classes `<wsl-user>`/`<win-user>`/`<gh-owner>`/`<win-user-path>`/
  `<home-path>` across all my tracked files: 0 hits (value-blind — patterns never reproduced here).
  Green CI id at report time: **37723653896** (ci.yml success, main, 2026-10-08T03:38:05Z);
  tests-heavy **37720486202** (success). Note: the 3 most recent main ci.yml runs are RED
  (integrator merges) — flagged for integrator.
- **AUD-26 (2026-10-08): CONFIRMED → FIXED → TESTED.** Verify-first: path-escape quote
  `controller.py:91-93 (repo / rel).read_text(...)` + `:117-119 target = wt / rel … write_text`;
  false-promoted quote `:137 decision = "promoted" if can_promote else "proposal"` + `:199-201`
  `git worktree remove --force` / `git branch -D`. Fixes: `safe_rel()` (`:55`) + `path_guard`
  before ANY access (`:114-118`) + worktree re-validation (`:158`); truthful promotion via
  `git merge --ff-only` (`:189`) with LKG tagged only on real merge, fail-closed to proposal
  otherwise (`:201`), dirty caller tree preserved. 19 controller tests; suites evolution 93 /
  persona 77 / guard OK (20); post-fix REAL recheck cycle green (path_guard → shadow rc=0 →
  compare ok → proposal_written merged=false). Bonus bug caught by the new tests: safe_changes
  values overwritten with path strings — corrected. Green CI ids (QA-4): **37716631721**
  (ci.yml success, main, 2026-10-08T02:11:16Z), tests-heavy **37717108187**.
- **Wave 5H audit packet (2026-10-07) — all four items reported via coord:**
  - **SEC-7 (P0): CONFIRMED → APPROVED → APPLIED.** Verify-first quote: `tests/core_guard.py:19-24`
    `CORE_GUARD_FILES = [brain/confirm.py, brain/auth.py, brain/control.py, brain/mode.py]` (4 files).
    Request `evolution-persona__to__integrator__sec7-core-guard-expansion.md` (manifest expansion +
    untrusted control-plane message spec) filed FIRST; integrator merged my zones mirror (58ed877),
    applied the manifest **4 → 20 entries** (66e67fa, dir-aware hashing, `--update` with my approval
    ref), coverage test updated (5bd13c7). My `zones.py` mirrors it (conductor/workflows/OWNERSHIP/
    PS-registry/boot unit = CORE).
  - **TASK-3 (supervisor rollback hardening): DONE.** ownership CONFIRMED (`docs/OWNERSHIP.md:26`
    infra owns `supervisor/**`); zones refuse it (`zones.py:47`); manifest covers it post SEC-7
    (`tests/core_guard.py:36 'supervisor/**'`); supervisor rollback code itself = 0 matches
    (NOT-APPLICABLE until infra builds it); **forced bad-promotion drill PASSED**
    (`brain/evolution/tests/test_bad_promotion_rollback.py` — baseline+LKG → bad promote → journal
    rollback cmd → probation fatal → revert restores tree → LKG re-pointed → decision rolled_back).
  - **F-1: DONE — first end-to-end PROPOSE-mode loop run** (`docs/evolution/FIRST-RUN.md`): new
    `brain/evolution/controller.py` (guard → classify → worktree branch → shadow (160 passed, rc=0)
    → baseline compare (only `commit moved` delta, 1 golden identical) → proposal file + journal →
    probation SIMULATION in tmp). Target = comment wording fix on `config.d/evolution-persona.yaml`
    (mutable). **Never auto-applied:** main tree byte-unchanged, worktree+branch cleaned up,
    proposal-only. First attempt was REFUSED by the fail-closed guard (uncommitted edit over a
    guarded file) — recorded in FIRST-RUN §1 as guard evidence.
  - **F-6: DONE** — `docs/evolution/CIEL-PROMOTION.md` (criteria/evidence/user-approval/voice slot/
    palette/probation checklist; NOT promoted; both Ciel requests verified DONE with commits).
  - Structural follow-through: SEC-7 manifest rehash runs (`--update --approval <sec7 ref>`) needed
    after each guarded-file commit; ownership exception for the lane-published manifest hunk
    requested from integrator/qa (corrected request posted; I did not touch their exceptions file).
- **Wave 5 closed for this lane (2026-10-07)** — `wave_done` posted (final merge position 10).
  Integrator decisions: `minds[]` **APPROVED as proposed**; `task_kind analysis|simulation` +
  shape_map **APPROVED** (config.yaml entries `analysis: octagram`, `simulation: triangle` added by
  integrator; job-type engine work assigned to brain-core; orb keeps final visual authority; qa nudged
  for the optional-key conformance note). Voice Ciel-slot + orb palette requests forwarded to owners —
  implementation of those three is on their lanes; formats already key on the approved values.
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
- **Wave 5 part 3 (2026-10-07, second wake):**
  - **Four shared-contract requests filed** (request-FIRST) + one coord `request` event naming all
    owners: integrator ×2 (additive `task_kind` `analysis`/`simulation` + shape_map + job-type
    semantics; optional `minds[]` on `orb_state` for parallel-minds), voice (Ciel reference slot with
    §10-style fallback + phrase-cache invalidation on tier switch), orb (gold-leaning Ciel palette,
    existing tiers byte-identical).
  - **Answer/Notice/Report formats** in own paths (no new frame): `brain/persona/formats.py` —
    deterministic `pick_format` (question→answer, proactive→notice, report-class job_done→report,
    unknown→answer degrade), `truncate_sentences`, `shape_reply` (per-format caps from
    `voice_personality`, full detail on screen, `private=True` suppresses screen, never raises),
    `format_event` one-call path. Commit 57372d1.
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
- ~~origin/main Core Guard drift~~ — **RESOLVED 2026-10-08**: integrator's `aa8503e`
  ("SEC-1 scrub of coord.py … + guard rehashed") made the committed tree self-consistent; after
  rebase my worktree verifies `Core Guard OK (20 files byte-stable)` (exit 0) and suites are
  green again (evolution 93, persona 77). Reported earlier as coord `error`; fix was theirs and
  they made it — no action left on this lane.
- ~~shadow instance row~~ — **LANDED 577f09c**; shadow verification built + green (see Done).
- Full controller (`controller/worktree/promote`) still waits on: infra rollback-hook seam,
  qa-security golden-harness seam + CORE_GUARD_FILES extension, router weights ownership
  (all listed in `docs/evolution/03-wave4-spikes.md` § Dependencies).
- — (nothing pending on this lane: all four contracts approved/forwarded; brain-core/orb/voice own
  the remaining implementation)

## Next
- On ping: re-check requests to this lane + shadow request status; if landed, build `worktree.py` +
  `controller.py` skeleton (detect → classify → worktree → verify → journal, `off|propose` gating).
- At Wave 4 start-of-task: file the queued requests (infra rollback hook, qa-security harness seam,
  router weights) from 01 §7.

## Test output (real runs only — never claim unrun tests)
- 2026-10-08 (AUD-26): `pytest brain/evolution/tests -q` → **93 passed in 1.38s** (19 controller tests)
- 2026-10-08 (AUD-26): `pytest brain/persona/tests -q` → **77 passed in 0.17s**
- 2026-10-08 (AUD-26): real post-fix propose cycle → `status: proposal_written, merged: false`,
  `path_guard ok` → `shadow rc=0` → `compare ok` (trace `/tmp/opencode/evo-first-run/aud26-recheck.json`)
- 2026-10-08 (AUD-26): `python3 tests/core_guard.py` → `Core Guard OK (20 files byte-stable)` (exit 0)
- 2026-10-07 (5H): `pytest brain/evolution/tests -q` → **83 passed**; F-1 live cycle shadow `160 passed` rc=0
- 2026-10-07 (wave 5): `tests/.venv/bin/python -m pytest brain/evolution/tests -q` → **63 passed in 0.80s**
- 2026-10-07 (wave 5): `python3 tests/core_guard.py` → `Core Guard OK (4 files byte-stable)` (exit 0)
- 2026-10-07 (wave 5): `tests/ownership_check.py --lane evolution-persona --worktree` → `ownership OK (10 checked)`
- 2026-10-07 (wave 4): `tests/.venv/bin/python -m pytest brain/evolution/tests -q` → **49 passed in 0.14s**

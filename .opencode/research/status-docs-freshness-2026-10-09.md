# Status-docs freshness pass — 2026-10-09

Scope: `docs/status/*.md` in <repo-root>/raphael (repo per task). Method: evidence-only
corrections appended as `## Current as of 2026-10-09 (integrator freshness pass)` at the END
of each touched file; no body rewrites, no deletions. Nothing staged, nothing committed, nothing pushed.

## Global evidence used across all appends (verified 2026-10-09)

- `git merge-base --is-ancestor agent/<lane> main` → **true for all 10 lanes**
  (router, brain-core, pc-control, voice, computer-use, orb, infra, qa-security,
  tools-memory, evolution-persona). No lane is "waiting to merge".
- **WAVE-5H GATE PASSED** recorded in main at commit `2247a65` (2026-10-08 09:56 -0500,
  "all 5 exit criteria verified"); tag `wave-5h-gate` exists.
- `gh run list` (2026-10-09): latest completed main CI **37800865212** (success,
  2026-10-08T15:27:03Z); gate-pass main run 37796668180 (success); post-gate main pushes
  37797510006 / 37798575215 (success); scheduled tests-heavy sweep **37925272630**
  (success, 2026-10-09T11:41:16Z). Several pushes were `in_progress` at scan time —
  not cited as evidence anywhere.
- `docs/WAVES.md:2` → `current_wave: 5` (line 102: wave 5H runs INSIDE wave 5).
- Post-gate closure commits from git log: `02e98c3` (npm-safetycli-lock → ANSWERED),
  `83652aa` (electron-audit-highs ANSWERED+verified, npm gate tightened back to
  `--audit-level=high`, SCANNERS allowlist retired), `4620775`/`48f74f3` (SEC-1 STRICT
  gate wired into tests-heavy; branch CI 37799170764 success; suite 405),
  `0d20b22` (request-disposition batch, branch CI 37795738095 5/5),
  `cccd26a`/`9784e0c`/`c464f4b` (voice/pc/router straggler-sweep doc records),
  `ccf4a86` (infra post-gate doc record), `96f406c` (orb closure record),
  `7f0b6e8` (brain-core doc record), `9e7c052` (integrator full-night record, 2026-10-09).

## Edits applied (10 files, 84 lines appended, nothing else changed)

### docs/status/brain-core.md (+8 lines)
- Flagged stale: `## In progress — "(Wave-5H packet reported; awaiting review/merge)"` →
  superseded by gate pass 2247a65 + branch merged (ancestor of main).
- Flagged stale: `## Blocked — "ARCH-5 waits on integrator's direction"` → contradicted by
  the doc's own Done line ("ARCH-5 decision received … nothing to code").
- Verified-still-open: `voice__to__brain-core__speak-warn-notices.md` = Status OPEN; no
  `speak_notice` call site in brain/loop.py or brain/ws.py (grep 2026-10-09) — the doc's
  "## Next" item genuinely stands.
- Noted (owner flip pending): `tools-memory__to__brain-core__loop-memory-skills-injection.md`
  still Status OPEN although injection landed (`brain/loop.py:166-193`, `arm_all` at
  `brain/app.py:116-117`); `plugins.load_enabled()` has no brain call site.

### docs/status/computer-use.md (+7 lines)
- Flagged stale: `## Next — "wave_done posted … Waves 3–5 … start only when current_wave
  says so"` → current_wave=5 since 2026-10-07; waves 3/4/5 + 5H executed and closed.
- Noted the Wave-5 "known non-mine" instance-table failure is fixed upstream (already
  acknowledged in the doc's own 5H test block).
- Request closure: `computer-use__to__pc-control__focused-password-flag.md` = Status DONE
  (pc-control implemented 2026-10-08; doc record merged 9784e0c).

### docs/status/evolution-persona.md (+7 lines)
- Flagged stale: `## Blocked — "Full controller … still waits on: infra rollback-hook
  seam, qa-security golden-harness seam + CORE_GUARD_FILES extension, router weights"` →
  controller built and tested (`brain/evolution/controller.py`, quoted in the doc's own
  AUD-26 section with file:line + 19 tests; F-1 ran a real PROPOSE-mode loop);
  CORE_GUARD_FILES extension landed (SEC-7 manifest 4→20). Caveat stated in the append:
  the two non-controller dependencies were not independently re-verified.
- Flagged stale: `## Next — "build worktree.py + controller.py skeleton"` → built.
- Flagged stale: "the 3 most recent main ci.yml runs are RED — flagged for integrator" →
  latest completed main CI runs green (37800865212; tests-heavy sweep 37925272630).

### docs/status/infra.md (+9 lines)
- Flagged stale: SEC-1 row "qa CI request OPEN" → infra implemented OPTION 1 (`8f941d2`),
  qa wired the strict gate same day (`4620775`, CI 37799170764 success, merged `48f74f3`);
  `qa-security__to__infra__personal-scan-strict-severity-scope.md` = DONE;
  `infra__to__qa-security__ci-personal-scan.md` = ANSWERED.
- Flagged stale: "F-7: DRAFT (co-sign pending)" → `infra__to__integrator__f7-readiness-cosign.md`
  = CO-SIGNED (integrator, 2026-10-08).
- Request closure: `infra__to__orb__npm-safetycli-lock.md` = ANSWERED (02e98c3).
- Verified-still-open: `infra__to__integrator__sec5-env-dev-and-docs.md` = OPEN (SEC-5 row
  "PROPOSED (integrator lines pending)" still accurate).
- Flagged stale: "## Next … await review — wave_done on the conductor's call" → gate passed.

### docs/status/pc-control.md (+8 lines)
- Flagged stale: header "Updated: 2026-10-06 (Wave 2 complete)" (body runs through 2026-10-08).
- Flagged stale: top `## Blocked` (live-Brain use awaits brain-core auto-discovery) →
  landed; the doc's own 5H section records "AUD-05 LIVE + MERGED … end-to-end".
- Flagged stale: top `## Next` (waves 3-5 wait on current_wave) → current_wave=5; all
  subsequent waves executed and logged in this very file.
- Verified-still-open: `pc-control__to__integrator__protocol-activity-act.md` = OPEN and
  `pc-control__to__brain-core__activity-endpoint.md` = OPEN (F-3 chain not fully closed).

### docs/status/qa-security.md (+9 lines)
- Flagged stale: header "Updated: 2026-10-07 (Wave 3 open…)".
- Flagged stale: "strict deferred until human scrub" → superseded same day by the
  OPTION-1 strict wiring (4620775, CI 37799170764, suite 405, merged 48f74f3).
- Flagged stale: electron/npm posture → `qa-security__to__orb__electron-audit-highs.md`
  = ANSWERED (83652aa); gate tightened to `--audit-level=high`; allowlist note retired.
- Flagged stale: `## Next — "current_wave: 2 → STOP here"` → current_wave=5; waves 3/4/5
  queue items were completed per this doc's own record.
- Added post-gate closure evidence (0d20b22, 48f74f3 + CI ids).

### docs/status/router.md (+7 lines) — smallest delta; doc was mostly fresh (header 2026-10-08)
- Flagged stale: "loop-label + arch5 + e-budget requests remain with their owners" →
  all three ANSWERED (`router__to__integrator__e-budget-code.md`,
  `router__to__integrator__arch5-router-contribution.md`,
  `router__to__brain-core__chat-purpose-label.md`), plus `router__to__orb__headroom-in-menu.md`
  = ANSWERED (orb side DONE) and `router__to__qa-security__ownership-ci-base.md` = ANSWERED.
- Verified-still-blocked: Wave-2 exit criterion 3 (live "what am I looking at" E2E) — no
  live-run evidence in git log or the request file.
- Verified-still-pending: ARCH-5 presets — `config.yaml:174-177` still only
  `cloud_temp: {}` + `local`; no profiles.cloud/hybrid paste landed.

### docs/status/tools-memory.md (+7 lines)
- Flagged stale (partially): Blocked item "loop-memory-skills-injection (Status OPEN) —
  memory is build-verified but not injected end-to-end" → injection + arm_all landed on
  main (brain/loop.py:166-193; brain/app.py:116-117); file still OPEN (flip pending);
  `plugins.load_enabled()` still unwired — so partially stale, precisely scoped in the append.
- Flagged stale: "## Next — wave_done stands for merge position 9 / idle until pinged" → merged.
- Verified-open: `tools-memory__to__integrator__ownership-acquis-typo.md` and
  `tools-memory__to__integrator__progress-md-rebase-conflict.md` both still Status OPEN;
  `tools-memory__to__qa-security__instance-count-12.md` = ANSWERED.

### docs/status/voice.md (+13 lines — largest append, most stale claims)
- Flagged stale: header "Updated: 2026-10-06 (Wave 2 complete …)" (body runs through 2026-10-08).
- Flagged stale: Blocked item `voice__to__integrator__audio-end-pass-reason.md` "(OPEN …
  currently fails open)" → file Status DONE (2026-10-06); SEC-3 fail-closed work superseded it.
- Flagged stale: "## Next: current_wave: 2" → current_wave=5.
- Flagged 4 requests still Status OPEN in their files whose implementation HAS landed
  (owner flip pending), each with code evidence: stt-outage-subtitle (brain/ws.py:874,947,958),
  utt-continuation-merge (brain/ws.py:765-766), streamed-sentence-batching
  (brain/loop.py:294-299), turbo-stt-for-purpose-transcribe (router Cut B record +
  roles.py:35 / config.d/router.yaml:12).
- Verified-still-open: `voice__to__brain-core__voice-confirm-wiring.md` (file OPEN) and
  `voice__to__brain-core__speak-warn-notices.md` (OPEN + no call site in brain).

### docs/status/orb.md (+9 lines)
- Flagged stale: header "Updated: 2026-10-06" (body runs through 2026-10-08).
- Flagged stale: the "BLUE PARTICLES" section's "on origin/main? NO — 48da3dd … never been
  merged … nothing has shipped since b0ed6ce. Fix = post wave_done → merge" → agent/orb is
  an ancestor of main; everything in that batch shipped; gate passed.
- Request closure: `qa-security__to__orb__electron-audit-highs.md` = ANSWERED (83652aa) —
  the doc's "ball is in qa's court" item #4 is complete.
- Confirmed accurate: `infra__to__orb__npm-safetycli-lock.md` = ANSWERED (matches doc).
- Verified-still-open: `orb__to__brain-core__orb-state-transitions.md` and
  `orb__to__integrator__backing-disc-default-zero.md` both OPEN — doc statements remain correct.

## Findings NOT fixed (with why)

1. **docs/status/integrator.md — NOT touched (flag only).** Body is bootstrap-era
   ("Updated: 2026-10-05 (bootstrap — not started)", "Next: Wave 2 task 1") and plainly
   stale vs git evidence (the integrator authored the gate record 2247a65 and dozens of
   merges, latest 9e7c052 on 2026-10-09; the file has not been modified since the bootstrap
   commit fbb1997). NOT fixed because "integrator" is not in the assigned lane list —
   decision left to the reviewer who owns that doc.
2. **Duplicate section headers inside docs/status/tools-memory.md** (e.g. the "Addenda batch"
   and "Wave 5H — audit packet" headings each appear twice, lines ~24/26, ~96/98, ~144/146,
   ~210/212, ~224/226). Cosmetic duplication, not a factual staleness — left alone per the
   "prefer appending, don't rewrite the body" rule.
3. **evolution-persona dependency sub-items** (infra rollback-hook seam; router weights
   ownership) — not independently verified whether each individually remains open; the append
   scopes its correction to what is provable (controller built; CORE_GUARD_FILES extension landed).
4. **Requests "landed but file still OPEN"** (stt-outage-subtitle, utt-continuation-merge,
   streamed-sentence-batching, turbo-stt, loop-memory-skills-injection) — the flips belong to
   the request owners per ownership rules; docs only record the discrepancy, files untouched.
5. **Live-E2E blocked items** (router wave-2 criterion 3; computer-use live-run checklist;
   voice pending-fish acceptance re-run) — no evidence any live run happened; left as
   genuinely blocked, explicitly re-affirmed rather than removed.
6. **In-progress CI runs at scan time** (several pushes `in_progress` in `gh run list`) — not
   cited as current-state evidence anywhere; only completed runs referenced.
7. **pc-control "branch CI dispatched on the final head"** (no CI id recorded by the lane) —
   cannot cite an id without inventing one; the append cites the merged-branch/gate evidence instead.

## Verification

- `python3 scripts/scan_personal.py` → "scanned 873 tracked files … 55 finding(s)
  (FAIL-severity: 0, non-ledger)", exit 0. All 55 are pre-existing REVIEW-severity
  voice-clip/ip-private findings; none on the appended lines (appends contain only
  repo-relative paths, commit hashes, CI run ids, and request filenames — no personal literals).
- `git status --porcelain docs/status/` → 10 modified files, unstaged; `git diff --stat`
  = 84 insertions, 0 deletions. Stage nothing; reviewer commits + pushes.

# qa-security — lane task list (owner: qa-security lane)

Read: docs/AGENT_RULES.md -> docs/WAVES.md -> this file. Status log: docs/status/qa-security.md. Requests to you: `ls docs/requests/*__to__qa-security__*.md`.

Merge-order position: see docs/WAVES.md

## Wave 2 tasks (docs/WAVES.md (current_wave: 2))
- [x] Mock harness: fake providers (groq/zen shapes per INTERFACES §a), fake brain, fake TTS/STT — no network/keys/GPU.  (`tests/harness/`, 2026-10-06)
- [x] Contract tests: config merge (§c), instance derivation (§d), orb_state emission (§e), tool-spec validation (§b).  (`tests/contract/` + `tests/regression/`; §c/§d are xfail tripwires with requests — implementation missing)
- [x] Ownership checker: lane diff vs docs/OWNERSHIP.md violations => fail (integrator runs it in the merge loop).  (`tests/ownership_check.py` + 45 unit tests; CI runs it per-diff)
- [x] Security regressions: Core Guard byte-stable unless integrator-approved, no secrets in logs/output, localhost+token intact.  (`tests/security/`, `tests/core_guard.py` + manifest)
- [x] CI workflow (.github/workflows) running the mock suites — secrets never required.  (`.github/workflows/ci.yml`: ubuntu brain+mocks / windows body-unit)

### Session-brief extras (Wave 2)
- [x] Contract tests: auth, rate limits, role capabilities, binary frames, error codes.
- [x] Regressions: no placeholder replies; orb_state lifecycle; confirmation flow (timeout aborts, per-job grants, high-risk needs non-voice); Private Mode zero cloud calls; redaction; instance isolation (two instances); cloud_temp never starts Ollama.
- [x] `tests/run_all` entry points (bash + ps1) + CI jobs.
- [x] Security review → docs/reviews/2026-10-06-wave2.md + 22 per-finding requests to owning lanes.

## Wave 3 (start only when WAVES.md says so — current_wave: 3)

Wave 2 is MERGED; live gate was 3/5 — evidence + bug dossiers: `docs/BUGS-WAVE2.md`. SPEED MANDATE: cloud is paid now — near-instant responses, fast model defaults (AGENT_RULES Rule 15, WAVES.md constraints).

- [P0-REGRESSIONS] Land tests for the gate bugs: (1) go_vision requests always carry `x-opencode-session` (Bug A); (2) no `listening` between sentences in an orb_state speak sequence (Bug E, with brain-core); (3) `open_app` failure always surfaces act_res + spoken subtitle (Bug B); (4) foreground=non-blocklisted terminal never refuses vision (Bug F). Wave-3 close = re-run ALL six WAVES criteria live (status table in docs/BUGS-WAVE2.md).
- [FLAKE] `tests/contract/test_binary_frames.py::test_kind1_mic_pcm_accumulates_and_transcribes` failed once in a full 757-test run (2026-10-07) but passes in isolation — order-dependent state leak; isolate + quarantine.
- [SPEED] Suites stay mock-fast (Rule 15).

## Wave 4 (start only when WAVES.md says so — current_wave: 4)

Wave 3 is MERGED + **GATE PASSED** (tag `wave-3-gate`, all six criteria live, acoustic voice included). Wave-4 theme per WAVES.md: hardening, resilience tests, audit fixes, crash recovery, evolution infrastructure. Rule 15 speed mandate still binds.

- [x] Orchestrate the wave-4 resilience matrix (owns the suite): kill/recovery drills green across brain/body/orb/supervisor, audit-fix verification passes, secret/redaction re-audit, encoding-class regression guard in CI matrix.  (2026-10-07: `tests/resilience/` provider-storm+recovery + crash-recovery interrupted drills; §b/429/orb/vision/ollama/loopback fixes verified strict; matrix + re-review in `docs/reviews/2026-10-07-wave4.md`; full-brain import-hygiene CI step added)

## Wave 5 (start only when WAVES.md says so — current_wave: 5)

Wave 4 is MERGED + **GATE PASSED** (tag `wave-4-gate`, 10/10 lanes, mock 308 green). Wave-5 theme per WAVES.md: Raphael features — Answer/Notice/Report formats, Analysis, Simulation, parallel-minds visuals, persona tiers. Rule 15 speed mandate binds; shared-contract changes go through integrator requests. Carried items are noted in WAVES.md gate record (shadow row; C1+C2 residual).

- [x] Wave-5 gate tests: format contract conformance (new frames vs §3), tier-switch safety (deep-merge cannot touch safety/privacy/providers — extend evolution's 14 tests), Analysis/Simulation privacy tripwires.  (2026-10-07: production-emitter ⊆ §3 scan strict; tier safety = per-TIERS authority property STRICT + adversarial-fragment xfail with loader-authority-guard request; Analysis/Sim tripwire armed — skip-until-lands, fails-if-ungated — with analysis-simulation-privacy-contract request filed)

## Wave 5H — audit hardening sprint (inside wave 5; gate `wave-5h-gate`)

- [x] **QA-1** DONE — `.gitleaks.toml` (custom user/path/IP rules, HEAD-scope+baseline), `ci.yml` job `security-scanners` (gitleaks/secret-scan/pip-audit/bandit/npm) + `.github/dependabot.yml`; gates green in CI run 37775644704; suppressions documented `tests/security/SCANNERS.md` + `tests/security/bandit.yaml`.
- [x] **QA-2** DONE — `tests/fuzz/test_property_fuzz.py` (7 seeded tests: confirm totality/fail-closed, wake injection, frame fuzz, act_res fuzz+replay, auth replay) + `tests/harness/fuzz.py`.
- [~] **QA-3** PARTIAL — golden transcripts DONE: `tests/golden/` (3 recorded transcripts + replay-vs-fresh-instance test 4/4 + `GOLDEN_RECORD=1` recorder); REMAINING: nightly cron sweep + the eval layer (persona format, tool-call accuracy vs recorded fixtures).
- [x] **QA-4** DONE — `tests/wave_done_lint.py` (+`tests/test_wave_done_lint.py`, 10 tests); accepted wave_done carried ci_run 37775644704; schema adopted by integrator.
- [x] **SEC-7 CI side** DONE — SHA-pinned actions + `permissions: contents:read` + `persist-credentials:false` in `ci.yml`/`tests-heavy.yml`, enforced by `tests/security/test_workflow_integrity.py`; branch-protection ATTENTION posted (human half).
- [ ] **control-plane re-audit** (brief item 6): `docs/reviews/<date>-wave5h.md` + requests — NOT started.
- [ ] Read `docs/audit-tasks/qa-security.md` → your IDs: **QA-1, QA-2, QA-3, QA-4, SEC-7** — VERIFY-FIRST (verbatim file:line, then CONFIRMED / NOT-APPLICABLE / ALREADY-DONE), QA-4: link a green CI run with your wave_done. Source register + dedupe: `docs/AUDIT-2026-10-07.md`. Rules: stack down (spawn only for your test), one suite at a time, heavy suites in cloud (`gh workflow run tests-heavy.yml`), Rule 15 speed, cost not a factor.

## Later waves (do not start early — AGENT_RULES §11; beyond current_wave 3)
- [ ] Wave 3: golden job transcripts (replayable recorded conversations/tool traces as regression baseline).
- [x] Wave 4: resilience test suites (with infra) + security re-review after fixes.  (`tests/resilience/` 3 drills green + `docs/reviews/2026-10-07-wave4.md`; matrix orchestration bullet above)
- [ ] Wave 5: evolution gate tests (Core Guard integrity, rollback, probation triggers).

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

- [ ] Orchestrate the wave-4 resilience matrix (owns the suite): kill/recovery drills green across brain/body/orb/supervisor, audit-fix verification passes, secret/redaction re-audit, encoding-class regression guard in CI matrix.

## Later waves (do not start early — AGENT_RULES §11; beyond current_wave 3)
- [ ] Wave 3: golden job transcripts (replayable recorded conversations/tool traces as regression baseline).
- [ ] Wave 4: resilience test suites (with infra) + security re-review after fixes.
- [ ] Wave 5: evolution gate tests (Core Guard integrity, rollback, probation triggers).

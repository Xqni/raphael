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

## Later waves (do not start early — AGENT_RULES §11; WAVES.md current_wave still 2)
- [ ] Wave 3: golden job transcripts (replayable recorded conversations/tool traces as regression baseline).
- [ ] Wave 4: resilience test suites (with infra) + security re-review after fixes.
- [ ] Wave 5: evolution gate tests (Core Guard integrity, rollback, probation triggers).

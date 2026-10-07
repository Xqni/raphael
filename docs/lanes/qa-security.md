# qa-security — lane task list (owner: qa-security lane)

Read: docs/AGENT_RULES.md -> docs/WAVES.md -> this file. Status log: docs/status/qa-security.md. Requests to you: `ls docs/requests/*__to__qa-security__*.md`.

Merge-order position: see docs/WAVES.md

## Wave 2 tasks (docs/WAVES.md (current_wave: 2))
- [ ] Mock harness: fake providers (groq/zen shapes per INTERFACES §a), fake brain, fake TTS/STT — no network/keys/GPU.
- [ ] Contract tests: config merge (§c), instance derivation (§d), orb_state emission (§e), tool-spec validation (§b).
- [ ] Ownership checker: lane diff vs docs/OWNERSHIP.md violations => fail (integrator runs it in the merge loop).
- [ ] Security regressions: Core Guard byte-stable unless integrator-approved, no secrets in logs/output, localhost+token intact.
- [ ] CI workflow (.github/workflows) running the mock suites — secrets never required.

## Later waves
- Per docs/WAVES.md — do not start early (AGENT_RULES §11).

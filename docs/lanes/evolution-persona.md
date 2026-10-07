# evolution-persona — lane task list (owner: evolution-persona lane)

Read: docs/AGENT_RULES.md -> docs/WAVES.md -> this file. Status log: docs/status/evolution-persona.md. Requests to you: `ls docs/requests/*__to__evolution-persona__*.md`.

Merge-order position: see docs/WAVES.md

## Wave 2 tasks (docs/WAVES.md (current_wave: 2))
- [x] Wave 2 has no exit-criteria tasks for this lane: write docs/evolution/ design notes (shadow instance, rollback, journal — Wave 4) + persona tier design (great_sage->raphael->ciel — Wave 5). Done 2026-10-05: `docs/evolution/01-self-evolution-infra.md` + `docs/evolution/02-persona-tiers.md` + request `evolution-persona__to__brain-core__shadow-instance-row.md`.
- [ ] Then: WAIT for current_wave to bump (AGENT_RULES §11) — check requests addressed to evolution-persona meanwhile.

## Wave 3 (start only when WAVES.md says so — current_wave: 3)

Wave 2 is MERGED; live gate was 3/5 — evidence + bug dossiers: `docs/BUGS-WAVE2.md`. SPEED MANDATE: cloud is paid now — near-instant responses, fast model defaults (AGENT_RULES Rule 15, WAVES.md constraints).

- [CONTEXT] Wave 2 merged; live gate 3/5 — gate bugs assigned in docs/BUGS-WAVE2.md (P0s belong to other lanes). Your wave-3 goals below stand.
- [SPEED] Persona responses stay fast cloud defaults (Rule 15).
- [x] Wave 3 lane task: refresh `docs/evolution/` design notes against the merged Wave 2 reality —
  (a) `01`: adopt qa-security's `tests/core_guard.py` + `tests/core_guard_manifest.json` as THE single
  Core Guard manifest (controller calls it, never forks one); dependency table updated (shadow row still
  OPEN and now hard-blocked by `brain/config.py` loud failure; requests queued for qa-security/infra/router
  at Wave 4 start); (b) `02`: Notice format aligned to brain-core's concrete `notice` frame proposal,
  caps tied to existing `voice_personality` keys, tier switch settled on config.d deep-merge (no
  shared-file edits). Verified: `python3 tests/core_guard.py` → "Core Guard OK (4 files byte-stable)".
- [ ] Wait for next coord ping (mode: exit) — check `docs/requests/*__to__evolution-persona__*.md` at task start.

## Later waves
- Per docs/WAVES.md — do not start early (AGENT_RULES §11).

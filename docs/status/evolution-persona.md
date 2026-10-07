# evolution-persona — status

Updated: 2026-10-07 (Wave 3)

## Done
- Wave 2 (2026-10-05): design notes `docs/evolution/01-self-evolution-infra.md` (Wave 4 infra) +
  `02-persona-tiers.md` (Wave 5) + request `evolution-persona__to__brain-core__shadow-instance-row.md`.
- Coord adoption (2026-10-06): heartbeat posted, lane hold taken, rule 13 (coord post every
  task/test/wave) + mode `exit` adopted.
- Wave 3 (2026-10-07): rebased onto merged main (3fab0a6) and refreshed both design notes:
  - `01`: THE manifest is now qa-security's `tests/core_guard.py` + `tests/core_guard_manifest.json`
    (4 core files) — the evolution controller verifies through it instead of keeping a second copy;
    §7 dependency table rewritten with statuses (shadow row request OPEN and now hard-blocked by
    `brain/config.py::_instance_index` failing loudly for unknown instances — correct fail-closed
    behavior); queued Wave-4 requests: extend CORE_GUARD_FILES (qa-security), rollback hook seam (infra),
    golden-harness seam (qa-security; `tests/{run_all,harness,conformance,contract}` exist to reuse),
    router weights ownership (router).
  - `02`: Notice format now anchors on brain-core's concrete `notice` frame proposal
    (`docs/requests/brain-core__to__integrator__notice-events.md`, OPEN) — no competing frame; spoken
    caps read existing `voice_personality.spoken_reply_max_sentences` / `proactive_warnings`; tier
    switch mechanism settled = `config.d/evolution-persona.yaml` deep-merge overlay per tier over
    `voice_personality` (integrator's `config.yaml` untouched; `great_sage` changes nothing).
  - No P0 gate bugs assigned to this lane (docs/BUGS-WAVE2.md has no evolution/persona items).

## In progress
- —

## Blocked
- Wave 4 code still gated by AGENT_RULES §11 (current_wave: 3; wave-4 goals are not yet due).
- `shadow` instance row (my OPEN request to brain-core) will hard-block shadow-instance runs when
  Wave 4 starts — no workaround planned (never hardcode ports, INTERFACES (d)).

## Next
- On next coord ping: re-check `docs/requests/*__to__evolution-persona__*.md` + status of my shadow
  request; at Wave 4 start write the four queued dependency requests from `01` §7.

## Test output (real runs only — never claim unrun tests)
- 2026-10-07: `python3 tests/core_guard.py` → `Core Guard OK (4 files byte-stable)` (exit 0).
- (no other tests run this wave — documentation/design task only)

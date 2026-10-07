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

## Wave 4 (start only when WAVES.md says so — current_wave: 4)

Wave 3 is MERGED + **GATE PASSED** (tag `wave-3-gate`, all six criteria live, acoustic voice included). Wave-4 theme per WAVES.md: hardening, resilience tests, audit fixes, crash recovery, evolution infrastructure. Rule 15 speed mandate still binds.

- [PARTIAL] Evolution infra (WAVES wave-4): shadow-instance REQUEST resolution with brain-core (currently OPEN), rollback design + journal design notes -> implementation spikes (docs/evolution), persona tier switch deep-merge test plan.
  - [x] Shadow resolution step done (2026-10-07): coord `request` event posted to brain-core with ref to
    `docs/requests/evolution-persona__to__brain-core__shadow-instance-row.md`; still **OPEN** → `shadow.py`/
    `baseline.py` cannot be built until the row lands (config.py raises for unknown instances). Blocked-on-others,
    not on me.
  - [x] Journal + rollback implementation spikes: `brain/evolution/{zones,journal,rollback}.py` + tests —
    49 passed; core guard exit 0; ownership check OK (11 files). Notes: `docs/evolution/03-wave4-spikes.md`.
  - [x] Persona tier switch deep-merge test plan: `docs/evolution/04-tier-switch-test-plan.md` +
    `brain/persona/tests/test_tier_switch.py` (14 passed) + lane fragment `config.d/evolution-persona.yaml`
    (default `persona.tier: great_sage`, `evolution.mode: propose`).
- [x] **Wave 4 WAVE_DONE posted 2026-10-07** (final merge position 10/10; conductor-verified spikes
  3f1afe8+9a01774). Shadow request APPROVED + assigned to brain-core; shadow verification runs
  (`shadow.py`/`baseline.py` + controller) **carried into Wave 5** — note it at wave-5 start.
- [ ] Wait for next coord ping (mode: exit) — at task start: `ls docs/requests/*__to__evolution-persona__*.md`.

## Wave 5 (start only when WAVES.md says so — current_wave: 5)

Wave 4 is MERGED + **GATE PASSED** (tag `wave-4-gate`, 10/10 lanes, mock 308 green). Wave-5 theme per WAVES.md: Raphael features — Answer/Notice/Report formats, Analysis, Simulation, parallel-minds visuals, persona tiers. Rule 15 speed mandate binds; shared-contract changes go through integrator requests. Carried items are noted in WAVES.md gate record (shadow row; C1+C2 residual).

- [x] PERSONA TIER IMPLEMENTATION (primary) — DONE 2026-10-07: deny-by-default proactive zones +
  unlock-criteria evaluator + probation lifecycle with automatic demotion (line-scoped `tier:` edit);
  `brain/persona/{tiers,probation}.py`, 56 tests green, core guard OK. Notes: docs/evolution/05-tier-probation-impl.md.
  - [x] Shadow verification (Wave-4 carry-over) — DONE 2026-10-07: `brain/evolution/{shadow,baseline}.py`,
    real derivation check (shadow/8911) + real subprocess pytest under RAPHAEL_INSTANCE=shadow, fail-closed
    promote compare (shadow/core-guard/transcript deltas; commit move alone passes); seed golden
    `brain/evolution/golden/open-youtube.json`. 63 tests green. Notes: docs/evolution/03-wave4-spikes.md § What landed (shadow/baseline).
- [x] Wave-5 leftovers needing shared contracts (request FIRST) — REQUESTS FILED 2026-10-07 + coord
  `request` event posted: `evolution-persona__to__integrator__task-kind-analysis-simulation.md`,
  `evolution-persona__to__integrator__orb-state-minds-field.md`,
  `evolution-persona__to__voice__ciel-voice-reference-slot.md`,
  `evolution-persona__to__orb__ciel-gold-palette.md`. Implementation of these four waits for owners'
  decisions (per requests/README workflow).
- [x] Answer/Notice/Report formats (own paths, no new frame needed) — DONE 2026-10-07:
  `brain/persona/formats.py` deterministic classifier (question→Answer, proactive→Notice,
  job_done+analysis/simulation/digest class→Report, else/degenerate→Answer), per-format sentence caps
  from `voice_personality`, full detail on screen, private suppresses screen, never raises.
  77 persona tests green. 
- [x] **Wave 5 WAVE_DONE posted 2026-10-07** (final merge position 10). Integrator decisions on both
  integrator contracts: **minds[] APPROVED as proposed**; **task_kind analysis|simulation + shape_map
  APPROVED** (analysis:octagram, simulation:triangle added to config.yaml by integrator; job-type
  engine implementation assigned to brain-core). Voice Ciel-slot + orb palette requests forwarded to
  owners. Formats already key on the approved enum values.
- [ ] Wait for next coord ping (mode: exit) — at task start: `ls docs/requests/*__to__evolution-persona__*.md`.

## Later waves
- Per docs/WAVES.md — do not start early (AGENT_RULES §11).

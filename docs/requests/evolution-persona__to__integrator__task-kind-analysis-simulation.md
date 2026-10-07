# evolution-persona → integrator: additive `task_kind` values `analysis` / `simulation`
Status: OPEN

## What
Extend the `task_kind` vocabulary additively (PROTOCOL §8 + INTERFACES §e):

- `task_kind: system|files|web|media|llm|gui|none` → add **`analysis`** and **`simulation`**;
- `config.yaml → orb.shape_map` gains two entries. Our proposal: **`analysis: octagram`**
  (shares the reasoning signature with `llm`) and **`simulation: triangle`** (shares the
  system/rehearsal family) — reuse is fine, the orb only needs a distinct morph target per
  class; the orb lane owns the final visual choice (any two valid, distinct-or-shared shapes
  are acceptable to us);
- job engine (brain-core) accepts two job *types*:
  - **Analysis** — read-only deep pass (files/logs/memory/web), `priority: background`,
    `lock: false`, output = Report format, side effects limited to the memory store;
  - **Simulation** — sandboxed dry-run against the Wave-4 shadow/mock harness, `lock: false`,
    NEVER the real input path, output = predicted `act_req` stream + Report.

The frames themselves are unchanged (`job_event` already carries `task_kind`); this is an
enum-value addition plus two job-type behaviors.

## Why
Wave 5 goal (WAVES.md: "Analysis, Simulation") + `docs/evolution/02-persona-tiers.md` §4.
Persona-side formatting (`brain/persona/formats.py`) already treats `analysis`/`simulation`
as Report-class and needs the real values to key on.

## Impact
Purely additive: unknown `task_kind` already falls back to `shape_map` default (`circle`),
so old clients/orbs are unaffected. **No Core Guard semantics touched.** Needs your decision
on: enum values, final shape_map entries, and whether brain-core (jobs) implements the two
types in the same pass (we propose: yes, brain-core for job types, orb for shapes).

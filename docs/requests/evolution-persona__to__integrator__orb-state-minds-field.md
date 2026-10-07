# evolution-persona → integrator: optional `minds[]` field on `orb_state` (parallel-minds)
Status: OPEN

## What
Add ONE optional field to the `orb_state` frame (PROTOCOL §8 / INTERFACES §e):

```json
{"type":"orb_state", ..., "minds": [
  {"job":"j_20261007_001","task_kind":"analysis","stage":"llm"},
  {"job":"j_20261007_002","task_kind":"files","stage":"tool"}
]}
```

- **optional** — absent means "no summary" → orb renders its existing `jobs_active` dots only
  (backward/forward compatible; the orb only renders what it recognizes);
- capped at 9 entries (matches the existing `jobs_active` display cap);
- server-authored from data the Brain already emits per job (`task_kind`, `stage`); **no new
  state** — `orb_state` remains the single state authority and private/paused stay `mode`
  overlays;
- `minds` is a status summary for the parallel-minds visualization (WAVES wave 5); levels of
  detail beyond this frame are the orb lane's rendering choice.

## Why
Wave 5 goal "parallel-minds visuals" (`docs/evolution/02-persona-tiers.md` §5.1). It is the
only contract piece; the renderer belongs to orb and the job data already exists in
brain-core — hence your file first (rule: new frames/contracts = integrator request FIRST).

## Impact
Additive optional field; qa-security's conformance whitelist needs the new optional key
flagged (their file — noted so the decision lands once). No Core Guard change, no state
machine change, no extra cost per frame beyond 2 short strings per active job.

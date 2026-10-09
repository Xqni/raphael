# brain-core → integrator: Wave-5 output formats + job kinds + fan-out correlation

From: brain-core lane. Date: 2026-10-07. Status: OPEN (Wave-5 lane task: "extend the
contract for Report/Answer shapes via integrator request FIRST").

## What (all additive; Notice stays as approved in Wave 3)

### 1. `answer` frame (Brain → ui+cli)
```json
{"type": "answer", "v": 1, "job": "j_…", "text": "2+2 is 4.",
 "provider": "groq", "model": "…", "format": "answer"}
```
Emitted ONCE per conversational final reply (alongside the existing subtitle/speak,
which stay unchanged). Lets the orb/CLI distinguish THE answer from narration/transient
text. `provider`/`model` only when the reply came from the router.

### 2. `report` frame (Brain → ui+cli)
```json
{"type": "report", "v": 1, "job": "j_…", "title": "Disk usage analysis",
 "summary": "3 findings.", "sections": [{"heading": "/", "text": "82% full"}],
 "format": "report"}
```
For Analysis results and anything long-form (spoken reply stays ≤2 sentences per
persona; the report is the on-screen artifact). `sections` capped (e.g. ≤10, text
trimmed server-side). Still NOT an orb state (INTERFACES §e untouched).

### 3. Job kinds (request + event, additive fields)
- `POST /jobs` and WS `command` gain OPTIONAL `kind`: `"chat" | "analysis" |
  "simulation" | "act"` (default `chat` — zero change when absent).
- `job_event` gains OPTIONAL `kind` (echoes the job's kind) so subscribers can
  style Analysis/Simulation differently.
- Semantics brain-core will enforce:
  - **simulation**: never executes side effects — the agent loop runs with
    `tools=[]` and no prompt-block; fastpath deterministic intents still allowed;
    confirm gate still applies to its text.
  - **analysis**: read-only intent — same confirm rules as today (nothing weakened);
    eligible for the parallel fan-out below.
  - `chat`/`act`: today's behavior exactly.

### 4. Parallel-minds fan-out correlation (additive)
- submit/command gain OPTIONAL `parent` (external job id) — a child job created by
  a fan-out helper; `job_event` echoes `parent` when present.
- brain-core ships `engine.submit_fanout(...)` (create N children for one parent,
  priority/source inherited) — the orb's parallel-minds visuals key off N active jobs
  + the `parent` tag; no new frame type needed beyond the echo field.

## Why
WAVES Wave 5 = "Answer/Notice/Report formats, Analysis, Simulation, parallel-minds".
Notice already exists (§3, wave 3); Answer/Report shapes and the kind/parent fields
are the missing contract. Without it the emitters cannot ship (lane rule: new
frames/contracts = integrator request FIRST).

## Impact
Purely additive fields/frame types; existing consumers ignore unknown types (they
already filter by `type`). qa conformance whitelist needs the two new rows + field
notes. Core Guard untouched (simulation REDUCES capability: tools off). Roles:
`answer`/`report` → ui+cli (body keeps speak/subtitle as today).

## Proposed defaults if you accept as-is
- caps: report `sections ≤ 10`, `summary ≤ 500`, per-section `text ≤ 2000`;
- `answer` suppressed for fastpath one-liners? — NO: emit for every final reply
  (uniform; consumers may dedupe by job).

## Status update (integrator freshness pass 2026-10-09)
ANSWERED/DONE — evidence: all four items landed. `docs/PROTOCOL.md:57` (`answer` row, "additive 2026-10-07, integrator-approved"), `docs/PROTOCOL.md:58` (`report` row with the proposed caps ≤10 sections/≤500 summary/≤2000 text), `docs/PROTOCOL.md:55` (`job_event` optional `kind` + `parent`, "kind/parent additive 2026-10-07 integrator-approved"). Engine side: `brain/jobs/engine.py:185` `KINDS = ('chat', 'analysis', 'simulation', 'act')` and `engine.py:213` `async def submit_fanout(...)`, regression-tested by `brain/tests/test_job_concurrency.py:346` `test_submit_fanout_correlates_children`.

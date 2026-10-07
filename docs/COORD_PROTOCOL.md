# COORD_PROTOCOL.md — the file-based coordination bus (integrator-owned)

Replaces manual message relaying between lane sessions. Two halves: a **file bus** (`coord`
CLI) everyone writes/reads, and a **non-LLM conductor** that watches the bus and wakes the
right session. Lanes never poll when the conductor is up. Last verified: 2026-10-06,
opencode v2.0.22.

## Layout — `~/.raphael-coord/` (OUTSIDE git, shared by every worktree)

| Path | Writers | Purpose |
|---|---|---|
| `bin/coord` | (symlink) | the CLI below — always the repo's `tools/conductor/coord.py` |
| `events/<lane>.jsonl` | that lane (+ conductor) | lane → integrator, append-only |
| `inbox/<lane>.jsonl` | integrator/conductor | integrator → lane; `<lane>.read` = lane's read cursor |
| `inbox/integrator.jsonl` | conductor | wake notices for fallback integrator sessions |
| `state.json` | integrator + conductor only | wave, per-lane status/heartbeat/session/branch_head/failures, event cursors — always flock-guarded |
| `locks/<lane>.lock` | lane holds it | long-held activity flock (session lifetime); headless launches must skip held lanes |
| `locks/write.lock`, `state.lock` | short critical sections | every append / state write |
| `ATTENTION.md` | anyone via `coord attention` | items for the human |
| `logs/` | conductor | `conductor.log`, `runs.jsonl` (launch/exit + durations), `launches.dryrun.jsonl`, `conductor.pid` |
| `STOP` | the human / `conductor stop` | kill switch: conductor launches nothing and exits cleanly |
| `conductor.yaml` | integrator | conductor config (JSON syntax = valid YAML 1.2; json.load, stdlib) |
| `prompts/` | integrator | `integrator_event.md`, `lane_continue.md`, `lane_adopt.md` (copied from repo) |

Envelope — one JSON object per line:
`{"ts", "lane", "type", "wave", "ref", "msg", "data"}`.
Event types: `heartbeat task_done wave_done blocked request test_result error user_attention`.
Inbox types: `decision answer wave_open nudge pause`.
Appends are single `O_APPEND` writes under `flock(locks/write.lock)` — atomic per line.

## CLI (exact usage)

```bash
C=~/.raphael-coord/bin/coord
$C init                                        # create/refresh layout (integrator)
$C post   --lane router --type task_done --msg "..." [--ref path] [--data '{"k":v}']
$C reply  --lane voice --type decision --msg "decision: merged <sha>"   # integrator→inbox
$C inbox  --lane voice [--unread] [--mark-read] [--json]
$C status [--json]        # wave, conductor running?, per-lane heartbeat/pending/lock/session
$C wave                   # print current_wave
$C wave-bump --wave 3     # integrator handler only
$C mode   --lane router   # "exit" = conductor up, you'll be pinged (end your turn);
                          # "wait" = conductor down, poll with coord wait (long timeouts)
$C wait   --lane router --for wave|inbox --timeout 300   # exit 0 change, 1 timeout
$C cursor --lane router [--set N]            # advance integrator's event cursor
$C ping   --lane router --msg "..." [--delivery steer|queue]   # wake via API injection
$C session-register --lane router --session-id ses_...
$C sessions [--json]      # sessions mapped to lanes by worktree directory (rename-proof)
$C hold   --lane router   # take the activity lock (session lifetime)  |  $C release
$C attention "text"       # append ATTENTION.md + toast
$C notify  "text"         # Windows toast (powershell.exe, base64 text, no extra modules);
                          # fallback: terminal bell + ATTENTION.md
```

## Wake model (verified — no wait loops by default)

**Ping (primary):** `POST /api/session/{sid}/prompt` through
`opencode api post /api/session/{sid}/prompt --data '{"text":"...","delivery":"steer"}'`.
Verified live: idle sessions wake in ~2–5 s with context intact; busy sessions admit the
message (processed in order, no 409 observed); `delivery:"queue"` also available. Idle
sessions cost **zero tokens**; a ping costs one wake turn. Raw `curl` gets 401 — always go
through `opencode api`. Research: `.opencode/research/session-ping-delegation.md`.

**Session identity:** `location.directory` from `GET /api/session` maps to the lane
(`~/raphael-wt/<lane>`) — titles are display-only (the user renames freely). Lanes also
self-register via heartbeat: `--data '{"session_id":"'$OPENCODE_SESSION_ID'"}'`.

**Headless fallback (only when a lane has no session):** `opencode run` in its worktree with
`prompts/lane_continue.md`, only if the lane lock is free.

**Wait loops (fallback only, conductor down):** `coord wait --for inbox --timeout 300` —
long timeouts to limit token burn. `coord mode` tells a lane which regime is active.

## Verified opencode flags (v2.0.22 — recorded, not assumed)

- `opencode run [flags] [<message...>]`: `--auto` (auto-approve permissions not explicitly
  denied; without it an `ask` rule would block headless), `--agent`, `--model provider/model`,
  `--session/-s`, `--continue/-c`, `--fork`, `--format json|default` (JSON = JSONL events),
  `--file/-f <prompt-file>`, `--title`, `--standalone`, `--server`. **Fresh run = omit
  `-s/-c`** (conductor's integrator runs are fresh each time — files are the memory).
  Working directory = cwd (project discovery).
- `opencode serve --hostname --port --cors --service --stdio` (v2 API + web server).
  **No `attach` subcommand exists** in v2.0.22 — connect with `--server <url>` or `opencode
  api` against the running service (`opencode service status` → URL).
- `opencode api get|post <path> [--data json]` — authenticated against the background
  service. Endpoints used: `GET /api/session`, `GET /api/session/active`,
  `POST /api/session/{sid}/prompt`.
- Permissions: ordered rules, last match wins; default base policy allows `*` with
  `external_directory`/`*.env` = ask; `deny` is never overridden. `opencode session delete <id>`
  for cleanup.
- Every agent process has `OPENCODE_SESSION_ID` in its environment.

## Conductor (`tools/conductor/conductor.py`)

```bash
python3 tools/conductor/conductor.py start [--dry-run] [--tick N]   # tmux session raphael-conductor
python3 tools/conductor/conductor.py stop                            # arms STOP + kills tmux + SIGTERMs children
python3 tools/conductor/conductor.py status
python3 tools/conductor/conductor.py pause <lane> | resume <lane>
```

Loop (default `tick_s: 15`): STOP → debounced integrator wake — **ping into the registered
integrator session** (idle at zero cost, context kept, one wake per 60–90 s batch; fresh
`opencode run` with `prompts/integrator_event.md` only as fallback when no session exists;
skipped while a run is active) → wave-open detection (ping
eligible lanes: not paused, `wave >= start_conditions[lane].min_wave`, backoff clear) →
concurrency cap `max_parallel_runs` (default 3; priority infra/router/brain-core > rest;
queue the rest) → failure handling (per-run timeout 2700 s; consecutive failures ≥ 3 → lane
paused + attention; 429/rate → exponential backoff; runs/hour cap 12; loop guard: two wakes
without cursor advance → integrator wakes disabled + attention) → stall detection (session
running per API but heartbeat > 20 min stale → attention; never kills interactive sessions —
it only reaps children it spawned) → every launch/exit + duration → `logs/runs.jsonl`.

Models: **free tier only** (`conductor.yaml → model`, default
`opencode/mimo-v2.6-flash-free`) for headless runs; pings use each session's own configured
model. Dev runs must never burn Groq quota, Go, or paid models.

## Wave gate (human-only)

When every required lane (not paused, `current_wave >= min_wave`) has
`merged_wave == current_wave`: Wave 2 requires a **LIVE** E2E on the real instance →
`coord attention "Wave N gate ready: say go for live E2E"` and **stop** (no auto-bump).
Other waves: tag `wave-N-gate`, `wave-bump`, wave_open to every inbox, PROGRESS entry.

## Tests

```bash
python3 tools/conductor/tests/test_coord.py       # 14: CLI semantics + concurrent writers
python3 tools/conductor/tests/test_conductor.py   # 8: dry wakes, STOP, failure caps, 429, loop guard, timeout
python3 tools/conductor/tests/test_e2e.py         # 1: wave_done → handler → wave bump → dry wakes → STOP → caps
```

All run in temp `RAPHAEL_COORD_DIR` sandboxes with `COORD_NO_TOAST=1`; no network, no models.

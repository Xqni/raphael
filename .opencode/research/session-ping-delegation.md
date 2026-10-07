# Session ping vs wait loops — verified research (2026-10-06, opencode v2.0.22)

Question: how do lane sessions learn about coord events WITHOUT `coord wait` polling loops
(each wait = one model turn = tokens on free/cheap tiers)? Answer: **don't poll — ping.**

## The mechanism (verified live)

`POST /api/session/{sessionID}/prompt` via `opencode api post` (auth handled by the CLI):

```bash
opencode api post /api/session/<sid>/prompt \
  --data '{"text":"...","delivery":"steer"}'
```

OpenAPI summary: *"Durably admit one session input and schedule agent-loop execution unless
resume is false."* Body: `{text (required), files[], skills[], metadata?, delivery?, resume?}`.
`delivery: "steer" | "queue"`. Responses: 200/400/401/404/409. Plain `curl` to the server port
gets `401 Authentication required` — must go through `opencode api` (or obtain auth another way).

### Live test evidence (scratch session, now deleted)

- Ping #1 to an **idle server-side session (no TUI attached)**: admitted, agent ran, replied
  (~5.3 s). Ping #2 to the same idle session: admitted, ran, replied (~2.1 s). Session context
  fully preserved — same sessionID, conversation continues.
- Ping while **busy**: `steer` was admitted (no 409 in practice) and processed after the current
  run; `queue` likewise. FIFO order kept: A(count 1-20) → B_OK → C_OK.
- Message schema: `user.text`, `assistant.content[] (type text|reasoning)`, `idle` markers.
  Assistant runs show model/provider used by that session.

## Session discovery + identity

- `GET /api/session` (via `opencode api get "/api/session?limit=100"`) → each session has
  `id`, `title`, `location.directory` (the worktree!), timestamps. **Directory is the
  authoritative lane key; title is display-only (user renames sessions freely).**
- `GET /api/session/active` → `{sessionID: {type:"running"}}` — who is mid-run right now.
- Every agent process has **`OPENCODE_SESSION_ID`** in its environment → a lane can report its
  own sid in a heartbeat event (`--data '{"session_id":"..."}'`).
- CLI: `opencode session list --format json -n 100` (project-scoped table fallback).

## Cost math

- Wait loop @ 90 s: ~40 model turns/hour **while idle** (~960/day) — the entire waste.
- Ping: **0 turns while idle** (an idle session costs nothing server-side) + 1 wake turn per
  actual event, with the lane's full context intact (vs. a fresh headless relaunch re-reading
  the worktree docs every time).
- Conductor watching files with python = free (no model at all).

## Delegation (the other option) — for comparison

The `subagent` tool with `background: true` + `sessionID` continuation lets *me* re-invoke a
child session with its full prior context (a "ping" for delegated work) and get completion
notifications — no polling. But lane sessions the **user opened in TUIs** are not my children,
so delegation does not apply to them; it is the alternative topology if lane work ever moves
under orchestrator-driven child sessions (claude's "conductor owns all runs" long-term idea).
Verdict: **ping-in-place for user-opened lanes; fresh `opencode run` only as fallback when a
lane has no session; delegation stays available for orchestrator-spawned work.**

## Design delta vs the original coordinator brief

1. Lanes NEVER run wait loops by default: `coord mode` → `exit` means "end your turn; the
   conductor will ping you" (zero idle cost). `wait` remains only as the documented fallback
   when the conductor is down (use long timeouts, e.g. 300 s+, to limit turns).
2. Conductor wake path = `coord ping --lane X --msg ...` (API prompt injection, delivery steer,
   auto-fallback to headless `opencode run` only if the lane has no session).
3. Pinging an existing session **removes the two-sessions-in-one-worktree risk** for that lane
   (same session continues); headless fallback still checks the lane lock first.
4. Lane adoption posts `session_id` ($OPENCODE_SESSION_ID) in its first heartbeat; conductor
   also discovers by `location.directory` match as fallback (rename-proof).
5. 429/rate pressure lever stays: lower `max_parallel_runs` (default 3 → 2), runs/hour cap.

## Verified CLI flags (for docs/COORD_PROTOCOL.md)

`opencode run [flags] [<message...>]`: `--auto` (auto-approve permissions not explicitly
denied; `ask`-rules would block headless — defaults allow `*` with external-dir/.env ask),
`--agent`, `--model provider/model#variant`, `--session/-s`, `--continue/-c`, `--fork`,
`--format json|default` (JSON = JSONL event stream), `--file/-f`, `--title`, `--standalone`,
`--server`. Fresh run = omit `-s/-c`. Working directory = cwd (project discovery).
`opencode serve`: `--hostname --port --cors --service --stdio`; there is **no `attach`
subcommand** in v2.0.22 (use `--server <url>` / `opencode api` against a running server).
`opencode service status` → server URL (e.g. http://127.0.0.1:49374).

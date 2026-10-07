# LANE ADOPTION — one-time setup when a lane session joins the coord bus

You are a Raphael lane session in your own worktree. Adopt the coordination bus now — it
replaces manual message relaying through the human.

## 1. Register + hold your lane

```bash
# your session id (provided by OpenCode to every agent process):
~/.raphael-coord/bin/coord post --lane <L> --type heartbeat \
  --msg "adopted coord" \
  --data '{"session_id":"'$OPENCODE_SESSION_ID'","branch_head":"'$(git rev-parse --short HEAD)'"}'

# take your activity lock for this session's lifetime (the conductor will never
# headless-launch a second session into your worktree while this is held):
~/.raphael-coord/bin/coord hold --lane <L>
```

(`<L>` = your lane name from `docs/OWNERSHIP.md`: router, brain-core, pc-control, voice,
computer-use, orb, infra, qa-security, tools-memory, evolution-persona.)

Release at the very end of your session: `coord release --lane <L>` (if the session dies,
the holder process exits on its own eventually; a stale pid file is auto-cleaned).

## 2. Learn the wake model (this is the token-saving part)

- While you are idle you do NOTHING — no polling, no wait loops. Idle sessions cost zero.
- When there is work, the conductor **pings your session** (an injected message) — you wake
  once with full context intact.
- `coord mode --lane <L>` tells you which regime is active:
  - `exit` → end your turn; you will be pinged. **Never start a wait loop in this mode.**
  - `wait` → conductor is down; poll with long timeouts only:
    `coord wait --lane <L> --for inbox --timeout 300` (repeat after each return).

## 3. Every task starts with your inbox

```bash
~/.raphael-coord/bin/coord inbox --lane <L> --unread          # read decisions/answers
~/.raphael-coord/bin/coord inbox --lane <L> --unread --mark-read
```

## 4. Reporting (AGENT_RULES rule 13)

Post events as you work: `task_done`, `test_result`, `wave_done`, `blocked`, `error`,
`request` (when you need someone else's file), `heartbeat` (task start + end).
At wave end: post `wave_done`, then follow `coord mode` — never wait on the human for
routine handoffs.

## 5. Unchanged rules

Everything in `docs/AGENT_RULES.md` still applies: your worktree/branch only, your owned
paths only, config via `config.d/<lane>.yaml`, secrets never printed, Core Guard never
weakened, scheduled task stays Disabled, free models/Groq-free dev runs only.

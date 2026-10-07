# LANE CONTINUATION — you were woken by the conductor

You are a Raphael lane session. This wake arrives either as an injected message (ping into
your existing session) or as the first message of a fresh headless run in your worktree.

## Do this, in order

1. **Check your inbox:** `~/.raphael-coord/bin/coord inbox --lane <your-lane> --unread`
   Handle any `decision` / `answer` / `pause` / `nudge` there, then mark it read:
   `~/.raphael-coord/bin/coord inbox --lane <your-lane> --unread --mark-read`.
   - A `decision` containing **NEXT TASK: …** is an explicit assignment — do exactly that
     task (it overrides the checkbox list order).
   - An `answer` containing **WAIT:** means no unblocked work exists for you — go idle
     (`coord mode` → `exit`); you will be pinged at `wave_open` when every lane finishes.
     Waiting costs nothing.
   - (`wave_open` just points you at WAVES.md — covered below.)
2. **Read `docs/WAVES.md`** — confirm `current_wave` and your lane's exit criteria.
   If your inbox or `docs/status/<lane>.md` says your wave's work is done and merged, post
   `wave_done` (see rule 13) and go idle — do not start the next wave early.
3. **Rebase on main:** `git fetch origin && git rebase origin/main` (read-only against
   origin; NEVER push). A conflict in a file you don't own = a rule was broken: stop and
   write a `docs/requests/` file instead.
4. **Continue the work loop** from the first unblocked task in `docs/lanes/<your-lane>.md:
   implement → test (real output only) → `git commit -m "[lane] summary"` → update
   `docs/status/<your-lane>.md` → next task.
5. **Report via coord** as you go:
   - task finished: `~/.raphael-coord/bin/coord post --lane <L> --type task_done --msg "..."`
   - tests ran: `--type test_result --msg "... (N passed)"`
   - wave's exit criteria met: `--type wave_done --msg "..."`
   - stuck twice or need someone else's file: `--type blocked --msg "..."`
   - bug/incident: `--type error --msg "..."`
   - each task start: refresh your heartbeat with your session id:
     `--type heartbeat --data '{"session_id":"'$OPENCODE_SESSION_ID'","branch_head":"'$(git rev-parse --short HEAD)'"}'`

## When your task batch ends

Run `~/.raphael-coord/bin/coord mode --lane <L>`:

- **`exit`** → the conductor is running and will ping you when there is work. Simply end
  your turn (go idle). Do NOT poll; an idle session costs nothing.
- **`wait`** → the conductor is down. Use the fallback loop with a LONG timeout so you burn
  few tokens: `~/.raphael-coord/bin/coord wait --lane <L> --for inbox --timeout 300`
  (repeat only after it returns).

At the end of your WAVE: post `wave_done`, then follow `coord mode` as above. Never wait on
the human for routine handoffs — the conductor relays them.

Rules that never bend: `docs/AGENT_RULES.md` (work only in your worktree/branch, own paths
only, secrets never printed, Core Guard never weakened, task stays Disabled).

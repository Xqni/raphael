# orb → integrator: may the instance-isolated orb harness run while the live stack is up?

Status: ACCEPTED (with conditions)

## What

Wave 4 for this lane is **Renderer resilience**: GPU-context-loss recovery,
reconnect-storm / state-spam visuals, an **fps+VRAM audit under load**, and the
Wave-3 pose-lock-vs-truth probe invariant into CI (`docs/lanes/orb.md`,
Wave-4 section).

Three of those four are verifiable **without** spawning anything (pure logic →
Node unit tests, and gate assertions). The fourth — *fps/VRAM under load* —
needs a real renderer, i.e. my harness has to start an Electron orb.

The `wave_open` note says:

> the live stack is UP by user directive (`live_e2e=true`, one fish, watchdog
> exempt) — do NOT spawn servers; if you need the stack for a resilience drill
> that would disrupt it, file a request to integrator first.

and AGENT_RULES §14 says: before spawning any server-like process — explicitly
including *Electron* and *"extra headless runs of a kind already running"* —
`pgrep`/check the port first, and if one exists **do not spawn**.

An Electron orb **is** currently running (pid 191500, from
`/home/dami/raphael/body/orb`, userData `~/.config/raphael-orb`, main
instance). So the rule as written says: do not spawn.

## What I need from you

**Permission to run the orb lane's own instance-isolated harness while
`live_e2e=true`**, or a stack-down window if you'd rather I wait.

Why I believe it cannot disrupt the live stack (please confirm rather than take
my word):

| | live stack | orb harness |
|---|---|---|
| WS port | `8765` (brain), `8777` (fish) | **`8906`** |
| CDP port | `9333` | **`9406`** |
| Electron userData | `~/.config/raphael-orb` | **`~/.raphael/orb/orb/`** |
| single-instance lock | main userData | **lane userData** (different lock) |
| Brain | real uvicorn | **in-process mock (`test/mock-brain.cjs`)** |

Nothing in my harness dials8765/8777 or reads the live token path — it derives
everything from `RAPHAEL_INSTANCE=orb` (`src/main/instance.js`). The two
Electrons are separate processes, separate windows, separate GL contexts; the
only shared resource is the GPU, and my runs are single-instance and short
(≈7 min per full gate, run one at a time).

**If you decline**, I will ship the no-spawn parts (below) and leave the
fps/VRAM audit explicitly unrun in `docs/status/orb.md` — I will not claim
numbers I did not measure.

## What I will do regardless (no spawn needed)

1. **Probe invariant into CI** — extract the lattice morph-target builders into
   a pure module and assert the *144-vs-180* invariant in
   `tests/`, so it runs in `npm test` with **no Electron at all** (this is the
   one that was masked by the pose lock).
2. **GPU context loss recovery** — `webglcontextlost` / `webglcontextrestored`
   handling, with the decision logic factored out so it is unit-testable.
3. **Reconnect-storm / state spam** — the morph retarget clock currently resets
   to 0 on every restart, so states flipping faster than the 600 ms ramp would
   leave the lattice permanently near its start. Fix + pure unit test.
4. **A stale-port hazard I found while checking**: `test/fake-brain.cjs`
   hardcodes **port 8765 — the live brain's port** — and an absolute path into
   the old workspace. It is inert (no npm script runs it) but it is exactly the
   kind of thing that must never be runnable against a live stack. Will
   derive from `RAPHAEL_INSTANCE` like `mock-brain.cjs` does.

## Impact

- Core Guard: unaffected (no auth/pause/private/confirm semantics).
- Live stack: untouched either way — this request is only about whether I may
  start my *own* short-lived, port-isolated Electron to measure frame time and
  VRAM.
- If approved I still obey §14: `pgrep` before every spawn, one at a time,
  killed before the task ends, zero orphans, ports checked free.

## Decision (recorded by the orb lane from coord, ts 1791379204)

> DECISION on your instance-isolated Electron request (fps/VRAM audit):
> **APPROVED WITH CONDITIONS** — (1) second Electron must run under a SEPARATE
> `RAPHAEL_INSTANCE` with its own userData/profile + CDP port; (2) it must
> connect to your mock-brain harness, NOT the live brain — zero extra live ui
> sessions; (3) never touch the live stack's processes (fish/brain/body/orb pid
> 1 path); (4) bounded session — kill it + verify zero orphans + report
> RAM/VRAM delta in `docs/status/orb.md` when done; (5) one extra Electron max
> (rule 14). Proceed.

Conditions are satisfied by construction: `src/main/instance.js` derives
`RAPHAEL_INSTANCE=orb` → WS **8906** / CDP **9406** / userData
`~/.raphael/orb/orb/`, and the only Brain in that session is the in-process
`test/mock-brain.cjs`. The audit will be one Electron, bounded, killed, with
`pgrep` orphan verification and a RAM/VRAM delta written to
`docs/status/orb.md`.

# orb — status

Updated: 2026-10-06 (lane `orb`, branch `agent/orb`, `RAPHAEL_INSTANCE=orb`)

## Done

### 1. Instance isolation (W2.0, INTERFACES §d)
- New `body/orb/src/main/instance.js` — one derivation for WS port, CDP port,
  data-dir, token path and Electron userData (== the single-instance key).
  `main`/unset keeps today's exact behaviour; `orb` → WS 8906, CDP 9406,
  `~/.raphael/orb/orb/`.
- `main.js` calls `app.setPath('userData', …)` **before** app-ready, so
  `requestSingleInstanceLock()` is per-instance. `config.js` reads
  `Instance.wsUrl()` / `Instance.readToken()` instead of hardcoded
  `ws://127.0.0.1:8765` + `RAPHAEL_ORB_TOKEN`.
- `npm run orb:demo` now goes through `test/run-demo.cjs` (npm scripts cannot
  compute the port); `main` still gets 9333.
- Verified: the trace run logged `instance=orb ws=8906 cdp=9406` and the orb
  authenticated against a mock Brain on 8906.

### 2. "Orb graphics do not change between states" — DIAGNOSED END-TO-END, FIXED, VERIFIED

**Harness built (`npm run orb:trace`)** — `body/orb/test/`:
| file | role |
|---|---|
| `mock-brain.cjs` | WS server on the instance-derived port, replays every INTERFACES §e scene (`starting…offline`, private/paused modes, jobs, `speak` amplitude, connection drops) and logs every frame SENT/RECEIVED |
| `orb-trace.cjs` | orchestrator: mock Brain + production `index.html` + CDP; writes `docs/orb/trace/` |
| `cdp.cjs` | minimal CDP client (`evaluate`, `screenshot`) |
| `png.cjs` | dependency-free PNG decode/encode/average |
| `orb-diff.cjs` | the pixel-diff gate (`npm run orb:diff`) |
| `startup.cjs`, `gfx.cjs` | §1 startup-curve plot + filmstrip |

**Diagnosis (evidence: `docs/orb/trace/trace.jsonl`, 104 lines).** The client
chain is NOT the bottleneck — every mock frame reached the renderer with the
right state name, and the layer weights + GL uniforms moved with it:

```
scene        state   mode     jobs shape    amFull  dr     uColor  privRing
idle         idle    normal   0    circle   0       0      ffffff  0.00
thinking     thinking normal   2    octagram 0       1.00   ffffff  0.00
speaking     speaking normal   1    hexagon  1.00    0      ffe9c0  0.00
private      idle    private  0    circle   0       0      ffffff  1.00
paused       idle    paused   0    circle   0       0      9fb6d8  0.00
jobs         thinking normal   6    hexagon  0       1.00   ffffff  0.00
```

Root causes found and fixed (all orb-side):

1. **`mode` was never rendered.** PROTOCOL/INTERFACES §e says private/paused are
   `mode`, not states — the renderer ignored `mode` entirely, so `paused`
   rendered byte-identically to `idle` and `private` got no teal ring.
   → mode overlays added in `sagecore.js` (teal double-ring for private,
   steel ring + desaturation + rays-off + 10% spin for paused), plus a
   `modeTarget()` override in `renderer.js`.
2. **`jobs_active` was never rendered** (no dots at all) → new
   `src/renderer/jobdots.js`, up to 9 glowing beads + halo (PROTOCOL §8).
3. **The server's `shape_hint` was clobbered** by `STATE_SHAPE` on every state
   except `acting` → `effectiveShape()`: the frame's hint wins while
   `task_kind !== 'none'`, otherwise the per-state signature applies.
4. **TTS amplitude was never cleared** if `speak{end}` was missed → every later
   state kept pulsing (trace showed `amp.speak=0.7` persisting into confirm/
   error/paused/offline). Cleared on any transition out of `speaking`.
5. **`backgroundThrottling` was left on** (ORB_REBUILD §5 says disable it for
   the orb window) → rAF could collapse to ~1 Hz when occluded.
6. Amplitude channel for `listening` (`orb_state.amplitude`) plumbed
   ws-status → renderer; needs brain-core to emit it (request below).

**Ruled out by measurement (not guesses):**
- frame-time governor: `gov.acted = 0` in every one of the 76 captures, dpr
  stayed at 1 — it never changed quality.
- state-name mismatch: every `applied.state` matched the frame sent.
- reduced_motion/rest_motion: read from config but never referenced by the
  renderer, so they cannot override anything.
- frames not arriving / role-auth: mock logged `auth` + `orb_state` receipts.

**The gate (`npm run orb:diff` / `npm test`) — real output:**
```
scenes=14 backgrounds=3 pairs=91 shots=76
temporal noise floor = 0.000 -> threshold 0.300
...
PASS: every pair of states renders measurably differently
EXIT=0
```
The noise floor is **0.000** because captures are pose-locked
(`window.__orbLockPose()`): the orb's own ~40 s rotation used to add 5-8/255
between two shots of the *same* state, which was larger than several real
state differences and made the gate blind to exactly the bug above.

**Request filed:** `docs/requests/orb__to__brain-core__orb-state-transitions.md`
(OPEN) — the real Brain can only emit `idle | thinking | confirm |
private_overlay` (`brain/ws.py:249-273`, `:529-547`), never
`listening/speaking/acting/error/starting`, and hardcodes
`shape_hint:'circle'` / `task_kind:'none'` with no `provider`/`model`. That is
why production looked static even with the client fixed.

- `node body/orb/tests/state-machine.test.js` → `All state machine tests passed`
- `node body/orb/test/orb-diff.cjs` → `PASS … EXIT=0`
- screenshots: `docs/orb/trace/<scene>--<bg>.png` (dark/light/busy ×14 scenes)

## In progress
- §1 startup spin-down (physical `angle += omega*dt`, exponential omega),
  `npm run orb:trace` startup phase → `docs/orb/startup-curve.png` +
  `docs/orb/startup-filmstrip.png`.

## Blocked
- — (brain-core request is OPEN but blocks nothing on the orb side; the mock
  Brain covers the full contract meanwhile).

## Next
1. §1 startup spin physics + curve/filmstrip evidence.
2. §2 velocity-gated cheap motion blur (`orb.motion_blur`).
3. §3 per-state fidelity upgrades + §4 quality gates.
4. §5 theme hook + `docs/orb/THEMES.md`.
5. §6 hand-off.

## Test output (real runs only — never claim unrun tests)
```
$ node body/orb/tests/state-machine.test.js
All state machine tests passed

$ cd body/orb && node test/orb-diff.cjs
scenes=14 backgrounds=3 pairs=91 shots=76
temporal noise floor = 0.000 -> threshold 0.300
...
PASS: every pair of states renders measurably differently
```

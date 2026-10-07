# docs/orb/STARTUP.md — the startup spin-down (fidelity pass §1)

Owner: orb lane. Refines `docs/ORB_REBUILD_TASK.md`; config lives in
`config.d/orb.yaml` → `orb.startup.spin_tau_ms`.

---

## 1. The problem the user reported

> "during the `starting` → `idle` sequence, the final spin eases out too early
> and then stops decelerating, so there is no real smooth slowdown."

## 2. Diagnosis (measured, not guessed)

`npm run orb:trace` drives a full scripted `starting → idle` sequence and
samples the rotation through `window.__orbSpin()` every 50 ms
(`docs/orb/trace/startup-samples.json`, 147 samples / 7953 ms).

**BEFORE (2026-10-06, original code):**

```
startup: FAIL over 147 samples (7953 ms), peak=21.124 rest=0.496 rad/s
  FAIL monotonic_non_increasing: largest increase = 6.12786 rad/s (eps 0.002) at t=12365 ms
  FAIL no_velocity_jump:          max |d(omega)| = 7.2042 rad/s between samples (eps 0.35) at t=12211 ms
  FAIL exponential_like:          fit R^2 = 0.8903, implied tau = 977 ms (config 1400, allowed 700-4200)
  FAIL no_early_flat_tail:        remaining delta 6.9% at 1.5x tau, 6.9% at 3x tau (need >=10% and <=35%)
  ok   governor_quiet:            frame-time governor acted 0 time(s) during startup
```

Causes, in the order the brief listed them:

| hypothesised cause | verdict | evidence |
|---|---|---|
| easing applied to angle/velocity, not correctly | **CONFIRMED** | the spin used `genSpin = sin²(π·spinProg^0.4)·7` — a bell-shaped *velocity* profile whose tail collapses quadratically. Only **6.9%** of the delta was left at 1.5× tau, i.e. it was visually over long before the sequence ended, then flat. |
| velocity discontinuity at the hand-off | **CONFIRMED** | **+6.13 rad/s jump** between adjacent samples at the `starting → idle` hand-off (the `genSpin` window closes at gt=8300 while `w.spin` ramps 0.00006→0.00013 as the state flips at 5400 ms — two unrelated ramps meeting). |
| frame-count / fixed-step timing, dt not clamped | **CONFIRMED** | four rotations advanced with fixed per-tick constants (`group.rotation.y += 0.003`, `rays.rotation.z += 0.01`, `lattice.rotation.y += 0.004`, `rings ±0.008/0.006`) — speed scaled with the tick rate; and `dt` was `now - lastFrame` (time since the last *render*), which double-counted on the 30 fps idle cap and made every 300–600 ms blend run ~1.5× fast. |
| frame-time governor changing quality mid-startup | **RULED OUT** | `governor_quiet` = 0 actions across the whole startup window (still asserted). |
| state crossfades fighting the spin | **PARTIAL** | weights and rotation were independent, but the two *velocity* ramps above did overlap and interfere. |
| reduced_motion / rest_motion overriding | **RULED OUT** (W2.1) | both are read from config but never referenced by the renderer. |

## 3. The model now

Rotation is physical:

```js
angle  += omega * dt                 // integrated state — NEVER reset, NEVER eased
omega  += (target - omega) * (1 - exp(-dt / tau))   // exponential approach (C1)
```

- **`angle` is integrated state.** `group.rotation.y` is assigned from
  `spin.angle * GROUP_SPIN`, not incremented by hand, so nothing can reset or
  re-time it. Direction lives in `GROUP_SPIN`; `omega` stays a positive
  magnitude, so a genuine reversal would show as a zero crossing in the trace.
- **`omega` relaxes exponentially** toward its target with a configurable tau:
  `omega(t) = rest + (start - rest)·e^(−t/τ)`, τ = `orb.startup.spin_tau_ms`
  (default 1400 ms). Total spin-down ≈ 3 τ ≈ 4.2 s, with the *deceleration*
  already imperceptible at ~3 s.
- **Velocity continuity (C1).** Entering `starting` only changes the *target*
  (smooth spin-up to the peak over 400 ms); leaving it does not touch omega at
  all. `target` then relaxes to `rest`. No snap at either end.
- **dt-based + clamped to 50 ms**, taken per animation tick
  (`now - lastNow`), so a hitch or a throttled tab cannot distort the curve —
  and the 300–600 ms blends now actually take 300–600 ms.
- **Build progress is eased separately** (`easeInOut3` on `genOuter` /
  `genInner` / `genSun`) and overlaps the spin-down; core brightness follows
  `genSun`, so the sun ramps smoothly instead of popping.
- **The frame-time governor is frozen** while `spin.phase !== 'run'` or the
  state is `starting` — no quality change mid-startup, no hitch.

Config knobs (`config.d/orb.yaml`):

```yaml
orb:
  startup:
    spin_tau_ms: 1400    # 1200-1800 per the brief
```

Constants in `renderer.js`: `SPIN_REST = 0.18 rad/s` (today's group rest rate
at the 60 fps design point), `SPIN_PEAK = 3.2 rad/s`, `SPIN_UP_MS = 400`.

## 4. Assertions (all must hold — the run fails otherwise)

`test/startup.cjs`, evaluated over the captured samples:

1. `monotonic_non_increasing` — omega never rises through the spin-down (ε 0.002 rad/s)
2. `no_velocity_jump` — max |Δomega| between adjacent samples ≤ 0.35 rad/s (no hand-off discontinuity)
3. `no_zero_crossing` — omega stays > 0
4. `exponential_like` — ln((omega−rest)/delta) is linear in t: R² ≥ 0.95 and implied tau within [0.5, 3.0]× configured
5. `no_early_flat_tail` — ≥10% of the delta still left at 1.5τ, ≤35% left at 3τ
6. `settled` — within 15% of the delta of rest by the end of the window
7. `governor_quiet` — the frame-time governor acted 0 times during startup

## 5. Evidence

- `docs/orb/startup-curve.png` — omega measured vs the exponential fit, plus
  angle / core brightness / layer weights, with the PASS/FAIL verdict and the
  fitted tau on the chart.
- `docs/orb/startup-filmstrip.png` — contact sheet across `starting → idle`.
- `docs/orb/trace/startup-samples.json` — every raw sample.
- Re-run: `npm run orb:trace` (the startup phase runs first, then the
  per-state scenes and the pixel-diff gate).

## 6. AFTER numbers

Filled in by the verification run — see `docs/status/orb.md` §Test output.

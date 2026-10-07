#!/usr/bin/env node
// startup.cjs — §1 evidence for the startup spin-down.
//
// Consumes the samples taken by orb-trace.cjs through window.__orbSpin():
//   { t, angle, omega, rest, peak, tau, phase, state, genT, bright, weights }
// and produces:
//   docs/orb/startup-curve.png     two stacked charts + PASS/FAIL verdict
//   docs/orb/startup-filmstrip.png contact sheet across starting -> idle
//   a JSON report with every assertion and its number
//
// Assertions (the task's, verbatim in intent):
//   1. omega is monotonic non-increasing during the spin-down
//   2. no velocity jump above epsilon at the hand-off
//   3. no zero crossing (omega stays positive)
//   4. the curve is exponential-like with no early flat tail
const fs = require('fs');
const path = require('path');
const { create, rect, text, textWidth, chart, filmstrip, encode, line } = require('./gfx.cjs');

const EPS_MONO = 0.002;          // rad/s — allow integration jitter only
const EPS_JUMP = 0.35;           // rad/s between adjacent samples (~60 ms)
const MIN_TAU_RATIO = 0.5;       // implied tau must sit inside [0.5, 3.0] x cfg
const MAX_TAU_RATIO = 3.0;
const FLAT_TAIL = 0.35;          // at 3 x tau >65% of the delta must be gone
const SETTLE_FRAC = 0.08;        // end of the window within 8% of the delta

/** Find the spin-down window: peak sample -> where the delta is < SETTLE_FRAC. */
function findWindow(s) {
  let peakIdx = 0;
  for (let i = 1; i < s.length; i++) if (s[i].omega > s[peakIdx].omega) peakIdx = i;
  const peak = s[peakIdx].omega;
  const rest = s[s.length - 1].rest;
  const delta = peak - rest;
  if (!(delta > 0)) return null;
  let endIdx = peakIdx;
  for (let i = peakIdx; i < s.length; i++) {
    if (s[i].omega - rest <= delta * SETTLE_FRAC) { endIdx = i; break; }
    endIdx = i;
  }
  return { peakIdx, endIdx, peak, rest, delta, t0: s[peakIdx].t, t1: s[endIdx].t };
}

function analyze(samples) {
  const checks = [];
  const add = (name, ok, detail) => checks.push({ name, ok, detail });

  const w = findWindow(samples);
  if (!w) {
    add('window', false, 'omega never exceeded its rest value — no spin-down found');
    return { pass: false, checks, window: null };
  }
  const seg = samples.slice(w.peakIdx, w.endIdx + 1);
  const rest = w.rest, delta = w.delta;

  // --- 3) no zero crossing, anywhere -----------------------------------------
  const minOmega = Math.min(...samples.map((s) => s.omega));
  add('no_zero_crossing', minOmega > 0, `min omega = ${minOmega.toFixed(4)} rad/s (must be > 0)`);

  // --- 1) monotonic non-increasing through the spin-down ---------------------
  let worstUp = 0, worstUpAt = null;
  for (let i = 1; i < seg.length; i++) {
    const rise = seg[i].omega - seg[i - 1].omega;
    if (rise > worstUp) { worstUp = rise; worstUpAt = seg[i].t; }
  }
  add('monotonic_non_increasing',
      worstUp <= EPS_MONO,
      `largest increase = ${worstUp.toFixed(5)} rad/s (eps ${EPS_MONO})` +
      (worstUpAt ? ` at t=${worstUpAt} ms` : ''));

  // --- 2) no velocity jump at the hand-off -----------------------------------
  // omega is angular VELOCITY, so a jump in it is an acceleration spike.
  // Sample-to-sample |d(omega)| must stay well under the biggest legitimate
  // change (the moment the target flips peak -> rest at the spin-up hand-off).
  let worstJump = 0, worstJumpAt = null;
  for (let i = 1; i < seg.length; i++) {
    const j = Math.abs(seg[i].omega - seg[i - 1].omega);
    if (j > worstJump) { worstJump = j; worstJumpAt = seg[i].t; }
  }
  add('no_velocity_jump', worstJump <= EPS_JUMP,
      `max |d(omega)| = ${worstJump.toFixed(4)} rad/s between samples (eps ${EPS_JUMP})` +
      (worstJumpAt ? ` at t=${worstJumpAt} ms` : ''));

  // --- 4) exponential-like, no early flat tail -------------------------------
  // For omega(t) = rest + delta*exp(-t/tau), ln((omega-rest)/delta) is linear
  // in t with slope -1/tau. Fit it over the spin-down window and require the
  // implied tau to sit around the configured value AND R^2 to be high.
  const pts = [];
  for (const s of seg) {
    const d = s.omega - rest;
    if (d > 1e-4) pts.push([s.t, Math.log(d / delta)]);
  }
  let r2 = 0, impliedTau = 0;
  if (pts.length >= 4) {
    const n = pts.length;
    const mx = pts.reduce((a, p) => a + p[0], 0) / n;
    const my = pts.reduce((a, p) => a + p[1], 0) / n;
    let sxx = 0, sxy = 0, syy = 0;
    for (const [x, y] of pts) { sxx += (x - mx) ** 2; sxy += (x - mx) * (y - my); syy += (y - my) ** 2; }
    const slope = sxy / (sxx || 1);
    r2 = (sxy * sxy) / ((sxx * syy) || 1);
    impliedTau = slope < -1e-9 ? -1000 / slope : Infinity; // t is in ms
  }
  const cfgTau = samples[0].tau;
  add('exponential_like',
      pts.length >= 4 && r2 >= 0.95 &&
      impliedTau >= MIN_TAU_RATIO * cfgTau && impliedTau <= MAX_TAU_RATIO * cfgTau,
      `fit R^2 = ${r2.toFixed(4)}, implied tau = ${Number.isFinite(impliedTau) ? impliedTau.toFixed(0) : 'inf'} ms ` +
      `(config tau ${cfgTau} ms, allowed ${Math.round(MIN_TAU_RATIO * cfgTau)}-${Math.round(MAX_TAU_RATIO * cfgTau)})`);

  // no early flat tail: 3 x tau into the spin-down most of the delta is gone,
  // and at 1.5 x tau it is still clearly there (it must not decay instantly).
  const t3 = w.t0 + 3 * cfgTau, t15 = w.t0 + 1.5 * cfgTau;
  const at = (tt) => {
    let best = seg[0];
    for (const s of seg) if (Math.abs(s.t - tt) < Math.abs(best.t - tt)) best = s;
    return best;
  };
  const rem3 = (at(t3).omega - rest) / delta;
  const rem15 = (at(t15).omega - rest) / delta;
  add('no_early_flat_tail', rem3 <= FLAT_TAIL && rem15 >= 0.1,
      `remaining delta: ${(rem15 * 100).toFixed(1)}% at 1.5x tau, ${(rem3 * 100).toFixed(1)}% at 3x tau ` +
      `(need >=10% and <=${FLAT_TAIL * 100}%)`);

  // settled by the end of the sampling window
  const lastRem = (samples[samples.length - 1].omega - rest) / delta;
  add('settled', lastRem <= 0.15,
      `last sample is ${(lastRem * 100).toFixed(1)}% of the delta above rest (need <=15%)`);

  // governor must not touch quality mid-startup (spec: no visible hitch)
  const govActed = Math.max(...samples.map((s) => s.govActed || 0));
  add('governor_quiet', govActed === 0,
      `frame-time governor acted ${govActed} time(s) during startup (must be 0)`);

  const pass = checks.every((c) => c.ok);
  return {
    pass, checks, window: { ...w, durationMs: w.t1 - w.t0, samples: seg.length },
    fit: { r2, impliedTau, cfgTau },
    rem15, rem3,
  };
}

// --- rendering ---------------------------------------------------------------
const SERIES_COLORS = {
  omega: [94, 234, 212, 255],   // teal
  angle: [129, 140, 248, 255],  // indigo
  bright: [255, 224, 138, 255], // amber
  weight: [129, 230, 150, 255], // green
};

function renderPlot(samples, report, outFile) {
  const W = 1180, H = 700;
  const img = create(W, H, [14, 15, 18, 255]);
  const w = report.window;

  text(img, 'RAPHAEL ORB - STARTUP SPIN-DOWN', 24, 20, [240, 242, 248, 255], 3);
  const verdict = report.pass ? 'PASS' : 'FAIL';
  const vc = report.pass ? [110, 231, 138, 255] : [248, 113, 113, 255];
  text(img, verdict, 24, 54, vc, 3);
  text(img, `TAU ${report.fit.cfgTau} MS   PEAK ${report.fit && w ? w.peak.toFixed(3) : '?'} RAD/S   ` +
       `REST ${w ? w.rest.toFixed(3) : '?'} RAD/S   WINDOW ${w ? w.durationMs : '?'} MS`,
       130, 58, [190, 196, 210, 255], 2);

  // Chart 1: raw omega (rad/s) with the exponential fit overlaid
  const fitValues = [];
  if (w) {
    for (const s of samples) {
      fitValues.push(s.t >= w.t0
        ? w.rest + w.delta * Math.exp(-(s.t - w.t0) / report.fit.cfgTau)
        : NaN);
    }
  }
  chart(img, {
    x: 60, y: 100, w: 1080, h: 220,
    title: 'OMEGA (RAD/S) - MEASURED VS EXPONENTIAL FIT',
    series: [
      { label: 'MEASURED', color: SERIES_COLORS.omega, values: samples.map((s) => s.omega) },
      { label: 'FIT EXP(-T/TAU)', color: [250, 150, 90, 255], values: fitValues },
      { label: 'REST', color: [130, 136, 150, 255], values: samples.map(() => (w ? w.rest : 0)) },
    ],
    ymin: 0, ymax: (w ? w.peak : 1) * 1.12,
    xlabel: 'SAMPLE INDEX (50 MS EACH)',
  });

  // Chart 2: normalized companions
  const peak = w ? w.peak : 1;
  const maxAngle = Math.max(...samples.map((s) => s.angle), 1e-9);
  chart(img, {
    x: 60, y: 420, w: 1080, h: 200,
    title: 'ANGLE (NORM), CORE BRIGHTNESS, LAYER WEIGHTS',
    series: [
      { label: 'ANGLE', color: SERIES_COLORS.angle, values: samples.map((s) => s.angle / maxAngle) },
      { label: 'CORE BRIGHT', color: SERIES_COLORS.bright, values: samples.map((s) => s.bright) },
      { label: 'LATTICE WT', color: SERIES_COLORS.weight, values: samples.map((s) => s.weights.lattice) },
      { label: 'HALO WT', color: [232, 140, 190, 255], values: samples.map((s) => s.weights.halo) },
    ],
    ymin: 0, ymax: 1.1,
    xlabel: 'STATE: STARTING -> IDLE AT T=5400 MS',
  });

  fs.writeFileSync(outFile, encode(img));
}

function renderFilmstrip(frames, outFile) {
  const strip = filmstrip(frames, { cell: 150, gap: 8, labels: frames.labels || [] });
  fs.writeFileSync(outFile, encode(strip));
}

module.exports = { analyze, renderPlot, renderFilmstrip, findWindow };

if (require.main === module) {
  const dir = process.argv[2] || path.join(__dirname, '..', '..', '..', 'docs', 'orb');
  const samplesPath = path.join(dir, 'startup-samples.json');
  if (!fs.existsSync(samplesPath)) {
    console.error('[startup] no samples — run `npm run orb:trace` first');
    process.exit(1);
  }
  const samples = JSON.parse(fs.readFileSync(samplesPath, 'utf8'));
  const report = analyze(samples);
  renderPlot(samples, report, path.join(dir, 'startup-curve.png'));
  console.log(`[startup] ${report.pass ? 'PASS' : 'FAIL'} — ${report.checks.length} checks`);
  for (const c of report.checks) console.log(`  ${c.ok ? 'ok  ' : 'FAIL'} ${c.name}: ${c.detail}`);
  process.exit(report.pass ? 0 : 1);
}

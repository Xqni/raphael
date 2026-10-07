#!/usr/bin/env node
/* orb-trace.cjs — `npm run orb:trace` (orb lane, W2.1).
 *
 * End-to-end diagnosis harness for "the orb's graphics do not change between
 * states". It exercises the REAL chain, not a shortcut:
 *
 *   mock-brain (WS, instance-derived port)
 *        --orb_state/speak/subtitle-->  ws-status.js (main)  --IPC-->  renderer
 *        --(CDP)--> __orbTrace(): frames received, state applied, layer
 *                   weights and GL uniforms per frame + Page.captureScreenshot
 *
 * Outputs (all under docs/orb/trace/):
 *   <scene>--<bg>.png   one screenshot per scene x background
 *   trace.jsonl         frames SENT by the mock brain, frames RECEIVED by main
 *                       and renderer, and the applied state/weights/uniforms
 *   distinctness.json   pixel-diff matrix; `pass:false` FAILS the run
 *
 * Exit code: 0 only when every pair of scenes renders measurably differently.
 *
 * Usage:  npm run orb:trace           (instance defaults to `orb`, never main)
 *         npm run orb:trace -- --keep (leave the orb running for inspection)
 */
process.env.RAPHAEL_INSTANCE = process.env.RAPHAEL_INSTANCE || 'orb';

const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');
const { MockBrain } = require('./mock-brain.cjs');
const { connect } = require('./cdp.cjs');
const { decode, encode, average } = require('./png.cjs');
const { analyze: analyzeStartup, renderPlot: renderStartupPlot, renderFilmstrip: renderStartupFilmstrip } = require('./startup.cjs');
const Instance = require('../src/main/instance');
const { runDistinctness } = require('./orb-diff.cjs');

const ROOT = path.join(__dirname, '..', '..', '..');
const OUT = path.join(ROOT, 'docs', 'orb', 'trace');
const DOCS_ORB = path.join(ROOT, 'docs', 'orb');
const BGS = ['dark', 'light', 'busy'];
const BG_STYLES = {
  transparent: 'transparent',
  dark: '#222222',
  light: '#e9e9ef',
  busy: 'repeating-conic-gradient(#7a7a7a 0% 25%, #b8b8b8 0% 50%) 0 0 / 48px 48px',
};
const SCENES = [
  'starting', 'idle', 'listening', 'thinking', 'acting', 'speaking',
  'confirm', 'error', 'private', 'private_overlay', 'paused', 'jobs',
  'private_speaking',
];
const SETTLE_MS = 1400;      // > the 600ms worst-case damp/morph window
const LOCK_SETTLE_MS = 600;  // damped uniforms after the pose snap
const STARTUP_SAMPLE_MS = 50;   // omega/angle sampling rate for §1
const STARTUP_MS = 8000;        // window covering starting (5400ms) -> idle
const STARTUP_FRAME_EVERY = 750; // filmstrip cadence across the startup
const HANDOFF_MS = 5400;        // matches renderer's natural boot hand-off
const TRACE_TOKEN = 'trace-test-token'; // harness-only value, not a secret

const log = (...a) => console.log('[orb-trace]', ...a);

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

async function launchOrb(cdpPort) {
  const electron = path.join(__dirname, '..', 'node_modules', '.bin', 'electron');
  const child = spawn(electron, [
    '.', `--remote-debugging-port=${cdpPort}`,
    '--no-sandbox', '--disable-gpu-sandbox', '--ignore-gpu-blocklist',
  ], {
    cwd: path.join(__dirname, '..'),
    stdio: ['ignore', 'pipe', 'pipe'],
    env: {
      ...process.env,
      // Production page (index.html) — the trace must reproduce what the user
      // sees, so --demo is deliberately NOT used here.
      RAPHAEL_ORB_TOKEN: TRACE_TOKEN,
      RAPHAEL_WS_URL: `ws://127.0.0.1:${Instance.wsPort()}/ws`,
      MESA_LOADER_DRIVER_OVERRIDE: 'd3d12',
      GALLIUM_DRIVER: 'd3d12',
    },
  });
  const out = fs.createWriteStream(path.join(OUT, 'orb-stdout.log'), { flags: 'a' });
  child.stdout.pipe(out);
  child.stderr.pipe(out);
  return child;
}

/**
 * §2 budget check (docs/orb/PERFORMANCE.md). Two questions, measured:
 *   - does an ACTIVE state stay within ~25% with the blur ON vs OFF?
 *   - does IDLE cost anything? (it must not — the pass is skipped when calm)
 * Frame time = rolling EMA of real animation-tick intervals, sampled for 2.5 s
 * per condition after a 1.6 s settle.
 */
async function runBlurPerf(cdp, brain, rec) {
  const sample = async (ms) => {
    await cdp.evaluate('window.__orbResetFrameTime()');
    await sleep(ms);
    return await cdp.evaluateJson('JSON.stringify(window.__orbFrameTime())');
  };
  brain.step('speaking');
  await sleep(1600);
  await cdp.evaluate("window.__orbSetMotionBlur('off')");
  const off = await sample(2500);
  await cdp.evaluate("window.__orbSetMotionBlur('force')");
  const on = await sample(2500);
  await cdp.evaluate('window.__orbSetMotionBlur(null)');

  brain.step('idle');
  await sleep(1600);
  const idle = await sample(2500);
  const idleBlur = await cdp.evaluateJson('JSON.stringify(window.__orbMotionBlur())');

  const pct = off.ema > 0 ? ((on.ema - off.ema) / off.ema) * 100 : 0;
  const out = {
    sampleMs: 2500,
    off, on,
    pctOverhead: pct,
    idle: { ema: idle.ema, reason: idleBlur.reason, skipped: idleBlur.skipped, speed: idleBlur.speed },
    activeBlur: await cdp.evaluateJson('JSON.stringify(window.__orbMotionBlur())'),
  };
  rec('blur_perf', out);
  fs.writeFileSync(path.join(OUT, 'blur-perf.json'), JSON.stringify(out, null, 2) + '\n');
  return out;
}

async function runStartupPhase(cdp, brain, rec) {
  // §1 evidence: drive a FULL starting -> idle sequence and sample omega,
  // angle, core brightness and layer weights every 50 ms through it, plus a
  // filmstrip of the visual result.
  brain.step('idle');
  await sleep(1500); // known rest state before the sequence starts

  const cfgTau = await cdp.evaluateJson('JSON.stringify((window.orbConfig && window.orbConfig.startupSpinTauMs) || 1400)');
  const samples = [];
  const frames = [];
  const labels = [];
  let handedOff = false;

  brain.step('starting');          // t = 0 of the scripted sequence
  await sleep(30);
  const start = Date.now();
  let nextFrameAt = 0;
  while (Date.now() - start < STARTUP_MS) {
    const s = await cdp.evaluateJson('JSON.stringify(window.__orbSpin())');
    s.rel = Date.now() - start;
    samples.push(s);
    // reproduce the natural boot hand-off (renderer flips starting -> idle
    // 5400 ms after load; a re-triggered sequence must be driven the same way)
    if (!handedOff && s.rel >= HANDOFF_MS) { brain.step('idle'); handedOff = true; }
    if (s.rel >= nextFrameAt) {
      frames.push(decode(await cdp.screenshot()));
      labels.push('T=' + s.rel);
      nextFrameAt += STARTUP_FRAME_EVERY;
    }
    await sleep(STARTUP_SAMPLE_MS);
  }

  // omega: explicit once the physical rewrite is in; otherwise finite-difference
  // the cage rotation (the layer the current genSpin drives) with a canonical
  // sign so a genuine reversal still shows up as a zero crossing.
  if (samples.some((s) => s.omega === null || s.omega === undefined)) {
    const d = [];
    for (let i = 1; i < samples.length; i++) {
      const dt = (samples[i].rel - samples[i - 1].rel) / 1000;
      const a = samples[i - 1].angles.cage, b = samples[i].angles.cage;
      d.push(dt > 0 && a !== null && b !== null ? (b - a) / dt : 0);
    }
    let best = 0;
    for (const v of d) if (Math.abs(v) > Math.abs(best)) best = v;
    const sign = best >= 0 ? 1 : -1;
    samples[0].omega = (d[0] || 0) * sign;
    for (let i = 1; i < samples.length; i++) samples[i].omega = (d[i - 1] || 0) * sign;
  }

  // fill rest / peak / tau when the renderer does not publish them
  const omegas = samples.map((s) => s.omega);
  const tail = omegas.slice(Math.floor(omegas.length * 0.85)).slice().sort((a, b) => a - b);
  const rest = tail.length ? tail[Math.floor(tail.length / 2)] : 0;
  const peak = Math.max(...omegas);
  for (const s of samples) {
    if (s.rest === null || s.rest === undefined) s.rest = rest;
    if (s.peak === null || s.peak === undefined) s.peak = peak;
    // always the CONFIGURED startup tau: the live one is the spin-UP tau for
    // the first ~400 ms and the analysis must judge the spin-DOWN against it
    s.tau = cfgTau;
    if (s.angle === null || s.angle === undefined) s.angle = s.angles ? s.angles.group : null;
  }

  fs.writeFileSync(path.join(OUT, 'startup-samples.json'), JSON.stringify(samples));
  frames.labels = labels;
  renderStartupFilmstrip(frames, path.join(ROOT, 'docs', 'orb', 'startup-filmstrip.png'));

  const report = analyzeStartup(samples);
  renderStartupPlot(samples, report, path.join(ROOT, 'docs', 'orb', 'startup-curve.png'));
  rec('startup', {
    samples: samples.length, durationMs: samples[samples.length - 1].rel,
    handedOff, pass: report.pass,
    window: report.window, fit: report.fit,
    checks: report.checks,
    peak, rest, cfgTau,
  });
  log(`startup: ${report.pass ? 'PASS' : 'FAIL'} over ${samples.length} samples ` +
      `(${samples[samples.length - 1].rel} ms), peak=${peak.toFixed(3)} rest=${rest.toFixed(3)} rad/s`);
  for (const c of report.checks) {
    log(`  ${c.ok ? 'ok  ' : 'FAIL'} ${c.name}: ${c.detail}`);
  }
  return report;
}

async function main() {
  fs.mkdirSync(OUT, { recursive: true });
  // Clear stale deliverables first: a state we no longer capture on a given
  // background would otherwise linger from an older build and be diffed
  // against fresh images (it did — 4 old offline/reconnecting shots survived).
  for (const f of fs.readdirSync(DOCS_ORB)) {
    if (/^[a-z_]+-(dark|light|busy)\.png$/.test(f)) fs.unlinkSync(path.join(DOCS_ORB, f));
  }
  for (const f of fs.readdirSync(OUT)) {
    if (/^[a-z_]+--(dark|light|busy)(--r\d+)?\.png$/.test(f)) fs.unlinkSync(path.join(OUT, f));
  }
  const cdpPort = Instance.cdpPort();
  const wsPort = Instance.wsPort();
  log(`instance=${Instance.instance()} ws=${wsPort} cdp=${cdpPort}`);

  const lines = [];
  const rec = (ev, extra) => lines.push(JSON.stringify({ ev, t: Date.now(), ...extra }));

  const brain = new MockBrain({ port: wsPort, token: TRACE_TOKEN });
  await brain.listen();
  log(`mock-brain up on ws://127.0.0.1:${wsPort}/ws`);

  const orb = await launchOrb(cdpPort);
  let cdp = null;
  try {
    cdp = await connect(cdpPort);
    log('CDP attached:', cdp.target.title);

    // wait for the orb's auth handshake to reach the mock brain
    let authed = false;
    for (let i = 0; i < 120 && !authed; i++) {
      authed = brain.received.some((r) => r.frame && r.frame.type === 'auth');
      if (!authed) await sleep(250);
    }
    log('auth frame seen by mock-brain:', authed);
    rec('auth', { authed, mockReceivedTypes: brain.received.map((r) => r.frame && r.frame.type) });
    if (!authed) throw new Error('orb never authenticated against the mock brain');

    // let the natural boot story (starting -> idle @5.4s) finish first, so a
    // scripted `starting` is not raced by the boot timeout.
    await sleep(6500);

    // --- §1 startup spin-down evidence --------------------------------------
    let startupReport = null;
    try {
      startupReport = await runStartupPhase(cdp, brain, rec);
    } catch (e) {
      log('startup phase FAILED:', e && e.message);
      rec('startup_error', { message: String(e && e.message) });
    }

    // Capture strategy: the orb is continuously animated (rotating rings,
    // shimmer, flicker), so ONE screenshot differs from the next purely
    // because it is spinning — that self-noise would drown out any state
    // difference. Each scene therefore captures a short burst and writes TWO
    // independent time-averaged images: `<scene>--<bg>.png` (frames 1-4) is
    // the artifact, `<scene>--<bg>--r2.png` (frames 5-8) exists so orb-diff
    // can measure the honest temporal noise floor of an averaged capture.
    const FRAMES = 8, HALF = 4, FRAME_MS = 220;
    const grabBurst = async () => {
      const bufs = [];
      for (let i = 0; i < FRAMES; i++) {
        bufs.push(await cdp.screenshot());
        if (i < FRAMES - 1) await sleep(FRAME_MS);
      }
      const dec = bufs.map((b) => decode(b));
      return { A: average(dec.slice(0, HALF)), B: average(dec.slice(HALF)) };
    };

    const capture = async (scene, bg, opts = {}) => {
      if (!opts.skipStep) {
        await cdp.evaluate(`document.body.style.background = ${JSON.stringify(BG_STYLES[bg])}`);
        brain.step(scene);
      }
      await sleep(SETTLE_MS);          // let crossfade/morph/damp settle
      // POSE LOCK: snap every weight to its target and pin the animation clock
      // so the two captures below are a pure function of (state, mode, jobs,
      // amplitude) — without it the orb's own rotation adds 5-8/255 of noise.
      await cdp.evaluate('window.__orbLockPose && window.__orbLockPose()');
      await sleep(LOCK_SETTLE_MS);     // uniforms (uBright/uTint) damp to target
      const { A, B } = await grabBurst();
      // rep 1 = the §4 deliverable in docs/orb/ (replaces the old screenshot),
      // rep 2 stays in docs/orb/trace/ as the noise-floor reference.
      fs.writeFileSync(path.join(DOCS_ORB, `${scene}-${bg}.png`), encode(A));
      fs.writeFileSync(path.join(OUT, `${scene}--${bg}--r2.png`), encode(B));
      const trace = await cdp.evaluateJson('JSON.stringify(window.__orbTrace ? window.__orbTrace() : null)');
      rec('applied', { scene, bg, shot: path.relative(ROOT, path.join(DOCS_ORB, `${scene}-${bg}.png`)),
                       applied: trace && trace.applied, weights: trace && trace.weights,
                       uniforms: trace && trace.uniforms, amp: trace && trace.amp,
                       poseLocked: trace && trace.poseLocked, stats: trace && trace.stats });
      await cdp.evaluate('window.__orbUnlockPose && window.__orbUnlockPose()');
      log(`captured ${scene}/${bg} state=${trace && trace.applied && trace.applied.state}`);
      return trace;
    };

    for (const scene of SCENES) {
      for (const bg of BGS) await capture(scene, bg);
    }

    // --- §2 performance: blur cost with it OFF vs ON, plus the idle proof ---
    try {
      const blurPerf = await runBlurPerf(cdp, brain, rec);
      log(`blur perf: idle=${blurPerf.idle.reason} active off=${blurPerf.off.ema.toFixed(1)}ms ` +
          `on=${blurPerf.on.ema.toFixed(1)}ms (+${blurPerf.pctOverhead.toFixed(1)}%)`);
    } catch (e) {
      log('blur perf FAILED:', e && e.message);
      rec('blur_perf_error', { message: String(e && e.message) });
    }

    // --- connection states (client-owned per INTERFACES §e) ----------------
    // Reset the mode first so reconnecting/offline are measured as `normal`
    // (they would otherwise inherit `private` from the previous scene and be
    // indistinguishable from it by construction).
    await cdp.evaluate(`document.body.style.background = ${JSON.stringify(BG_STYLES.dark)}`);
    brain.step('idle');
    await sleep(600);
    // 1) refuse the upgrade entirely -> the orb retries -> 'reconnecting' is
    //    stable for as long as we keep refusing (no race with a 5 s backoff).
    brain.refuseConnections = true;
    brain.dropClients();
    let t = null;
    for (let i = 0; i < 30 && (!t || t.applied.state !== 'reconnecting'); i++) {
      await sleep(300);
      t = await cdp.evaluateJson('JSON.stringify(window.__orbTrace())');
    }
    t = await capture('reconnecting', 'dark', { skipStep: true });
    log('reconnecting state =', t.applied.state);

    // 2) accept the connection but REJECT auth -> fatal auth -> 'offline'
    brain.refuseConnections = false;
    brain.rejectAuth = true;
    let offT = null;
    for (let i = 0; i < 60 && (!offT || offT.applied.state !== 'offline'); i++) {
      await sleep(500);
      offT = await cdp.evaluateJson('JSON.stringify(window.__orbTrace())');
    }
    offT = await capture('offline', 'dark', { skipStep: true });
    log('offline state =', offT.applied.state);

    // --- frame-trace evidence: main-side receive log ------------------------
    const mainRx = await cdp.evaluateJson('window.raphael.traceWs().then(r => JSON.stringify(r))');
    for (const e of mainRx) rec('main_rx', { frame: e.frame, t2: e.t });
    rec('summary', {
      mockSent: brain.sent.length, mockReceived: brain.received.length,
      mainReceived: mainRx.length,
      mockSentTypes: countTypes(brain.sent),
      mainReceivedTypes: countTypes(mainRx.map((e) => e.frame)),
      rendererRxTypes: countTypes(
        (await cdp.evaluateJson('JSON.stringify((window.__orbTrace().rx||[]).map(r=>({type:r.kind})))')) || []),
    });

    fs.writeFileSync(path.join(OUT, 'trace.jsonl'), lines.join('\n') + '\n');
    log(`trace.jsonl written (${lines.length} lines)`);

    // --- distinctness gate ---------------------------------------------------
    const verdict = runDistinctness([DOCS_ORB, OUT], path.join(OUT, 'distinctness.json'));
    log(`distinctness: pass=${verdict.pass} weakest=${verdict.weakest && verdict.weakest.pair
      ? verdict.weakest.pair.join(' vs ') + ' = ' + verdict.weakest.diff.toFixed(2) : 'n/a'}`);

    let failed = false;
    if (!verdict.pass) {
      console.error('[orb-trace] FAIL: two or more states render near-identical');
      failed = true;
    } else {
      log('PASS: every scene renders measurably differently');
    }
    if (startupReport && !startupReport.pass) {
      console.error('[orb-trace] FAIL: startup spin-down assertions did not hold');
      failed = true;
    }
    if (failed) process.exitCode = 1;
  } finally {
    if (cdp) cdp.close();
    if (process.argv.includes('--keep')) {
      log('--keep: leaving mock-brain + orb running');
      return;
    }
    try { orb.kill('SIGTERM'); } catch (e) { /* gone */ }
    await brain.close();
    await sleep(400);
  }
}

function countTypes(frames) {
  const out = {};
  for (const f of frames) {
    const k = (f && f.type) || (f && f.kind) || 'unknown';
    out[k] = (out[k] || 0) + 1;
  }
  return out;
}

main().catch((e) => {
  console.error('[orb-trace] FAILED:', e && e.stack ? e.stack : e);
  process.exit(1);
});

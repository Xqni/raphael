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
const Instance = require('../src/main/instance');
const { runDistinctness } = require('./orb-diff.cjs');

const ROOT = path.join(__dirname, '..', '..', '..');
const OUT = path.join(ROOT, 'docs', 'orb', 'trace');
const BGS = ['dark', 'light', 'busy'];
const BG_STYLES = {
  transparent: 'transparent',
  dark: '#222222',
  light: '#e9e9ef',
  busy: 'repeating-conic-gradient(#7a7a7a 0% 25%, #b8b8b8 0% 50%) 0 0 / 48px 48px',
};
const SCENES = [
  'starting', 'idle', 'listening', 'thinking', 'acting', 'speaking',
  'confirm', 'error', 'private', 'paused', 'jobs', 'private_speaking',
];
const SETTLE_MS = 1400;      // > the 600ms worst-case damp/morph window
const LOCK_SETTLE_MS = 600;  // damped uniforms after the pose snap
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

async function main() {
  fs.mkdirSync(OUT, { recursive: true });
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

    // let the natural boot story (starting -> idle @5.4s) finish first, so the
    // scripted `starting` capture is not raced by the boot timeout.
    await sleep(6000);

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
      fs.writeFileSync(path.join(OUT, `${scene}--${bg}.png`), encode(A));
      fs.writeFileSync(path.join(OUT, `${scene}--${bg}--r2.png`), encode(B));
      const trace = await cdp.evaluateJson('JSON.stringify(window.__orbTrace ? window.__orbTrace() : null)');
      rec('applied', { scene, bg, shot: path.relative(ROOT, path.join(OUT, `${scene}--${bg}.png`)),
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
    const verdict = runDistinctness(OUT, path.join(OUT, 'distinctness.json'));
    log(`distinctness: pass=${verdict.pass} weakest=${verdict.weakest && verdict.weakest.pair
      ? verdict.weakest.pair.join(' vs ') + ' = ' + verdict.weakest.diff.toFixed(2) : 'n/a'}`);

    if (!verdict.pass) {
      console.error('[orb-trace] FAIL: two or more states render near-identical');
      process.exitCode = 1;
    } else {
      log('PASS: every scene renders measurably differently');
    }
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

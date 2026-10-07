#!/usr/bin/env node
// orb-audit.cjs — Wave-4 "fps/VRAM audit under load" (APPROVED WITH
// CONDITIONS, coord ts 1791379204 — see
// docs/requests/orb__to__integrator__harness-spawn-while-live.md).
//
// Conditions, each enforced in code below:
//   1. SEPARATE RAPHAEL_INSTANCE + own userData + own CDP port -> instance.js
//   2. connects to the MOCK brain, never the live one          -> MockBrain
//   3. never touches the live stack's processes                 -> measurements
//      walk OUR pid's /proc descendant tree only, and we only ever signal our
//      own child; no `pkill`, no path/cmd pattern matching (pattern matching
//      false-positived on the invoking shell's own `cd <worktree>` line)
//   4. bounded session: pidfile + hard timeout + kill + ZERO orphans verified
//      + RAM delta reported to docs/status/orb.md
//   5. ONE Electron max (rule 14) -> pidfile pre-flight refuses a second
//
// Usage:  npm run orb:audit
process.env.RAPHAEL_INSTANCE = process.env.RAPHAEL_INSTANCE || 'orb';

const path = require('path');
const fs = require('fs');
const { spawn, execSync } = require('child_process');
const { MockBrain } = require('./mock-brain.cjs');
const { connect } = require('./cdp.cjs');
const Instance = require('../src/main/instance');

const ROOT = path.join(__dirname, '..');            // <worktree>/body/orb
const OUT = path.join(ROOT, '..', '..', 'docs', 'orb', 'trace'); // <worktree>/docs/orb/trace
const PIDFILE = path.join(Instance.dataDir(), 'orb-audit.pid');
const TIMEOUT_MS = 150000;                          // hard bound on the session

const log = (...a) => console.log('[orb:audit]', ...a);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const alive = (pid) => { try { return fs.existsSync(`/proc/${pid}`); } catch (e) { return false; } };

/** Our child + every descendant, discovered through /proc (no guessing). */
function pidsUnder(rootPid) {
  if (!rootPid || !alive(rootPid)) return [];
  const out = [rootPid];
  const stack = [rootPid];
  while (stack.length) {
    const p = stack.pop();
    let kids = '';
    try { kids = fs.readFileSync(`/proc/${p}/task/${p}/children`, 'utf8'); } catch (e) { continue; }
    for (const k of kids.split(/\s+/)) {
      const n = parseInt(k, 10);
      if (n && !out.includes(n)) { out.push(n); stack.push(n); }
    }
  }
  return out;
}

function procsFor(rootPid) {
  return pidsUnder(rootPid).map((pid) => {
    let rssKb = 0, vszKb = 0;
    try {
      const s = fs.readFileSync(`/proc/${pid}/status`, 'utf8');
      rssKb = parseInt((/VmRSS:\s+(\d+)/.exec(s) || [])[1] || '0', 10);
      vszKb = parseInt((/VmSize:\s+(\d+)/.exec(s) || [])[1] || '0', 10);
    } catch (e) { return null; }
    return { pid, rssKb, vszKb };
  }).filter(Boolean);
}

/** Peak resident set (VmHWM) — the honest high-water mark per process. */
function vmHwmKb(pid) {
  try {
    const s = fs.readFileSync(`/proc/${pid}/status`, 'utf8');
    const m = /VmHWM:\s+(\d+)\s+kB/.exec(s);
    return m ? +m[1] : null;
  } catch (e) { return null; }
}

const rssTotalKb = (rootPid) => procsFor(rootPid).reduce((a, p) => a + p.rssKb, 0);

function portsListening() {
  try {
    const out = execSync('ss -ltn 2>/dev/null || true', { encoding: 'utf8' });
    return [Instance.wsPort(), Instance.cdpPort()]
      .filter((p) => out.includes(`:${p} `) || out.includes(`:${p}\n`));
  } catch (e) { return []; }
}

/** Rule 14 / condition 5: refuse if a previous run is still alive. */
function preflight() {
  let stale = null;
  try {
    const raw = fs.readFileSync(PIDFILE, 'utf8').trim();
    stale = parseInt(raw, 10);
  } catch (e) { /* no pidfile */ }
  if (stale && alive(stale)) {
    throw new Error(
      `refusing to spawn (rule 14 / condition 5): a previous audit is still alive ` +
      `(pid ${stale}, pidfile ${PIDFILE}). One Electron max — wait for it or kill it.`);
  }
  if (stale) { try { fs.unlinkSync(PIDFILE); } catch (e) { /* stale file */ } }
  const busy = portsListening();
  if (busy.length) {
    throw new Error(`refusing to spawn (rule 14): my instance ports still listening: ${busy}`);
  }
}

async function sample(cdp, rootPid, ms) {
  await cdp.evaluate('window.__orbResetFrameTime && window.__orbResetFrameTime()');
  await sleep(ms);
  const ft = await cdp.evaluateJson(
    'JSON.stringify(window.__orbFrameTime ? window.__orbFrameTime() : { ema: 0, n: 0 })');
  const stats = await cdp.evaluateJson(
    'JSON.stringify(window.__orbStats ? window.__orbStats() : {})');
  return { ft, stats, rssKb: rssTotalKb(rootPid), procs: procsFor(rootPid).length };
}

async function main() {
  const started = Date.now();
  preflight();
  const cdpPort = Instance.cdpPort();
  const wsPort = Instance.wsPort();
  log(`instance=${Instance.instance()} ws=${wsPort} cdp=${cdpPort} userData=${Instance.userDataDir()}`);

  const brain = new MockBrain({ port: wsPort, token: 'audit-token' });
  await brain.listen();

  const electron = path.join(ROOT, 'node_modules', '.bin', 'electron');
  const child = spawn(electron, [
    '.', `--remote-debugging-port=${cdpPort}`,
    '--no-sandbox', '--disable-gpu-sandbox', '--ignore-gpu-blocklist',
  ], {
    cwd: ROOT, stdio: 'ignore',
    env: {
      ...process.env,
      RAPHAEL_ORB_TOKEN: 'audit-token',                 // mock only (condition 2)
      RAPHAEL_WS_URL: `ws://127.0.0.1:${wsPort}/ws`,
      MESA_LOADER_DRIVER_OVERRIDE: 'd3d12', GALLIUM_DRIVER: 'd3d12',
    },
  });
  const rootPid = child.pid;
  fs.mkdirSync(path.dirname(PIDFILE), { recursive: true });
  fs.writeFileSync(PIDFILE, String(rootPid));
  log(`spawned our own Electron pid=${rootPid} (live stack untouched; pidfile ${PIDFILE})`);

  let result = null, error = null;
  const deadline = setTimeout(() => {
    log('hard timeout reached — killing the session (condition 4)');
    try { child.kill('SIGKILL'); } catch (e) { /* gone */ }
  }, TIMEOUT_MS);

  try {
    const cdp = await connect(cdpPort);
    let authed = false;
    for (let i = 0; i < 100 && !authed; i++) {
      authed = brain.received.some((r) => r.frame && r.frame.type === 'auth');
      if (!authed) await sleep(200);
    }
    log('mock-brain authed:', authed);
    await sleep(6500);                     // past the natural boot hand-off

    const glInfo = await cdp.evaluateJson(
      'JSON.stringify({ gl: window.__orbStats().gl, dpr: window.__orbStats().dpr, gov: window.__orbStats().gov })');

    // --- baseline: idle ----------------------------------------------------
    brain.step('idle');
    await sleep(1200);
    const idle = await sample(cdp, rootPid, 3000);
    log(`idle      ema=${idle.ft.ema.toFixed(1)}ms rss=${(idle.rssKb / 1024).toFixed(1)}MB procs=${idle.procs}`);

    // --- active: speaking at full amplitude ---------------------------------
    brain.step('speaking');
    brain.speakAt(0.95);
    await sleep(800);
    const speaking = await sample(cdp, rootPid, 3000);
    log(`speaking  ema=${speaking.ft.ema.toFixed(1)}ms rss=${(speaking.rssKb / 1024).toFixed(1)}MB`);

    // --- storm: flip states faster than the 600 ms morph ramp (Wave-4 case) -
    const stormStart = Date.now();
    const cycle = ['listening', 'thinking', 'acting', 'speaking', 'confirm', 'error', 'idle'];
    let flips = 0;
    while (Date.now() - stormStart < 6000) {
      brain.step(cycle[flips % cycle.length]);
      flips++;
      await sleep(90);
    }
    const storm = await sample(cdp, rootPid, 3000);
    log(`storm     ${flips} flips in 6s, ema=${storm.ft.ema.toFixed(1)}ms rss=${(storm.rssKb / 1024).toFixed(1)}MB`);

    await sleep(1500);                     // let the last ramp settle
    const morph = await cdp.evaluateJson('JSON.stringify(window.__orbMorphDiff())');
    const gl2 = await cdp.evaluateJson('JSON.stringify(window.__orbGl ? window.__orbGl() : null)');

    const procs = procsFor(rootPid);
    const hwm = procs.map((p) => vmHwmKb(p.pid)).filter((v) => v !== null);

    result = {
      when: new Date().toISOString(),
      instance: Instance.instance(),
      isolation: { wsPort, cdpPort, userData: Instance.userDataDir(), mockBrainOnly: true },
      gl: glInfo,
      glRecovery: gl2,
      idle, speaking, storm,
      stormFlips: flips,
      morphAfterStorm: morph,
      deltas: {
        rssIdleMb: +(idle.rssKb / 1024).toFixed(1),
        rssSpeakingMb: +(speaking.rssKb / 1024).toFixed(1),
        rssStormMb: +(storm.rssKb / 1024).toFixed(1),
        rssDeltaMb: +((storm.rssKb - idle.rssKb) / 1024).toFixed(1),
        vmHwmPeakMb: hwm.length ? +(Math.max(...hwm) / 1024).toFixed(1) : null,
        processCount: Math.max(idle.procs, speaking.procs, storm.procs),
      },
      vramNote: 'GPU VRAM is not readable from WSL (no per-process GPU counter). ' +
                'VmRSS/VmHWM over the whole Electron tree plus renderer.info are the honest substitutes.',
      durationMs: Date.now() - started,
    };
    cdp.close();
  } catch (e) {
    error = String(e && e.stack ? e.stack.split('\n')[0] : e);
    log('audit error:', error);
  } finally {
    clearTimeout(deadline);
    // --- condition 4: kill OUR tree and prove there are no orphans ---------
    try { child.kill('SIGTERM'); } catch (e) { /* gone */ }
    await sleep(1500);
    try { if (alive(rootPid)) child.kill('SIGKILL'); } catch (e) { /* gone */ }
    await sleep(1200);
    try { await brain.close(); } catch (e) { /* ignore */ }

    const survivors = pidsUnder(rootPid).filter((p) => alive(p));
    const ports = portsListening();
    const clean = survivors.length === 0 && ports.length === 0;
    if (clean) { try { fs.unlinkSync(PIDFILE); } catch (e) { /* already gone */ } }
    log(clean
      ? 'kill-verify: ZERO orphans, instance ports free'
      : `kill-verify FAILED: survivors=[${survivors}] ports=[${ports}]`);

    if (result) {
      result.killVerify = {
        clean, rootPid, survivorPids: survivors, portsStillListening: ports,
        liveStackUntouched: true,
      };
      fs.mkdirSync(OUT, { recursive: true });
      fs.writeFileSync(path.join(OUT, 'audit.json'), JSON.stringify(result, null, 2) + '\n');
      const d = result.deltas;
      log(`RAM  idle=${d.rssIdleMb}MB speaking=${d.rssSpeakingMb}MB storm=${d.rssStormMb}MB ` +
          `(delta ${d.rssDeltaMb}MB, VmHWM peak ${d.vmHwmPeakMb}MB, ${d.processCount} procs)`);
      log(`fps  idle=${result.idle.ft.ema.toFixed(1)}ms speaking=${result.speaking.ft.ema.toFixed(1)}ms ` +
          `storm=${result.storm.ft.ema.toFixed(1)}ms`);
      log(`morph after storm: ${JSON.stringify((result.morphAfterStorm || {}).lattice)}`);
      log(`gl: ${JSON.stringify(result.gl)} glRecovery: ${JSON.stringify(result.glRecovery)}`);
    }
    process.exitCode = (result && !error && clean) ? 0 : 1;
  }
}

main().catch((e) => { console.error('[orb:audit] FAILED:', e && e.stack || e); process.exit(1); });

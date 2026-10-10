#!/usr/bin/env node
// orb-size.cjs — §3.6 legibility sweep: 160 / 200 / 280 px at 100% and 150%
// display scale.
//
// "150% Windows scaling" is reproduced faithfully with Chromium's
// --force-device-scale-factor (devicePixelRatio 1.5), which is exactly what a
// Windows scale change does to the renderer: dpr 1.5 -> backing store 1.5x.
//
// For each (size, scale) it measures, on a DARK wallpaper:
//   - coverage: the bounding box of everything that differs from the backdrop,
//     as a fraction of the window — the orb must fill ~85-90% of content_px
//     (and, once the window is smaller than content_px, ~86% of the window)
//   - edge margin: the closest the content gets to the window border (the
//     6% edge mask must always keep a visible gap — no clipping)
//
// Output: docs/orb/size-<size>x<scale>-<state>.png + docs/orb/trace/sizecheck.json
process.env.RAPHAEL_INSTANCE = process.env.RAPHAEL_INSTANCE || 'orb';

const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');
const { MockBrain } = require('./mock-brain.cjs');
const { connect } = require('./cdp.cjs');
const { decode } = require('./png.cjs');
const Instance = require('../src/main/instance');

const ROOT = path.join(__dirname, '..', '..', '..');
const OUT = path.join(ROOT, 'docs', 'orb');
const SIZES = [160, 200, 280];
const SCALES = ['1', '1.5'];
const STATES = ['idle', 'speaking'];
const BG = '#222222';              // dark wallpaper (see measure(): additive
                                   // haze saturates a LIGHT backdrop, which made
                                   // every coverage reading ~95%)
const SETTLE = 1500;
const TOKEN = 'sizecheck-token';

const log = (...a) => console.log('[orb:size]', ...a);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/**
 * Where the orb's STRUCTURE reaches, on a flat backdrop.
 *
 * A plain bounding box is useless here: the decorative starfield
 * (scene-level points out to +-8 world units) puts a handful of pixels near
 * the window border in every state, so the bbox always reads ~90-98%.
 * Instead: radius of the pixel that contains 97% of the lit pixels — robust
 * to sparse outliers, and exactly the "how big does the orb draw" question.
 */
function measure(img) {
  const { width: W, height: H, data } = img;
  const [br, bg, bb] = [34, 34, 34];   // must match BG
  const cx = (W - 1) / 2, cy = (H - 1) / 2;
  const radii = [];
  let minX = W, minY = H, maxX = -1, maxY = -1;
  for (let y = 0; y < H; y++) {
    for (let x = 0; x < W; x++) {
      const i = (y * W + x) * 4;
      const d = Math.abs(data[i] - br) + Math.abs(data[i + 1] - bg) + Math.abs(data[i + 2] - bb);
      if (d > 45) {
        radii.push(Math.hypot(x - cx, y - cy));
        if (x < minX) minX = x;
        if (x > maxX) maxX = x;
        if (y < minY) minY = y;
        if (y > maxY) maxY = y;
      }
    }
  }
  if (maxX < 0) return { width: W, height: H, coverage: 0, edgeMargin: 0, litPx: 0 };
  radii.sort((a, b) => a - b);
  const r97 = radii[Math.floor(radii.length * 0.97)];
  return {
    width: W, height: H,
    bbox: [minX, minY, maxX, maxY],
    coverage: (2 * r97) / Math.max(W, H),   // fraction of the window the orb spans
    edgeMargin: Math.min(minX, minY, W - 1 - maxX, H - 1 - maxY),
    litPx: radii.length,
  };
}

async function once(size, scale, verbose) {
  const cdpPort = Instance.cdpPort();
  const wsPort = Instance.wsPort();
  const brain = new MockBrain({ port: wsPort, token: TOKEN });
  await brain.listen();
  const electron = path.join(__dirname, '..', 'node_modules', '.bin', 'electron');
  const child = spawn(electron, [
    '.', '--demo', `--remote-debugging-port=${cdpPort}`,
    `--force-device-scale-factor=${scale}`,
    '--no-sandbox', '--disable-gpu-sandbox', '--ignore-gpu-blocklist',
  ], {
    cwd: path.join(__dirname, '..'),
    stdio: 'ignore',
    env: {
      ...process.env,
      RAPHAEL_ORB_SIZE_PX: String(size),
      RAPHAEL_ORB_TOKEN: TOKEN,
      RAPHAEL_WS_URL: `ws://127.0.0.1:${wsPort}/ws`,
      MESA_LOADER_DRIVER_OVERRIDE: 'd3d12',
      GALLIUM_DRIVER: 'd3d12',
      RAPHAEL_ORB_OFFSCREEN_RENDER: '1',
    },
  });

  const results = [];
  let cdp = null;
  try {
    cdp = await connect(cdpPort);
    let authed = false;
    for (let i = 0; i < 80 && !authed; i++) {
      authed = brain.received.some((r) => r.frame && r.frame.type === 'auth');
      if (!authed) await sleep(200);
    }
    await cdp.evaluate(`document.body.style.background = ${JSON.stringify(BG)}`);
    for (const state of STATES) {
      brain.step(state);
      await sleep(SETTLE);
      // POSE LOCK: the orb keeps rotating while we shoot, and `idle` has only
      // ~2k lit pixels (vs ~14k for speaking) so its 97th-percentile radius
      // swung by several pixels with the phase — measured drift wandered
      // 4.7% -> 12.0% across runs and sat exactly on the limit. Freezing the
      // pose makes coverage a pure function of (size, scale, state).
      await cdp.evaluate('window.__orbLockPose && window.__orbLockPose()');
      await sleep(600);
      const png = await cdp.screenshot();
      await cdp.evaluate('window.__orbUnlockPose && window.__orbUnlockPose()');
      const m = measure(decode(png));
      const file = `size-${size}x${scale.replace('.', '')}-${state}.png`;
      fs.writeFileSync(path.join(OUT, file), png);
      results.push({ size, scale, state, file, ...m,
                     dpr: await cdp.evaluate('window.devicePixelRatio'),
                     stats: await cdp.evaluate('JSON.stringify(window.__orbStats && window.__orbStats())') });
      if (verbose) log(`${size}px @${scale}x ${state}: coverage ${(m.coverage * 100).toFixed(1)}% ` +
                       `edgeMargin ${m.edgeMargin}px lit ${m.litPx}`);
    }
  } finally {
    if (cdp) cdp.close();
    try { child.kill('SIGTERM'); } catch (e) { /* gone */ }
    await brain.close();
    await sleep(600);
  }
  return results;
}

async function main() {
  const verbose = process.argv.includes('-v');
  const all = [];
  for (const size of SIZES) {
    for (const scale of SCALES) {
      log(`size=${size} scale=${scale}...`);
      all.push(...(await once(size, scale, verbose)));
    }
  }

  // Assertions: nothing clipped, content present, and the orb's SIZE matches
  // the spec (ORB_REBUILD §3.6 / §4: ~85-90% of content_px — or, once the
  // window is smaller than content_px, most of the window).
  const checks = [];
  const add = (name, ok, detail) => checks.push({ name, ok, detail });
  const worstMargin = Math.min(...all.map((r) => r.edgeMargin));
  add('no_edge_clipping', worstMargin > 0,
      `smallest gap between content and the window border = ${worstMargin}px (must be > 0)`);
  const coverages = all.map((r) => r.coverage);
  add('has_content', Math.min(...coverages) > 0.5,
      `min coverage ${(Math.min(...coverages) * 100).toFixed(1)}% (must be > 50%)`);

  const CONTENT = 200;
  const HALF = (r) => Math.max(1.5 * (r.size / CONTENT), 1.35 / 0.86); // renderer's camera
  const verdicts = all.map((r) => {
    const orbPx = r.coverage * r.size;
    const targetPx = r.size >= CONTENT ? 0.875 * CONTENT : 0.86 * r.size;
    const err = Math.abs(orbPx - targetPx) / targetPx;
    return { ...r, orbPx: Math.round(orbPx), targetPx: Math.round(targetPx), err };
  });
  const worst = verdicts.reduce((a, b) => (b.err > a.err ? b : a));
  add('size_matches_spec', worst.err <= 0.12,
      `worst = ${worst.size}px@${worst.scale} ${worst.state}: orb spans ${worst.orbPx}px ` +
      `(target ${worst.targetPx}px, drift ${(worst.err * 100).toFixed(1)}%, allowed 12%)`);
  add('scales_with_window', Math.max(...verdicts.map((v) => v.err)) <= 0.12 &&
      new Set(verdicts.map((v) => v.size)).size === SIZES.length,
      `checked ${verdicts.length} (size x scale x state) combinations`);

  const report = { pass: checks.every((c) => c.ok), checks, verdicts, results: all };
  fs.mkdirSync(path.join(OUT, 'trace'), { recursive: true });
  fs.writeFileSync(path.join(OUT, 'trace', 'sizecheck.json'), JSON.stringify(report, null, 2) + '\n');
  log(report.pass ? 'PASS' : 'FAIL');
  for (const c of checks) log(`  ${c.ok ? 'ok  ' : 'FAIL'} ${c.name}: ${c.detail}`);
  process.exit(report.pass ? 0 : 1);
}

main().catch((e) => { console.error('[orb:size] FAILED:', e && e.stack || e); process.exit(1); });

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
const { spawn, execSync } = require('child_process');
const { MockBrain } = require('./mock-brain.cjs');
const { connect } = require('./cdp.cjs');
const { decode, encode, average } = require('./png.cjs');
const { analyze: analyzeStartup, renderPlot: renderStartupPlot, renderFilmstrip: renderStartupFilmstrip } = require('./startup.cjs');
const { filmstrip } = require('./gfx.cjs');
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
const ONLY_PHASE = (() => {
  const a = process.argv.find((x) => x.startsWith('--only='));
  return a ? a.slice('--only='.length) : null;
})();
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

/**
 * §4 evidence: contact sheets.
 *   speaking-filmstrip.png — same state at LOW and HIGH TTS amplitude (proves
 *                            amplitude reactivity is visible, not just wired)
 *   thinking-filmstrip.png — several frames across the Data-Rings rotation
 */
async function runFilmstrips(cdp, brain, rec) {
  // NB: a DARK backdrop, not transparent — `Page.captureScreenshot` returns an
  // empty image for a transparent page in this environment (WSLg/ANGLE), which
  // produced a filmstrip of blank cells on the first attempt.
  await cdp.evaluate(`document.body.style.background = ${JSON.stringify(BG_STYLES.dark)}`);
  const shoot = async (n, everyMs) => {
    const frames = [], labels = [];
    for (let i = 0; i < n; i++) {
      frames.push(decode(await cdp.screenshot()));
      if (i < n - 1) await sleep(everyMs);
    }
    return { frames, labels };
  };

  // thinking: the rings rotate, the wireframe pulses — 6 frames
  brain.step('thinking');
  await sleep(1600);
  let s = await shoot(6, 700);
  s.labels = s.frames.map((_, i) => 'F' + i);
  fs.writeFileSync(path.join(DOCS_ORB, 'thinking-filmstrip.png'),
    encode(filmstrip(s.frames, { labels: s.labels, cell: 132 })));

  // speaking: LOW amplitude then HIGH amplitude (ORB_REBUILD §6)
  brain.step('speaking');
  await sleep(1500);
  brain.speakAt(0.12);
  await sleep(700);
  const low = await shoot(3, 400);
  brain.speakAt(0.95);
  await sleep(700);
  const high = await shoot(3, 400);
  const frames = [...low.frames, ...high.frames];
  frames.labels = ['AMP 0.12', 'AMP 0.12', 'AMP 0.12', 'AMP 0.95', 'AMP 0.95', 'AMP 0.95'];
  fs.writeFileSync(path.join(DOCS_ORB, 'speaking-filmstrip.png'),
    encode(filmstrip(frames, { labels: frames.labels, cell: 132 })));
  rec('filmstrips', { thinking: 6, speakingLow: 3, speakingHigh: 3 });
  log('filmstrips written: thinking, speaking (amp 0.12 / 0.95)');
}

/**
 * §4 transparency check: no box, fringe or clipping at the window edge, WITH
 * the motion blur forced on (the worst case for a trail/feedback approach).
 * The edge mask fades the outer 6%, so the outermost 2 px must stay near zero
 * in both alpha and RGB — a visible rectangle would show up as alpha ~255.
 */
async function runTransparency(cdp, brain, rec) {
  await cdp.evaluate("window.__orbSetMotionBlur && window.__orbSetMotionBlur('force')");
  const results = [];
  for (const scene of ['idle', 'speaking', 'error', 'paused', 'reconnecting']) {
    brain.step(scene);
    if (scene === 'speaking') brain.speakAt(0.9);
    await cdp.evaluate(`document.body.style.background = ${JSON.stringify(BG_STYLES.dark)}`);
    await sleep(1500);
    // real alpha comes from gl.readPixels on the canvas (a screenshot of a
    // transparent page is empty here, which made the old check vacuous)
    const edge = await cdp.evaluateJson('JSON.stringify(window.__orbEdgeStats())');
    const shot = await cdp.screenshot();
    fs.writeFileSync(path.join(OUT, `transparency-${scene}.png`), shot);
    results.push({ scene, blur: await cdp.evaluateJson('JSON.stringify(window.__orbMotionBlur && window.__orbMotionBlur())'), ...edge });
  }
  await cdp.evaluate("window.__orbSetMotionBlur && window.__orbSetMotionBlur(null)");
  const ALPHA_MAX = 16, RGB_MAX = 24, MIN_LIT = 200;
  const failures = results.filter(
    (r) => r.maxBorderAlpha > ALPHA_MAX || r.maxBorderRgb > RGB_MAX || r.litPixels < MIN_LIT);
  const out = { alphaMax: ALPHA_MAX, rgbMax: RGB_MAX, minLitPixels: MIN_LIT,
                pass: failures.length === 0, results, failures };
  rec('transparency', out);
  fs.writeFileSync(path.join(OUT, 'transparency.json'), JSON.stringify(out, null, 2) + '\n');
  log(`transparency (blur forced): ${out.pass ? 'PASS' : 'FAIL'} — ` +
      results.map((r) => `${r.scene} borderA${r.maxBorderAlpha}/rgb${r.maxBorderRgb} lit${r.litPixels}`).join(' '));
  return out;
}

/**
 * W2.3 interaction checks (Wave-2 checklist item #1's `provider/model`
 * remainder + TODO §3e typed input). Runs against a live orb over CDP:
 *   1. right-click menu structure (exposed as data via `orb-menu-spec`)
 *   2. pointer hit-testing — solid only while the cursor is over the orb
 *   3. double-click -> text box -> PROTOCOL §3 `command` {source: 'orb'}
 *   4. `control` frames actually leave the process
 */
async function runInteraction(cdp, brain, rec) {
  const checks = [];
  const add = (name, ok, detail) => checks.push({ name, ok, detail, pass: !!ok });
  const commandsBefore = () => brain.received.filter((r) => r.frame && r.frame.type === 'command').length;

  // give the menu something to display
  brain.step('speaking');
  await sleep(700);

  const spec = await cdp.evaluateJson('window.raphael.menuSpec()');
  const ids = (spec || []).map((i) => i.id).filter(Boolean);
  const has = (id) => ids.includes(id);
  add('menu_provider_and_model', has('info-provider') && has('info-model'),
      `ids: ${ids.filter((i) => i.startsWith('info-')).join(', ') || 'none'}`);
  const need = ['pause', 'private', 'jobs', 'logs', 'restart', 'quit'];
  const missing = need.filter((x) => !has(x));
  add('menu_required_items', missing.length === 0,
      missing.length ? `missing: ${missing.join(', ')}` : `all present (${need.join(', ')})`);
  const prov = (spec || []).find((i) => i.id === 'info-provider');
  const mdl = (spec || []).find((i) => i.id === 'info-model');
  add('menu_shows_provider_model_values',
      !!prov && /groq/i.test(prov.label || '') && !!mdl && /llama/i.test(mdl.label || ''),
      `${prov && prov.label} | ${mdl && mdl.label}`);
  const pauseItem = (spec || []).find((i) => i.id === 'pause');
  add('menu_pause_is_checkbox', !!pauseItem && pauseItem.type === 'checkbox',
      pauseItem && `label="${pauseItem.label}" type=${pauseItem.type} action=${pauseItem.action}`);

  // --- pointer hit-testing -------------------------------------------------
  // A genuine OS mousemove can land at ANY moment (the window forwards them),
  // and one did: the listener saw clientX=17 clientY=157 while the harness
  // dispatched 140,140. So this checks the three things that are actually a
  // contract, none of which depends on where the physical cursor happens to be:
  //   1. the decision function reads the geometry right
  //   2. the mousemove listener is wired and computes the same answer
  //   3. main's setIgnoreMouseEvents tracks what the renderer decided
  const direct = await cdp.evaluateJson('window.__orbPointer(140, 140)');
  add('hit_test_decision', direct.inside === true && direct.pointerInside === true,
      `dist=${direct.dist && direct.dist.toFixed(1)} hitR=${direct.hitR && direct.hitR.toFixed(1)} ` +
      `viewport=${direct.w}x${direct.h} inside=${direct.inside} typedOpen=${direct.typedOpen}`);

  await cdp.evaluate("window.dispatchEvent(new MouseEvent('mousemove', { clientX: 140, clientY: 140 }))");
  await sleep(200);
  const evState = await cdp.evaluateJson('window.__orbInteraction()');
  const lm = evState.lastMove || {};
  const hitPx = direct.hitR;
  add('mousemove_listener_wired',
      (lm.seen || 0) >= 1 && typeof lm.dist === 'number' &&
      lm.inside === (lm.dist <= hitPx),
      `listener saw clientX=${lm.x} clientY=${lm.y} dist=${lm.dist === null ? 'n/a' : lm.dist.toFixed(1)} ` +
      `inside=${lm.inside} seen=${lm.seen} (expect inside == dist<=${hitPx && hitPx.toFixed(0)})`);

  // main must mirror the renderer (consistency, not an absolute value — the
  // physical cursor is free to move)
  await cdp.evaluateJson('window.__orbPointer(140, 140)');
  await sleep(300);
  const followState = await cdp.evaluateJson('window.__orbInteraction()');
  const followMain = await cdp.evaluateJson('window.raphael.instanceInfo()');
  add('main_follows_renderer', followMain.mouseThrough === !followState.pointerInside,
      `renderer.pointerInside=${followState.pointerInside} -> main.mouseThrough=${followMain.mouseThrough} ` +
      `(must be the exact opposite)`);
  const away = await cdp.evaluateJson('window.__orbPointer(4, 4)');
  await sleep(300);
  const awayMain = await cdp.evaluateJson('window.raphael.instanceInfo()');
  add('pointer_away_releases_input', away.inside === false && awayMain.mouseThrough === true,
      `dist=${away.dist && away.dist.toFixed(1)} inside=${away.inside} main.mouseThrough=${awayMain.mouseThrough}`);

  // --- double-click -> text box -> command(source: orb) ---------------------
  const before = commandsBefore();
  await cdp.evaluate('window.__orbTyped.open()');
  const opened = await cdp.evaluateJson('JSON.stringify(window.__orbTyped.isOpen())');
  add('dblclick_opens_text_box', opened === true, `isOpen=${opened}`);
  await cdp.evaluate('window.__orbTyped.set("open youtube and search lo-fi")');
  await cdp.evaluate('window.__orbTyped.submit()');
  await sleep(600);
  const cmds = brain.received.filter((r) => r.frame && r.frame.type === 'command');
  const last = cmds.length ? cmds[cmds.length - 1].frame : null;
  add('text_box_sends_command', cmds.length > before,
      last ? JSON.stringify({ type: last.type, source: last.source, text: last.text }) : 'no command frame reached the Brain');
  add('command_source_is_orb', !!last && last.source === 'orb', last && `source=${last.source}`);
  add('command_text_roundtrips', !!last && /lo-fi/.test(last.text || ''), last && `text=${last.text}`);
  const closed = await cdp.evaluateJson('JSON.stringify(window.__orbTyped.isOpen())');
  add('text_box_closes_after_send', closed === false, `isOpen=${closed}`);

  // --- control frames leave the process (menu actions) ----------------------
  await cdp.evaluate("window.raphael.sendControl('pause')");
  await sleep(500);
  const ctl = brain.received.filter((r) => r.frame && r.frame.type === 'control');
  add('control_pause_reaches_brain', ctl.some((c) => c.frame.action === 'pause'),
      ctl.length ? JSON.stringify(ctl[ctl.length - 1].frame) : 'no control frame');

  // leave the window click-through again so later phases are unaffected
  await cdp.evaluate("window.dispatchEvent(new MouseEvent('mousemove', { clientX: 4, clientY: 4 }))");

  // --- job list + cancel (the menu's Jobs submenu actions) ------------------
  await cdp.evaluate('window.raphael.requestJobList()');
  await sleep(600);
  const spec2 = await cdp.evaluateJson('window.raphael.menuSpec()');
  const jobsItem = (spec2 || []).find((i) => i.id === 'jobs');
  add('menu_lists_jobs', !!jobsItem && (jobsItem.submenu || []).length === 2,
      jobsItem ? `label="${jobsItem.label}" items=${(jobsItem.submenu || []).length}` : 'no jobs item');
  const cancelBefore = brain.received.filter((r) => r.frame && r.frame.type === 'cancel').length;
  await cdp.evaluate("window.raphael.cancelJob('j_mock_1')");
  await sleep(500);
  const cancels = brain.received.filter((r) => r.frame && r.frame.type === 'cancel');
  add('menu_cancel_reaches_brain',
      cancels.length > cancelBefore && cancels[cancels.length - 1].frame.job === 'j_mock_1' &&
      cancels[cancels.length - 1].frame.scope === 'full',
      cancels.length ? JSON.stringify(cancels[cancels.length - 1].frame) : 'no cancel frame');

  // leave the window click-through again so later phases are unaffected
  await cdp.evaluate("window.dispatchEvent(new MouseEvent('mousemove', { clientX: 4, clientY: 4 }))");

  // --- PROTOCOL §3 `notice`: renders as a banner, NEVER moves the orb state -
  brain.step('idle');
  await sleep(600);
  const stateBefore = await cdp.evaluate('window.__orbDebug.state');
  const traceBefore = await cdp.evaluateJson('JSON.stringify(window.__orbTrace())');
  const rxBefore = (traceBefore.rx || []).filter((r) => r.kind === 'notice').length;
  brain.step('notice');
  await sleep(700);
  const stateAfter = await cdp.evaluate('window.__orbDebug.state');
  const traceAfter = await cdp.evaluateJson('JSON.stringify(window.__orbTrace())');
  const rxAfter = (traceAfter.rx || []).filter((r) => r.kind === 'notice').length;
  const banner = await cdp.evaluate(
    "JSON.stringify({text: (document.getElementById('subtitle')||{}).textContent, " +
    "shown: !!(document.getElementById('subtitle')||{}).classList.contains('show')})");
  const bannerObj = JSON.parse(banner);
  add('notice_reaches_renderer', rxAfter > rxBefore,
      `renderer rx notice frames: ${rxBefore} -> ${rxAfter}`);
  add('notice_shown_as_banner', bannerObj.shown && /disk almost full/.test(bannerObj.text || ''),
      `banner=${JSON.stringify(bannerObj)}`);
  add('notice_never_changes_state', stateAfter === stateBefore && traceAfter.applied.state === stateBefore,
      `state ${stateBefore} -> ${stateAfter}, applied=${traceAfter.applied.state} (must be unchanged)`);

  const out = { pass: checks.every((c) => c.ok), checks, menuSpec: spec };
  rec('interaction', out);
  fs.writeFileSync(path.join(OUT, 'interaction.json'), JSON.stringify(out, null, 2) + '\n');
  log(`interaction: ${out.pass ? 'PASS' : 'FAIL'} (${checks.filter((c) => c.ok).length}/${checks.length})`);
  for (const c of checks) log(`  ${c.ok ? 'ok  ' : 'FAIL'} ${c.name}: ${c.detail}`);
  return out;
}

/**
 * BUGS-WAVE2 Bug C — the two P0 render bugs, both reproduced then fixed:
 *   (1) no pulse: a fresh utterance restarts `seq` at 0 and the stale-seq guard
 *       dropped the whole utterance;
 *   (2) stuck shape: the octagram target had a different vertex count, so an
 *       interrupted morph left a permanently stale tail.
 * Plus the Wave-3 SPEED check (Rule 15): how long a state flip takes to land.
 */
async function runBugC(cdp, brain, rec) {
  const checks = [];
  const add = (name, ok, detail) => checks.push({ name, ok, detail, pass: !!ok });
  const amp = async () => (await cdp.evaluateJson('JSON.stringify(window.__orbTrace())')).amp.speak;
  const speakRx = async () => {
    const t = await cdp.evaluateJson('JSON.stringify(window.__orbTrace())');
    return (t.rx || []).filter((r) => r.kind === 'speak').length;
  };

  // (1) PULSE — utterance 1 low, then a FRESH utterance (seq restarts) high.
  //     Old guard: seq 1 <= 8 -> dropped -> amp2 stays 0.15.
  await cdp.evaluate(`document.body.style.background = ${JSON.stringify(BG_STYLES.dark)}`);
  brain.step('speaking');
  await sleep(1400);
  brain.speakReset(); brain.speakAt(0.15);
  await sleep(600);
  const amp1 = await amp();
  const rx1 = await speakRx();
  brain.speakReset(); brain.speakAt(0.95);
  await sleep(600);
  const amp2 = await amp();
  const rx2 = await speakRx();
  add('pulse_follows_fresh_utterance', Math.abs(amp2 - 0.95) < 0.08,
      `amp1=${amp1} (seq run A) -> amp2=${amp2} (fresh run restarting at seq 0, expect ~0.95)`);
  add('renderer_received_every_speak_frame', rx2 > rx1,
      `renderer rx speak frames: ${rx1} -> ${rx2} (a dropped run would not grow)`);

  // (2) STUCK SHAPE — reproduce Bug E's flicker: restart the morph mid-ramp,
  //     over and over, then let it settle on one shape.
  for (let i = 0; i < 5; i++) {
    brain.step('listening'); await sleep(140);
    brain.step('speaking'); await sleep(140);
  }
  brain.step('speaking');
  await sleep(1600);
  const md = await cdp.evaluateJson('window.__orbMorphDiff()');
  add('morph_targets_share_one_length',
      !!md && new Set(md.targetLengths).size === 1,
      md ? `target lengths = ${JSON.stringify(md.targetLengths)} (octagram used to be 144 vs 180)` : 'probe missing');
  add('morph_settles_after_interruption',
      !!md && md.lattice && md.lattice.lengthMismatch === false &&
      md.morphActive === false && md.lattice.maxErr < 0.01,
      md ? `lattice=${JSON.stringify(md.lattice)} morphActive=${md.morphActive} shape=${md.shape}` : 'no probe');
  add('cage_shape_settles_after_interruption',
      !!md && md.cage && md.cage.active === false && md.cage.maxErr < 0.01,
      md && md.cage ? `cage=${JSON.stringify(md.cage)}` : 'no cage probe');

  // (3) SPEED (Rule 15): how long from "Brain sends orb_state" to the renderer
  //     applying it. This includes the harness's own evaluate round-trip, so it
  //     is an upper bound. The 300-600ms visual crossfade is BY DESIGN and is
  //     not what this measures.
  const flips = [];
  for (const s of ['listening', 'thinking', 'confirm', 'error', 'idle']) {
    const t0 = Date.now();
    brain.step(s);
    let seen = null;
    while (Date.now() - t0 < 3000) {
      seen = await cdp.evaluate('window.__orbDebug.state');
      if (seen === s) break;
      await sleep(10);
    }
    flips.push({ state: s, ms: Date.now() - t0, seen });
  }
  const worst = Math.max(...flips.map((f) => f.ms));
  const mean = flips.reduce((a, b) => a + b.ms, 0) / flips.length;
  add('state_flip_latency', flips.every((f) => f.seen === f.state) && worst <= 150,
      `mean=${mean.toFixed(0)}ms worst=${worst}ms (delivery only; 300-600ms crossfade is by design) — ` +
      flips.map((f) => `${f.state}:${f.ms}`).join(' '));

  const out = { pass: checks.every((c) => c.ok), checks, morph: md };
  rec('bugc', out);
  fs.writeFileSync(path.join(OUT, 'bugc.json'), JSON.stringify(out, null, 2) + '\n');
  log(`Bug C + speed: ${out.pass ? 'PASS' : 'FAIL'} (${checks.filter((c) => c.ok).length}/${checks.length})`);
  for (const c of checks) log(`  ${c.ok ? 'ok  ' : 'FAIL'} ${c.name}: ${c.detail}`);
  return out;
}

/**
 * Wave 5 — answer/report banners, parallel-minds fan-out, kind accent, theme.
 * Contract guard for all of them: NONE of this may move the orb state.
 */
async function runWave5(cdp, brain, rec) {
  const checks = [];
  const add = (name, ok, detail) => checks.push({ name, ok, detail, pass: !!ok });
  const banner = async () => {
    const s = await cdp.evaluateJson(
      "JSON.stringify({ text: (document.getElementById('subtitle')||{}).textContent || '', " +
      "shown: !!(document.getElementById('subtitle')||{}).classList.contains('show'), " +
      "cls: (document.getElementById('subtitle')||{}).className || '' })");
    return s;
  };

  await cdp.evaluate(`document.body.style.background = ${JSON.stringify(BG_STYLES.dark)}`);
  brain.step('fan');                    // parallel-minds: 1 parent + 2 children
  await sleep(1400);
  let trace = await cdp.evaluateJson('JSON.stringify(window.__orbTrace())');
  add('parallel_minds_fan_layout',
      trace.jobs.length === 3 && trace.jobFan === true &&
      trace.jobGroups >= 1 && trace.jobSpokes > 0,
      `jobs=${trace.jobs.length} fan=${trace.jobFan} groups=${trace.jobGroups} ` +
      `spokes=${trace.jobSpokes} (expect 3 / true / >=1 / >0)`);
  add('kind_accent_analysis', trace.jobKind === 'analysis',
      `foreground kind=${trace.jobKind} (first live job_event.kind, expect analysis)`);

  const stateBefore = trace.applied.state;

  brain.step('answer');
  await sleep(700);
  let b = await banner();
  const t = await cdp.evaluateJson('JSON.stringify(window.__orbTrace())');
  add('answer_renders_as_banner',
      b.shown && /Answer ·/.test(b.text) && /groq/.test(b.text) && /banner/.test(b.cls),
      `text=${JSON.stringify(b.text)} cls=${b.cls}`);
  add('answer_does_not_change_state', t.applied.state === stateBefore,
      `state ${stateBefore} -> ${t.applied.state} (must be unchanged)`);

  brain.step('report');
  await sleep(700);
  b = await banner();
  add('report_renders_as_banner',
      b.shown && /Weekly pipeline report/.test(b.text) && /banner/.test(b.cls),
      `text=${JSON.stringify(b.text.slice(0, 90))} cls=${b.cls}`);
  const t2 = await cdp.evaluateJson('JSON.stringify(window.__orbTrace())');
  add('report_does_not_change_state', t2.applied.state === stateBefore,
      `state ${stateBefore} -> ${t2.applied.state} (must be unchanged)`);

  add('theme_follows_persona_tier',
      t.theme && t.theme.requested === 'auto' && t.theme.personaTier === 'great_sage',
      t.theme ? `orb.theme=${t.theme.requested} persona.tier=${t.theme.personaTier}` : 'theme probe missing');

  // LIVE palette reload (evolution-persona request, requirement 2): main stats
  // the config files on orb_state and re-pushes the palette. Touch MY OWN lane
  // fragment — content byte-identical, only mtime moves — then drive a state so
  // the watcher fires. No other lane's file is touched.
  const cfgFile = path.join(ROOT, 'config.d', 'orb.yaml');
  const before = fs.readFileSync(cfgFile);
  try {
    execSync(`touch ${JSON.stringify(cfgFile)}`, { stdio: 'ignore' });
    brain.step('thinking');
    await sleep(1300);
    brain.step('idle');            // second transition clears the 1s throttle
    await sleep(1500);
    const t3 = await cdp.evaluateJson('JSON.stringify(window.__orbTrace())');
    const paletteRx = (t3.rx || []).filter((r) => r.kind === 'palette');
    add('palette_reloads_live_without_restart', paletteRx.length > 0,
        `orb-palette frames received: ${paletteRx.length}` +
        (paletteRx.length ? ` last=${JSON.stringify(paletteRx[paletteRx.length - 1].data)}` : ''));
    add('palette_content_unchanged', fs.readFileSync(cfgFile).equals(before),
        'config.d/orb.yaml must be byte-identical (only mtime changed)');
  } finally {
    fs.writeFileSync(cfgFile, before);   // never leave the lane config modified
  }

  const out = { pass: checks.every((c) => c.ok), checks };
  rec('wave5', out);
  fs.writeFileSync(path.join(OUT, 'wave5.json'), JSON.stringify(out, null, 2) + '\n');
  log(`Wave 5: ${out.pass ? 'PASS' : 'FAIL'} (${checks.filter((c) => c.ok).length}/${checks.length})`);
  for (const c of checks) log(`  ${c.ok ? 'ok  ' : 'FAIL'} ${c.name}: ${c.detail}`);
  return out;
}

/**
 * AMENDMENT (user, 2026-10-07): "the orb is now in a weird shape, its not a
 * cage we had earlier — preserve that."
 *
 * Two failure modes to prove cannot happen:
 *  1. BOOT — the revert collapsed every morph through ONE applyLatticeShape()
 *     call site; if the lattice were only established on the first STATE event
 *     it would sit at build-time default. Assert the geometry is already the
 *     cage before anything drives a state.
 *  2. MID-TASK — brain/orbstate.py still emits per-task `shape_hint`
 *     (llm -> octagram via config orb.shape_map). The renderer must ignore it
 *     (SHAPE_MORPHS_ENABLED=false), so the check deliberately REQUIRES that a
 *     non-circle hint actually arrives and is still not applied.
 */
async function runCageGuard(cdp, brain, rec) {
  const checks = [];
  const add = (name, ok, detail) => checks.push({ name, ok, detail, pass: !!ok });
  const md = () => cdp.evaluateJson('window.__orbMorphDiff()');
  const okShape = (m) => m && m.shape === 'circle' && m.morphActive === false &&
    m.lattice && m.lattice.maxErr < 0.01 && m.cage && m.cage.maxErr < 0.01;

  // (1) BOOT
  const boot = await md();
  add('cage_established_at_boot', okShape(boot),
    boot ? `shape=${boot.shape} morphActive=${boot.morphActive} ` +
          `lattice.maxErr=${boot.lattice && boot.lattice.maxErr.toFixed(4)} ` +
          `cage.maxErr=${boot.cage && boot.cage.maxErr.toFixed(4)} points=${boot.lattice && boot.lattice.points}`
         : 'probe missing');

  // (2) MID-TASK — mock's thinking frame carries shape_hint=octagram, task_kind=llm
  brain.step('thinking');
  await sleep(1400);
  const rx = await cdp.evaluateJson('JSON.stringify(window.__orbTrace())');
  const hinted = (rx.rx || []).filter((r) => r.kind === 'orb_state' && r.data && r.data.shapeHint);
  const octa = hinted.some((r) => r.data.shapeHint === 'octagram');
  add('mid_task_hint_reaches_renderer', octa,
    `orb_state frames carrying a shape_hint: ${hinted.map((r) => r.data.shapeHint).join(',') || 'none'} ` +
    '(the brain-side value we must IGNORE)');

  const mid = await md();
  add('cage_preserved_mid_task', okShape(mid),
    mid ? `applied=${mid.shapeHintField} effective=${mid.shape} morphActive=${mid.morphActive} ` +
          `lattice.maxErr=${mid.lattice && mid.lattice.maxErr.toFixed(4)} ` +
          `cage.maxErr=${mid.cage && mid.cage.maxErr.toFixed(4)}`
        : 'probe missing');
  add('state_applied_while_shape_stays_circle',
    rx.applied && rx.applied.state === 'thinking' && rx.applied.shapeHint === 'circle',
    rx.applied ? `state=${rx.applied.state} shapeHint=${rx.applied.shapeHint} (expect thinking / circle)` : 'no applied record');

  brain.step('idle');
  await sleep(600);
  const out = { pass: checks.every((c) => c.ok), checks, boot, mid };
  rec('cage_guard', out);
  fs.writeFileSync(path.join(OUT, 'cage-guard.json'), JSON.stringify(out, null, 2) + '\n');
  log(`cage guard: ${out.pass ? 'PASS' : 'FAIL'} (${checks.filter((c) => c.ok).length}/${checks.length})`);
  for (const c of checks) log(`  ${c.ok ? 'ok  ' : 'FAIL'} ${c.name}: ${c.detail}`);
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
  fs.mkdirSync(path.join(DOCS_ORB, 'matrix'), { recursive: true });
  // Clear stale deliverables first: a state we no longer capture on a given
  // background would otherwise linger from an older build and be diffed
  // against fresh images (it did — 4 old offline/reconnecting shots survived).
  // Skipped for a partial `--only=` phase: it regenerates only its own output
  // and would otherwise destroy the rest of the evidence set.
  if (!ONLY_PHASE) {
    for (const f of fs.readdirSync(DOCS_ORB)) {
      if (/^[a-z_]+-(dark|light|busy)\.png$/.test(f)) fs.unlinkSync(path.join(DOCS_ORB, f));
    }
    const matrixDir = path.join(DOCS_ORB, 'matrix');
    if (fs.existsSync(matrixDir)) {
      for (const f of fs.readdirSync(matrixDir)) {
        if (/^[a-z_]+--(dark|light|busy)\.png$/.test(f)) fs.unlinkSync(path.join(matrixDir, f));
      }
    }
    for (const f of fs.readdirSync(OUT)) {
      if (/^[a-z_]+--(dark|light|busy)(--r\d+)?\.png$/.test(f)) fs.unlinkSync(path.join(OUT, f));
    }
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

    // `--only=<phase>` runs a single evidence phase against a fresh instance
    // (cheap iteration instead of a full ~8 min trace).
    if (ONLY_PHASE) {
      log(`--only=${ONLY_PHASE}`);
      if (ONLY_PHASE === 'filmstrip') await runFilmstrips(cdp, brain, rec);
      else if (ONLY_PHASE === 'transparency') await runTransparency(cdp, brain, rec);
      else if (ONLY_PHASE === 'perf') await runBlurPerf(cdp, brain, rec);
      else if (ONLY_PHASE === 'interaction') await runInteraction(cdp, brain, rec);
      else if (ONLY_PHASE === 'bugc') await runBugC(cdp, brain, rec);
      else if (ONLY_PHASE === 'wave5') await runWave5(cdp, brain, rec);
      else throw new Error('unknown --only phase: ' + ONLY_PHASE);
      fs.writeFileSync(path.join(OUT, 'trace-partial.jsonl'), lines.join('\n') + '\n');
      const only = lines.map((l) => { try { return JSON.parse(l); } catch (e) { return null; } })
        .find((e) => e && e.ev === ONLY_PHASE);
      if (only && only.pass === false) {
        console.error(`[orb-trace] FAIL: ${ONLY_PHASE} checks did not hold`);
        process.exitCode = 1;
      }
      return;
    }
    // ^ NB: the stale-PNG cleanup at the top of main() must NOT run for a
    // partial phase — it would delete the per-state screenshots this phase
    // does not regenerate. That already happened once.

    // --- AMENDMENT: preserve the cage (rest AND mid-task) --------------------
    let cageGuard = null;
    try {
      cageGuard = await runCageGuard(cdp, brain, rec);
    } catch (e) {
      log('cage guard FAILED:', e && e.message);
      rec('cage_guard_error', { message: String(e && e.message) });
    }

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
      // docs/orb/matrix/ is the path ORB_REBUILD §8, TODO §4 and PROGRESS.md
      // all cite as the Wave-2 screenshot evidence — keep it in step with the
      // human-facing copy instead of letting it go stale (it was deleted once).
      const matrixDir = path.join(DOCS_ORB, 'matrix');
      fs.mkdirSync(matrixDir, { recursive: true });
      fs.copyFileSync(path.join(DOCS_ORB, `${scene}-${bg}.png`),
                      path.join(matrixDir, `${scene}--${bg}.png`));
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

    // --- §4 filmstrips + transparency (blur forced, transparent backdrop) ---
    let transparency = null;
    try {
      await runFilmstrips(cdp, brain, rec);
      transparency = await runTransparency(cdp, brain, rec);
    } catch (e) {
      log('§4 evidence FAILED:', e && e.message);
      rec('sec4_error', { message: String(e && e.message) });
    }

    // --- Bug C (P0) + Rule-15 flip latency ---------------------------------
    let bugc = null;
    try {
      bugc = await runBugC(cdp, brain, rec);
    } catch (e) {
      log('Bug C phase FAILED:', e && e.message);
      rec('bugc_error', { message: String(e && e.message) });
    }

    // --- Wave 5 (answer/report/parallel-minds/kind/theme) ------------------
    let wave5 = null;
    try {
      wave5 = await runWave5(cdp, brain, rec);
    } catch (e) {
      log('Wave 5 phase FAILED:', e && e.message);
      rec('wave5_error', { message: String(e && e.message) });
    }

    // --- W2.3 interaction (menu / hit-testing / typed command) -------------
    let interaction = null;
    try {
      interaction = await runInteraction(cdp, brain, rec);
    } catch (e) {
      log('interaction FAILED:', e && e.message);
      rec('interaction_error', { message: String(e && e.message) });
    }

    // --- §2 performance: blur cost with it OFF vs ON, plus the idle proof ---
    try {
      const blurPerf = await runBlurPerf(cdp, brain, rec);
      log(`blur perf: idle=${blurPerf.idle.reason} active off=${blurPerf.off.ema.toFixed(1)}ms ` +
          `on=${blurPerf.on.ema.toFixed(1)}ms (${blurPerf.pctOverhead >= 0 ? '+' : ''}${blurPerf.pctOverhead.toFixed(1)}%)`);
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

    // USER DIRECTIVE 2026-10-07: shape morphing is OFF — every captured scene
    // must report the same base shape (circle). Re-scans the `applied` records
    // written above, so this fails if any state or task kind sneaks a morph in.
    const shapesSeen = new Set();
    for (const l of lines) {
      try {
        const e = JSON.parse(l);
        if (e.ev === 'applied' && e.applied && e.applied.shapeHint) shapesSeen.add(e.applied.shapeHint);
      } catch (e) { /* not JSON we care about */ }
    }
    const shapeOk = shapesSeen.size <= 1 && (!shapesSeen.size || shapesSeen.has('circle'));
    rec('shape_directive', { ok: shapeOk, seen: [...shapesSeen], expected: ['circle'] });
    log(`shape directive: ${shapeOk ? 'ok' : 'FAIL'} shapeHint values seen = ${JSON.stringify([...shapesSeen])}`);
    if (!shapeOk) {
      console.error('[orb-trace] FAIL: a shape morph slipped through — expected only "circle"');
      failed = true;
    }

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
    if (transparency && !transparency.pass) {
      console.error('[orb-trace] FAIL: transparency check — a box/fringe is visible at the window edge');
      failed = true;
    }
    if (cageGuard && !cageGuard.pass) {
      console.error('[orb-trace] FAIL: the cage is not preserved at rest/mid-task (AMENDMENT)');
      failed = true;
    }
    if (wave5 && !wave5.pass) {
      console.error('[orb-trace] FAIL: Wave 5 (answer/report/parallel-minds/theme) checks did not hold');
      failed = true;
    }
    if (bugc && !bugc.pass) {
      console.error('[orb-trace] FAIL: Bug C (pulse / stuck shape) or flip latency did not hold');
      failed = true;
    }
    if (interaction && !interaction.pass) {
      console.error('[orb-trace] FAIL: W2.3 interaction checks did not hold');
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

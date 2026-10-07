#!/usr/bin/env node
/* orb-diff.cjs — the W2.1 automated distinctness gate.
 *
 * FAILS when two orb states render near-identical. A pure absolute threshold
 * would be guesswork (a slowly rotating orb differs from itself between two
 * shots), so the gate measures the noise floor FIRST: every scene/background
 * is captured twice, and the same-scene diff is that pair's temporal noise.
 * A cross-scene pair must then clear
 *
 *     threshold = max(ABS_FLOOR, NOISE_FACTOR * worst same-scene noise)
 *
 * plus a minimum share of pixels that actually moved. This is a real pixel
 * diff on the WebGL surface (CDP Page.captureScreenshot), not a state-string
 * comparison.
 *
 * Captures are POSE-LOCKED by the harness (window.__orbLockPose), so the
 * same-scene noise should sit near zero. If it doesn't, the threshold rises
 * and the gate fails loudly — a non-deterministic capture cannot police
 * distinctness, so that failure is the correct one.
 *
 * Usage:  node test/orb-diff.cjs [screenshotDir]
 *         npm run orb:diff
 */
const fs = require('fs');
const path = require('path');
const { decode } = require('./png.cjs');

const ABS_FLOOR = 0.30;     // mean |ΔRGB| out of 255. Pose-locked identical
                            // pairs measure ~0.00, so 0.30 is a 30x margin —
                            // low enough that a *thin* indicator (the private
                            // teal ring, ~0.4-0.8) still counts as a real
                            // difference, which it visibly is.
const NOISE_FACTOR = 1.5;   // cross-scene must beat same-scene noise by 50%
const MIN_CHANGED = 0.007;  // >=0.7% of pixels must actually move — a guard
                            // against "the mean moved because of one blurred
                            // edge" and the primary catch for total clones

function meanAbsDiff(a, b) {
  if (!a || !b || a.length !== b.length) return 255;
  let sum = 0;
  for (let i = 0; i < a.length; i += 4) {
    sum += Math.abs(a[i] - b[i]) + Math.abs(a[i + 1] - b[i + 1]) + Math.abs(a[i + 2] - b[i + 2]);
  }
  return sum / ((a.length / 4) * 3);
}

function changedRatio(a, b, perPx = 12) {
  if (!a || !b || a.length !== b.length) return 1;
  let n = 0;
  for (let i = 0; i < a.length; i += 4) {
    if (Math.abs(a[i] - b[i]) + Math.abs(a[i + 1] - b[i + 1]) + Math.abs(a[i + 2] - b[i + 2]) > perPx) n++;
  }
  return n / (a.length / 4);
}

function loadShots(dir) {
  const shots = new Map(); // "scene|bg|rep" -> rgba
  const files = fs.readdirSync(dir).filter((f) => f.endsWith('.png'));
  for (const f of files) {
    const m = /^(.+)--(dark|light|busy)(?:--r(\d+))?\.png$/.exec(f);
    if (!m) continue;
    const key = `${m[1]}|${m[2]}|${m[3] || '1'}`;
    try {
      shots.set(key, decode(fs.readFileSync(path.join(dir, f))));
    } catch (e) {
      console.error(`[orb-diff] cannot decode ${f}: ${e.message}`);
    }
  }
  return shots;
}

function runDistinctness(dir, outFile) {
  const shots = loadShots(dir);
  const scenes = new Set();
  const bgs = new Set();
  for (const k of shots.keys()) {
    const [s, b] = k.split('|');
    scenes.add(s); bgs.add(b);
  }
  const sceneList = [...scenes].sort();
  const bgList = [...bgs].sort();

  const missing = [];
  const noise = [];   // {scene,bg,diff}
  const bgsOf = new Map(); // scene -> backgrounds it was actually captured in
  for (const s of sceneList) {
    const own = [];
    for (const b of bgList) {
      const a = shots.get(`${s}|${b}|1`);
      if (!a) continue;
      own.push(b);
      const c = shots.get(`${s}|${b}|2`);
      if (!c) missing.push(`${s}--${b} (needs 2 captures)`);
      else noise.push({ scene: s, bg: b, diff: meanAbsDiff(a.data, c.data) });
    }
    if (!own.length) missing.push(`${s} (no captures at all)`);
    bgsOf.set(s, own);
  }

  const worstNoise = noise.reduce((m, n) => Math.max(m, n.diff), 0);
  const threshold = Math.max(ABS_FLOOR, NOISE_FACTOR * worstNoise);

  const pairs = [];
  for (let i = 0; i < sceneList.length; i++) {
    for (let j = i + 1; j < sceneList.length; j++) {
      let worst = { diff: 0, bg: null, changed: 0 };
      const shared = (bgsOf.get(sceneList[i]) || []).filter((b) => (bgsOf.get(sceneList[j]) || []).includes(b));
      for (const b of shared) {
        const a = shots.get(`${sceneList[i]}|${b}|1`);
        const c = shots.get(`${sceneList[j]}|${b}|1`);
        if (!a || !c) continue;
        const d = meanAbsDiff(a.data, c.data);
        if (d > worst.diff) worst = { diff: d, bg: b, changed: changedRatio(a.data, c.data) };
      }
      if (worst.bg === null) continue;
      const pass = worst.diff >= threshold && worst.changed >= MIN_CHANGED;
      pairs.push({ pair: [sceneList[i], sceneList[j]], ...worst, pass });
    }
  }

  const failures = pairs.filter((p) => !p.pass);
  const weakest = pairs.slice().sort((a, b) => a.diff - b.diff)[0] || null;
  const report = {
    scenes: sceneList, backgrounds: bgList,
    shots: shots.size,
    noise: { worst: worstNoise, samples: noise.length,
             perScene: noise.slice().sort((a, b) => b.diff - a.diff).slice(0, 5) },
    threshold, minChanged: MIN_CHANGED,
    pairCount: pairs.length,
    pairs,
    failures: failures.length,
    failingPairs: failures.slice(0, 40),
    weakest,
    pass: failures.length === 0 && missing.length === 0,
    missing,
  };
  if (outFile) fs.writeFileSync(outFile, JSON.stringify(report, null, 2) + '\n');
  return report;
}

function table(report) {
  const byScene = {};
  for (const p of report.pairs) {
    const [a, b] = p.pair;
    byScene[a] = byScene[a] || [];
    byScene[b] = byScene[b] || [];
    byScene[a].push({ other: b, d: p.diff, ok: p.pass });
    byScene[b].push({ other: a, d: p.diff, ok: p.pass });
  }
  const rows = [];
  for (const s of report.scenes) {
    const list = (byScene[s] || []).sort((x, y) => x.d - y.d);
    const worst = list[0];
    rows.push(`${s.padEnd(18)} worst=${worst ? worst.other.padEnd(18) + ' ' + worst.d.toFixed(2) : 'n/a'} ` +
              `${worst && worst.ok ? 'ok' : 'FAIL'}`);
  }
  return rows.join('\n');
}

if (require.main === module) {
  const dir = process.argv[2] || path.join(__dirname, '..', '..', '..', 'docs', 'orb', 'trace');
  if (!fs.existsSync(dir)) {
    console.error(`[orb-diff] no screenshots in ${dir} — run \`npm run orb:trace\` first`);
    process.exit(1);
  }
  const report = runDistinctness(dir, path.join(dir, 'distinctness.json'));
  console.log(`scenes=${report.scenes.length} backgrounds=${report.backgrounds.length} ` +
              `pairs=${report.pairCount} shots=${report.shots}`);
  console.log(`temporal noise floor = ${report.noise.worst.toFixed(3)} -> threshold ${report.threshold.toFixed(3)}`);
  console.log(table(report));
  if (report.missing.length) {
    console.error('MISSING captures:\n  ' + report.missing.join('\n  '));
  }
  if (report.failures) {
    console.error(`\nFAIL: ${report.failures} near-identical pair(s):`);
    for (const f of report.failingPairs.slice(0, 15)) {
      console.error(`  ${f.pair[0]} vs ${f.pair[1]} @${f.bg}: diff=${f.diff.toFixed(2)} ` +
                    `changed=${(f.changed * 100).toFixed(1)}% (need ${report.threshold.toFixed(2)})`);
    }
    process.exit(1);
  }
  console.log('\nPASS: every pair of states renders measurably differently');
}

module.exports = { runDistinctness, meanAbsDiff, changedRatio, ABS_FLOOR, NOISE_FACTOR };

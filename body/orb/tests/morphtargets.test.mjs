// Wave-4 "pose-lock-vs-truth probe invariant into CI" — the pure half of it.
//
// Bug C's lattice wedge (144 floats vs 180) was invisible to EVERY screenshot
// gate, because __orbLockPose() snapped the lattice before each capture. The
// rule from the Wave-3 handoff is: renderer invariants get asserted unlocked
// and, wherever the logic is pure, in a test that needs no GPU at all.
//
// Run: node tests/morphtargets.test.mjs      (no Electron, no spawn)
import assert from 'node:assert';
import {
  makeMorphTarget, MORPH_SHAPES, BASE_VERTEX_COUNT, LATTICE_DEPTH,
  circlePoints, octagramPoints, polygonPoints,
} from '../src/renderer/morphtargets.js';

const results = [];
function check(name, fn) {
  try { fn(); results.push(`  ok   ${name}`); }
  catch (e) { results.push(`  FAIL ${name}: ${e.message}`); process.exitCode = 1; }
}

check('every PROTOCOL §8 shape is present', () => {
  for (const s of ['circle', 'triangle', 'square', 'pentagon', 'hexagon', 'octagram']) {
    assert.ok(MORPH_SHAPES.includes(s), `MORPH_SHAPES is missing "${s}"`);
  }
});

// *** The invariant that Bug C violated ***
check('all targets share ONE vertex count (Bug C: octagram 144 vs 180)', () => {
  const lens = MORPH_SHAPES.map((s) => makeMorphTarget(s).length);
  const uniq = [...new Set(lens)];
  assert.strictEqual(uniq.length, 1,
    `targets disagree: ${MORPH_SHAPES.map((s, i) => `${s}=${lens[i]}`).join(' ')}`);
  assert.strictEqual(uniq[0], BASE_VERTEX_COUNT * 3,
    `expected ${BASE_VERTEX_COUNT * 3} floats, got ${uniq[0]}`);
});

check('targets stay equal even when the vertex count is varied', () => {
  for (const n of [12, 48, 60, 96]) {
    const lens = ['circle', 'triangle', 'square', 'pentagon', 'hexagon', 'octagram']
      .map((s) => (s === 'octagram' ? octagramPoints(n)
        : s === 'circle' ? circlePoints(n)
          : polygonPoints(3, n)).length);
    assert.deepStrictEqual([...new Set(lens)], [n * 3],
      `n=${n} produced ${lens.join(',')}`);
  }
});

check('a shorter target would be caught (the shape of the original bug)', () => {
  // simulate what updateMorph does: it lerps only min(from, to)
  const from = makeMorphTarget('circle');          // 180
  const legacyOctagram = octagramPoints(48);       // 144 — the pre-fix builder
  const lerped = Math.min(from.length, legacyOctagram.length);
  assert.strictEqual(lerped, 144, 'expected the legacy builder to under-run');
  assert.ok(from.length - lerped >= 30,
    'a stale tail should be big enough to matter — the premise of this test');
  // and assert the shipped builder does NOT reproduce it
  assert.strictEqual(makeMorphTarget('octagram').length, from.length,
    'shipped octagram still under-runs the lerp');
});

check('every target is finite (no NaN leaking into the buffer)', () => {
  for (const s of MORPH_SHAPES) {
    const a = makeMorphTarget(s);
    for (let i = 0; i < a.length; i++) {
      assert.ok(Number.isFinite(a[i]), `${s}[${i}] = ${a[i]}`);
    }
  }
});

check('lattice is NOT flat (off-plane by LATTICE_DEPTH)', () => {
  for (const s of MORPH_SHAPES) {
    const a = makeMorphTarget(s);
    let maxZ = 0;
    for (let i = 2; i < a.length; i += 3) maxZ = Math.max(maxZ, Math.abs(a[i]));
    assert.ok(maxZ > LATTICE_DEPTH * 0.9,
      `${s} max |z| = ${maxZ.toFixed(3)}, expected ~${LATTICE_DEPTH} — it is flat again`);
  }
});

check('the shape actually differs between targets (a morph is not a no-op)', () => {
  const a = makeMorphTarget('circle');
  for (const s of MORPH_SHAPES.filter((x) => x !== 'circle')) {
    const b = makeMorphTarget(s);
    let max = 0;
    for (let i = 0; i < a.length; i++) max = Math.max(max, Math.abs(a[i] - b[i]));
    assert.ok(max > 0.05, `circle vs ${s} max delta = ${max.toFixed(4)} — visually identical`);
  }
});

console.log('morph target invariants:');
console.log(results.join('\n'));
if (process.exitCode) {
  console.error('FAILED');
  process.exit(1);
}
console.log(`All ${results.length} morph target invariants passed`);

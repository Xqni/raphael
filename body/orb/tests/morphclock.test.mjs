// Wave-4 reconnect-storm test — does a lattice morph converge when states
// change faster than the 600 ms ramp? Pure simulation, no GPU (AGENTS §14).
import assert from 'node:assert';
import { nextMorphStart, morphProgress } from '../src/renderer/morphclock.js';

const results = [];
function check(name, fn) {
  try { fn(); results.push(`  ok   ${name}`); }
  catch (e) { results.push(`  FAIL ${name}: ${e.message}`); process.exitCode = 1; }
}
const D = 600;      // MORPH_DURATION
const STEP = 100;   // a state flip every 100 ms (worse than Bug E's flicker)

/** Returns the wall-clock time at which the ramp first reaches 1. */
function storm(comboStart) {
  let morphStart = 0, active = false;
  for (let t = 0; t <= 4000; t += STEP) {
    morphStart = comboStart(t, morphStart, active);   // a retarget lands at t
    active = true;
    if (morphProgress(t - morphStart, D) >= 1) return t;
  }
  return null;
}

check('retarget keeps progress -> a storm CONVERGES on the newest target', () => {
  const at = storm((t, start, active) => nextMorphStart({ active, morphStart: start, now: t }));
  assert.ok(at !== null, 'never completed — the lattice would stay stuck');
  assert.ok(at <= 700, `took ${at}ms to converge, expected <=700ms`);
});

check('reset-on-retarget (the old behaviour) NEVER converges', () => {
  // documents why the fix is not a no-op: restarting the clock every 100 ms
  // keeps progress at 0% forever.
  const at = storm((t) => t);            // always "start now"
  assert.strictEqual(at, null, 'old behaviour unexpectedly converged');
});

check('a calm ramp is untouched by the fix', () => {
  let start = nextMorphStart({ active: false, morphStart: 0, now: 12345 });
  assert.strictEqual(start, 12345, 'a fresh ramp must start now');
  assert.strictEqual(morphProgress(0, D), 0);
  assert.strictEqual(morphProgress(D / 2, D), 0.5);
  assert.strictEqual(morphProgress(D, D), 1);
  assert.strictEqual(morphProgress(D + 999, D), 1, 'clamped, no overshoot');
});

check('progress is monotonic while nobody retargets', () => {
  let prev = -1;
  for (let t = 0; t <= D; t += 33) {
    const p = morphProgress(t - 0, D);
    assert.ok(p >= prev, `progress went backwards at t=${t}`);
    prev = p;
  }
});

check('degenerate inputs cannot divide-by-zero', () => {
  assert.strictEqual(morphProgress(100, 0), 1, 'duration 0 should be done');
  assert.strictEqual(nextMorphStart({ active: true, morphStart: NaN, now: 7 }).valueOf(), 7,
    'NaN start must be treated as fresh');
});

console.log('morph clock / reconnect-storm:');
console.log(results.join('\n'));
if (process.exitCode) { console.error('FAILED'); process.exit(1); }
console.log(`All ${results.length} morph-clock tests passed`);

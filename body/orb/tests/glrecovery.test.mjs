// Wave-4 GPU context loss — pure policy test (no GPU, no Electron).
import assert from 'node:assert';
import { createGlRecovery } from '../src/renderer/glrecovery.js';

const results = [];
function check(name, fn) {
  try { fn(); results.push(`  ok   ${name}`); }
  catch (e) { results.push(`  FAIL ${name}: ${e.message}`); process.exitCode = 1; }
}

check('webglcontextlost is PREVENTED (otherwise restore never fires)', () => {
  let prevented = 0;
  const r = createGlRecovery({ reload: () => { throw new Error('must not reload on lost'); } });
  const out = r.onLost({ preventDefault: () => { prevented++; } });
  assert.strictEqual(prevented, 1, 'preventDefault was not called');
  assert.strictEqual(out, true);
  assert.strictEqual(r.isLost(), true, 'renderer must know to skip GL work');
});

check('restore reloads exactly once', () => {
  let n = 0;
  let t = 0;
  const r = createGlRecovery({ reload: () => { n++; }, now: () => t });
  r.onLost({ preventDefault() {} });
  t = 20000;                       // well past the cooldown
  assert.strictEqual(r.onRestored(), 'reloaded');
  assert.strictEqual(n, 1);
  assert.strictEqual(r.isLost(), false);
});

check('a context that keeps dying cannot cause a reload loop', () => {
  let n = 0;
  let t = 0;
  const r = createGlRecovery({ reload: () => { n++; }, now: () => t, cooldownMs: 15000 });
  r.onLost({ preventDefault() {} }); t = 20000;
  assert.strictEqual(r.onRestored(), 'reloaded');
  // second and third losses inside the cooldown must be suppressed
  for (let i = 0; i < 5; i++) {
    r.onLost({ preventDefault() {} });
    t += 100;                      // 100ms between loss and restore
    assert.strictEqual(r.onRestored(), 'suppressed', `loop guard #${i}`);
  }
  assert.strictEqual(n, 1, 'reloaded more than once');
  assert.strictEqual(r.state().suppressed, 5);
  // ...and a loss AFTER the cooldown may reload again (recovery still works)
  t += 20000;
  r.onLost({ preventDefault() {} });
  assert.strictEqual(r.onRestored(), 'reloaded');
  assert.strictEqual(n, 2);
});

check('100 loss/restore cycles stay bounded', () => {
  let n = 0, t = 0;
  const r = createGlRecovery({ reload: () => { n++; }, now: () => t });
  for (let i = 0; i < 100; i++) {
    r.onLost({ preventDefault() {} });
    t += 500;
    r.onRestored();
  }
  // 100 cycles over 50 s with a 15 s cooldown => reloads at t=0.5s/15.5s/30.5s/45.5s
  assert.ok(n <= 4, `expected <=4 reloads over 100 cycles in 50s, got ${n}`);
  assert.ok(r.state().suppressed >= 95, `expected >=95 suppressed, got ${r.state().suppressed}`);
});

console.log('gpu context loss recovery:');
console.log(results.join('\n'));
if (process.exitCode) { console.error('FAILED'); process.exit(1); }
console.log(`All ${results.length} gl-recovery tests passed`);

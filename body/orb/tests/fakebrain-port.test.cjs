// Wave-4 safety test (no spawn): `fake-brain.cjs` used to hardcode port 8765 —
// the LIVE brain's port — which, with the stack up (live_e2e=true), a careless
// `node fake-brain.cjs` would have bound. resolvePort() is pure, so this runs
// in plain Node: no Electron, no socket, nothing listening (AGENT_RULES §14).
const assert = require('assert');
const { resolvePort, MAIN_PORT } = require('../test/fake-brain.cjs');

function gotPort(argv, env) {
  try { return { port: resolvePort(argv, env) }; }
  catch (e) { return { threw: e.message }; }
}

const results = [];
function check(name, fn) {
  try { fn(); results.push(`  ok   ${name}`); }
  catch (e) { results.push(`  FAIL ${name}: ${e.message}`); process.exitCode = 1; }
}

check('no instance -> LANE port, never the live brain port', () => {
  const r = gotPort([], {});
  assert.strictEqual(typeof r.port, 'number', `threw instead: ${r.threw}`);
  assert.notStrictEqual(r.port, MAIN_PORT, 'resolved to the LIVE port 8765');
});

check('instance orb -> 8906 (INTERFACES §d)', () => {
  assert.strictEqual(gotPort([], { RAPHAEL_INSTANCE: 'orb' }).port, 8906);
});

check('instance main -> REFUSES without --allow-main', () => {
  const r = gotPort([], { RAPHAEL_INSTANCE: 'main' });
  assert.ok(r.threw && /LIVE brain port/.test(r.threw), `expected refusal, got ${r.port}`);
});

check('--port=8765 -> REFUSES without --allow-main', () => {
  const r = gotPort(['--port=8765'], {});
  assert.ok(r.threw && /LIVE brain port/.test(r.threw), `expected refusal, got ${r.port}`);
});

check('--port=8765 --allow-main -> allowed (explicit intent)', () => {
  assert.strictEqual(gotPort(['--port=8765', '--allow-main'], {}).port, 8765);
});

check('explicit --port is honoured', () => {
  assert.strictEqual(gotPort(['--port=18901'], {}).port, 18901);
});

check('bad --port is rejected', () => {
  assert.ok(gotPort(['--port=nope'], {}).threw, 'expected a rejection');
});

check('caller env is not mutated (helper is side-effect free)', () => {
  const had = process.env.RAPHAEL_INSTANCE;
  const env = {};
  resolvePort([], env);
  assert.deepStrictEqual(env, {}, 'caller env was mutated');
  assert.strictEqual(process.env.RAPHAEL_INSTANCE, had,
    'process.env.RAPHAEL_INSTANCE was left behind');
});

console.log('fake-brain port safety tests:');
console.log(results.join('\n'));
if (process.exitCode) {
  console.error('FAILED');
  process.exit(1);
}
console.log(`All ${results.length} fake-brain port safety tests passed`);

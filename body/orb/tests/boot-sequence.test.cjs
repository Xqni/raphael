// AMENDMENT 2 (user): "the starting state might need to be rewired — starting
// state -> idle state -> then change based on what's happening."
//
// This is the ORB's half of that guarantee, tested in plain Node against a
// local mock-brain on an ephemeral test port (AGENT_RULES §14: never 8765,
// the live brain port) — no Electron, no live stack.
//
// Three scenarios:
//   A. brain accepts the socket and NEVER answers -> starting must auto-escape
//      to idle instead of lingering forever (previously only the renderer's
//      one-shot 5400 ms timer covered this; main-process status did not).
//   B. the first non-boot frame is already an EVENT state (jobs exist the
//      moment boot finishes) -> show idle for one beat first, so the sequence
//      is starting -> idle -> thinking, never starting -> thinking.
//   C. the normal path: auth_ok settles to idle, then events follow.

const assert = require('assert');
const { MockBrain } = require('../test/mock-brain.cjs');
const StatusWS = require('../src/main/ws-status.js');

const PORT = Number(process.env.ORB_TEST_WS_PORT || 18942);
const TOKEN = 'boot-seq-test-token';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const results = [];
function report(name, cond, detail) {
  results.push(`  ${cond ? 'ok  ' : 'FAIL'} ${name}${detail ? `: ${detail}` : ''}`);
  if (!cond) process.exitCode = 1;
}

function watch(st, stepMs = 15) {
  const seq = [];
  // capture the constructor's initial state synchronously — a fast auth_ok can
  // land before the first tick, and `starting` must still be recorded.
  let last = st.state.orbState;
  seq.push({ state: last, at: Date.now() });
  const timer = setInterval(() => {
    const s = st.state.orbState;
    if (s !== last) { seq.push({ state: s, at: Date.now() }); last = s; }
  }, stepMs);
  return { seq, stop: () => clearInterval(timer) };
}
const names = (seq) => seq.map((s) => s.state);
/** true when `from` is immediately followed by `to` in the transition list */
const adjacent = (seq, from, to) =>
  seq.some((s, i) => i > 0 && seq[i - 1].state === from && s.state === to);

async function main() {
  const brain = new MockBrain({ port: PORT, token: TOKEN });
  await brain.listen();

  const cfg = (extra) => Object.assign({
    token: TOKEN,
    wsUrl: `ws://127.0.0.1:${PORT}/ws`,
    reconnectInitial: 120,
    reconnectMax: 800,
    heartbeatInterval: 15000,
  }, extra);

  // ---- A: no frame ever arrives -> auto-escape -----------------------------
  brain.holdAuth = true;
  const stA = new StatusWS(cfg({ bootEscapeMs: 250 }));
  const wA = watch(stA);
  const tA = Date.now();
  stA.start();
  await sleep(1400);
  wA.stop();
  stA.dispose();
  const seqA = wA.seq;
  const escA = seqA.find((s) => s.state === 'idle');

  report('A: starts in `starting`', names(seqA)[0] === 'starting', names(seqA).join('->'));
  report('A: auto-escapes starting->idle when NO frame arrives',
    !!escA, names(seqA).join('->'));
  report('A: escape fires inside the 250 ms budget (it is the timer, not luck)',
    !!escA && (escA.at - tA) < 1000,
    escA ? `escape after ${escA.at - tA} ms (budget 250, deadline 1000)` : 'no escape');
  report('A: never lingers — ends `idle`, not starting/reconnecting/offline',
    names(seqA).includes('idle') && !['starting', 'reconnecting', 'offline']
      .includes(names(seqA)[names(seqA).length - 1]),
    `final=${names(seqA)[names(seqA).length - 1]}`);
  report('A: a healthy open socket must not drop to reconnecting',
    !names(seqA).includes('reconnecting'), names(seqA).join('->'));

  // ---- B: first frame is an event state -> idle beat first -----------------
  brain.holdAuth = true;
  const stB = new StatusWS(cfg({ bootEscapeMs: 8000 })); // too slow to interfere
  const wB = watch(stB);
  stB.start();
  await sleep(150);                 // connected, auth withheld, still `starting`
  brain.step('thinking');           // Brain boots straight into an event state
  await sleep(1100);
  wB.stop();
  stB.dispose();
  const seqB = wB.seq;

  report('B: starts in `starting`', names(seqB)[0] === 'starting', names(seqB).join('->'));
  report('B: never starting->thinking DIRECTLY (idle beat inserted)',
    !adjacent(seqB, 'starting', 'thinking'), names(seqB).join('->'));
  report('B: idle shown before the event state',
    names(seqB).indexOf('idle') > -1 &&
    names(seqB).indexOf('thinking') > names(seqB).indexOf('idle'),
    names(seqB).join('->'));
  report('B: the deferred event state is still applied (not swallowed)',
    names(seqB).includes('thinking'), names(seqB).join('->'));

  // ---- C: normal path — auth_ok settles, then events ------------------------
  brain.holdAuth = false;
  brain.releaseAuth();               // in case a held auth lingers
  const stC = new StatusWS(cfg({ bootEscapeMs: 8000 }));
  const wC = watch(stC);
  stC.start();
  await sleep(500);                  // auth_ok -> idle
  brain.step('thinking');
  await sleep(400);
  wC.stop();
  stC.dispose();
  const seqC = wC.seq;

  report('C: starts in `starting`', names(seqC)[0] === 'starting', names(seqC).join('->'));
  report('C: settles to idle on auth (brief starting, no lingering)',
    names(seqC).includes('idle'), names(seqC).join('->'));
  report('C: never starting->thinking DIRECTLY',
    !adjacent(seqC, 'starting', 'thinking'), names(seqC).join('->'));
  report('C: sequence is starting -> idle -> <event>',
    names(seqC).indexOf('idle') > -1 &&
    names(seqC).indexOf('thinking') > names(seqC).indexOf('idle'),
    names(seqC).join('->'));

  await brain.close();

  console.log('boot sequence tests (AMENDMENT 2):');
  console.log(results.join('\n'));
  if (process.exitCode) { console.error('FAILED'); process.exit(1); }
  console.log(`All ${results.length} boot sequence tests passed`);
  process.exit(0);
}

main().catch((e) => { console.error('FAILED:', e && e.stack || e); process.exit(1); });

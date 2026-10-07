// Phase-6 fake Brain: drives the orb's REAL WS->IPC->renderer chain end-to-end.
// Timeline: auth_ok -> thinking -> speaking (+10 amplitude bursts) -> hold ->
// then the server CLOSES so the orb must fall into reconnecting (edge-drop).
//
// Usage:  node fake-brain.cjs                # binds the ORB instance port (8906)
//         node fake-brain.cjs --port=18901   # explicit port
//         node fake-brain.cjs --allow-main   # required to bind 8765 at all
//
// SAFETY (Wave 4): this used to hardcode port 8765 — the LIVE brain's port —
// and an absolute path into the old workspace. With the live stack running
// (`live_e2e=true`), binding8765 would collide with (or impersonate) the real
// Brain. It now derives from RAPHAEL_INSTANCE, DEFAULTS TO THE LANE, and
// refuses the main port unless you pass --allow-main. Nothing binds at
// require() time, so `resolvePort()` is unit-testable without spawning.
const { WebSocketServer } = require('ws');
const Instance = require('../src/main/instance');

const log = (...a) => console.log('[FAKE-BRAIN]', ...a);
const MAIN_PORT = Instance.MAIN_WS_PORT;

/**
 * Decide which port to bind — pure, no sockets, so it can be asserted without
 * starting anything (AGENT_RULES §14: check before you spawn).
 * @returns {number}
 */
function resolvePort(argv = process.argv.slice(2), env = process.env) {
  const explicit = argv.find((a) => a.startsWith('--port='));
  if (explicit) {
    const p = parseInt(explicit.slice('--port='.length), 10);
    if (!Number.isFinite(p) || p <= 0) throw new Error(`bad --port: ${explicit}`);
    if (p === MAIN_PORT && !argv.includes('--allow-main')) {
      throw new Error(
        `refusing to bind ${p}: that is the LIVE brain port. ` +
        'Pass --allow-main if you really mean the main instance.');
    }
    return p;
  }
  // Default to the LANE, never to main — an unset instance must not be able to
  // land on a running stack's port. The port still comes from the ONE
  // derivation in src/main/instance.js (never re-derived here); `env` is
  // applied to process.env only for the duration of the call so the helper is
  // side-effect-free for callers and unit-testable without binding anything.
  const name = env.RAPHAEL_INSTANCE || 'orb';
  const prev = process.env.RAPHAEL_INSTANCE;
  process.env.RAPHAEL_INSTANCE = name;
  let port;
  try {
    port = Instance.wsPort();
  } finally {
    if (prev === undefined) delete process.env.RAPHAEL_INSTANCE;
    else process.env.RAPHAEL_INSTANCE = prev;
  }
  if (port === MAIN_PORT && !argv.includes('--allow-main')) {
    throw new Error(
      `refusing to bind ${port}: RAPHAEL_INSTANCE=${name} resolves to the ` +
      'LIVE brain port. Unset it (or pass --allow-main if you really mean main).');
  }
  return port;
}

/** Start the scripted fake brain on `port`. Returns a handle for teardown. */
function start(port) {
  const wss = new WebSocketServer({ port, path: '/ws' });
  wss.on('connection', (ws, req) => {
    log('connection from', req.url);
    // auth immediately (orb sends auth on open; auth_ok handler just flips idle)
    ws.send(JSON.stringify({ type: 'auth_ok', session: 'phase6-test' }));
    log('sent auth_ok');

    const send = (obj) => { if (ws.readyState === 1) ws.send(JSON.stringify(obj)); };

    ws.on('message', (data) => {
      let m; try { m = JSON.parse(data.toString()); } catch (e) { return; }
      log('recv type=', m.type, m.type === 'auth' ? JSON.stringify(m).slice(0, 120) : '');
      if (m.type === 'ping') send({ type: 'pong' });
      if (m.type === 'pong') { /* client pong */ }
    });

    // scripted timeline (seconds after connect)
    setTimeout(() => { send({ type: 'orb_state', state: 'thinking', jobs_active: 2 }); log('-> thinking'); }, 1500);
    setTimeout(() => { send({ type: 'orb_state', state: 'speaking', jobs_active: 1 }); log('-> speaking'); }, 4000);
    // amplitude bursts at ~30Hz for ~1.2s (speak events; renderer smooths 30/150ms)
    let seq = 1;
    const t0 = Date.now();
    const ampTimer = setInterval(() => {
      const el = (Date.now() - t0) / 1000;
      const a = Math.abs(Math.sin(el * 5)) * 0.95; // swinging 0..0.95
      send({ type: 'speak', event: 'chunk', seq: seq++, amplitude: a, pitch_hz: 200 + a * 120 });
      if (seq > 36) { clearInterval(ampTimer); } // ~1.2s of bursts
    }, 33);
    setTimeout(() => { log('closing connection (orb should -> reconnecting)'); ws.close(); }, 7000);

    // heartbeat both directions
    const hb = setInterval(() => send({ type: 'ping' }), 4000);
    ws.on('close', () => { clearInterval(hb); clearInterval(ampTimer); log('closed'); });
  });
  return {
    wss,
    close: () => new Promise((res) => wss.close(() => res())),
  };
}

module.exports = { resolvePort, start, MAIN_PORT };

if (require.main === module) {
  try {
    const port = resolvePort();
    start(port);
    log(`listening on ws://127.0.0.1:${port}/ws (instance=${process.env.RAPHAEL_INSTANCE})`);
  } catch (e) {
    console.error('[FAKE-BRAIN]', e.message);
    process.exit(1);
  }
}

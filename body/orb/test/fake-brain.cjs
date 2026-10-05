// Phase-6 fake Brain: drives the orb's REAL WS->IPC->renderer chain end-to-end.
// Timeline: auth_ok -> thinking -> speaking (+10 amplitude bursts) -> hold ->
// then the server CLOSES so the orb must fall into reconnecting (edge-drop).
// Usage: node fake-brain.cjs   (listens ws://127.0.0.1:8765/ws)
const { WebSocketServer } = require('/home/dami/raphael/body/orb/node_modules/ws');

const wss = new WebSocketServer({ port: 8765, path: '/ws' });
const log = (...a) => console.log('[FAKE-BRAIN]', ...a);

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
  ws.on('close', () => { clearInterval(hb); log('closed'); });
});

log('listening on ws://127.0.0.1:8765/ws');

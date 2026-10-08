#!/usr/bin/env node
/* mock-brain.cjs — Wave-2 orb trace source (orb lane, body/orb/test/).
 *
 * Replays PROTOCOL §3 / INTERFACES §e frames at the orb over the REAL WS
 * transport, so the whole chain (WS -> ws-status -> IPC -> renderer -> GL) is
 * exercised exactly as in production. It is intentionally driven by the
 * orchestrator (test/orb-trace.cjs) instead of a wall-clock timeline so a
 * screenshot can be taken at a settled, deterministic moment per state.
 *
 * Standalone:  RAPHAEL_INSTANCE=orb node test/mock-brain.cjs
 *   -> listens on the instance-derived port (8906 for lane `orb`),
 *      logs every frame SENT and RECEIVED to stdout.
 *
 * Frames replayed cover every INTERFACES §e state:
 *   starting, idle, listening, thinking, acting, speaking (+amplitude),
 *   confirm, error, reconnecting (server closes), offline (client-owned —
 *   simulated by closing AND refusing reconnects), private/paused MODES.
 */
const http = require('http');
const { WebSocketServer } = require('ws');

const LOG_MAX = 2000;

// INTERFACES §e: every orb_state carries provider/model (router's current or
// last target) — the orb's right-click menu displays them (Wave-2 item #1).
const INFO = { provider: 'groq', model: 'llama-3.3-70b-versatile' };

class MockBrain {
  /**
   * @param {object} opts { port, token, verbose }
   */
  constructor(opts = {}) {
    this.port = opts.port;
    this.token = opts.token || null;
    this.verbose = !!opts.verbose;
    this.log = [];
    this.sent = [];
    this.received = [];
    this.clients = new Set();
    this.closed = false;
    this.rejectAuth = false;   // set by the trace harness to reach 'offline'
    this.refuseConnections = false; // set by the trace harness to hold 'reconnecting'
    this.holdAuth = false;     // AMENDMENT 2: accept the socket, never answer
    this.authHeld = false;     // true once a client's auth was withheld
    this._seq = 0;             // monotonic `speak` sequence counter
    this._t0 = Date.now();
    this.server = http.createServer((req, res) => {
      res.writeHead(404); res.end('mock-brain');
    });
    this.wss = new WebSocketServer({ noServer: true });
    this.server.on('upgrade', (req, socket, head) => {
      if (req.url !== '/ws' || this.refuseConnections) { socket.destroy(); return; }
      this.wss.handleUpgrade(req, socket, head, (ws) => this._onConnection(ws, req));
    });
  }

  _record(dir, frame) {
    const entry = { t: Date.now() - this._t0, dir, frame };
    this.log.push(entry);
    if (this.log.length > LOG_MAX) this.log.shift();
    if (dir === 'send') this.sent.push(entry); else this.received.push(entry);
    if (this.sent.length > LOG_MAX) this.sent.shift();
    if (this.received.length > LOG_MAX) this.received.shift();
    if (this.verbose) {
      console.log(`[mock-brain ${dir}] ${JSON.stringify(frame)}`);
    }
  }

  _onConnection(ws, req) {
    if (this.closed) { ws.close(); return; }
    this.clients.add(ws);
    this._record('recv', { _meta: 'connect', url: req.url });
    ws.on('message', (data) => {
      if (data instanceof Buffer && data.length >= 4 && data.slice(0, 4).toString() === 'RAPH') {
        this._record('recv', { _meta: 'binary', bytes: data.length });
        return;
      }
      let msg;
      try { msg = JSON.parse(data.toString()); } catch (e) { return; }
      this._record('recv', msg);
      this._onClientFrame(ws, msg);
    });
    ws.on('close', () => this._record('recv', { _meta: 'close' }));
    ws.on('error', () => {});
  }

  _onClientFrame(ws, msg) {
    switch (msg.type) {
      case 'auth': {
        const ok = !this.rejectAuth && (!this.token || msg.token === this.token);
        if (!ok) {
          this._send(ws, { type: 'auth_fail', v: 1, code: 'E_AUTH' });
          ws.close();
          return;
        }
        // AMENDMENT 2 test hook: holdAuth simulates a Brain that accepts the
        // socket but never answers — the orb must auto-escape starting->idle
        // instead of lingering. releaseAuth() completes it later.
        if (this.holdAuth) { this.authHeld = true; break; }
        this._send(ws, { type: 'auth_ok', v: 1, session: 'mock-' + Math.random().toString(36).slice(2, 8), server_v: 'mock' });
        // PROTOCOL §3: server kicks off keepalive immediately after auth_ok.
        this._send(ws, { type: 'ping', v: 1 });
        break;
      }
      case 'ping': this._send(ws, { type: 'pong', v: 1 }); break;
      case 'pong': break;
      // PROTOCOL §3: job snapshot(s) — powers the orb menu's Jobs submenu
      case 'job_list':
        this._send(ws, { type: 'job_list', v: 1, jobs: [
          { job: 'j_mock_1', status: 'running', text: 'Open YouTube and search lo-fi' },
          { job: 'j_mock_2', status: 'done', text: 'What time is it today' },
        ] });
        break;
      case 'cancel':
        this._send(ws, { type: 'ack', v: 1, job: msg.job, cancelled: true });
        break;
      default: break;
    }
  }

  /** AMENDMENT 2: complete a held auth so the orb settles exactly once. */
  releaseAuth() {
    this.holdAuth = false;
    if (!this.authHeld) return false;
    this.authHeld = false;
    for (const ws of this.clients) {
      try {
        this._send(ws, { type: 'auth_ok', v: 1, session: 'mock-' + Math.random().toString(36).slice(2, 8), server_v: 'mock' });
        this._send(ws, { type: 'ping', v: 1 });
      } catch (e) { /* gone */ }
    }
    return true;
  }

  _send(ws, frame) {
    if (!ws || ws.readyState !== ws.OPEN) return;
    this._record('send', frame);
    ws.send(JSON.stringify(frame));
  }

  /** Send `frame` to every connected orb (what brain-core would broadcast). */
  broadcast(frame) {
    for (const ws of this.clients) this._send(ws, frame);
    return frame;
  }

  /** Per-state scene: the exact frame set the Brain SHOULD emit (INTERFACES §e). */
  step(name) {
    const base = { v: 1 };
    switch (name) {
      case 'starting':
        return this.broadcast({ type: 'orb_state', ...base, ...INFO, state: 'starting', jobs_active: 0, mode: 'normal', shape_hint: 'circle', task_kind: 'none', subtitle: 'starting up' });
      case 'idle':
        return this.broadcast({ type: 'orb_state', ...base, ...INFO, state: 'idle', jobs_active: 0, mode: 'normal', shape_hint: 'circle', task_kind: 'none' });
      case 'listening':
        return this.broadcast({ type: 'orb_state', ...base, ...INFO, state: 'listening', jobs_active: 0, mode: 'normal', shape_hint: 'circle', task_kind: 'none', subtitle: 'listening', amplitude: 0.78 });
      case 'thinking':
        return this.broadcast({ type: 'orb_state', ...base, ...INFO, state: 'thinking', jobs_active: 2, mode: 'normal', shape_hint: 'octagram', task_kind: 'llm' });
      case 'acting':
        return this.broadcast({ type: 'orb_state', ...base, ...INFO, state: 'acting', jobs_active: 1, mode: 'normal', shape_hint: 'square', task_kind: 'files', subtitle: 'opening files' });
      case 'speaking':
        this.broadcast({ type: 'orb_state', ...base, ...INFO, state: 'speaking', jobs_active: 1, mode: 'normal', shape_hint: 'circle', task_kind: 'none', provider: 'groq', model: 'llama-3.3-70b-versatile', subtitle: 'speaking' });
        return this.speakBurst(0.85);
      case 'confirm':
        return this.broadcast({ type: 'orb_state', ...base, ...INFO, state: 'confirm', jobs_active: 1, mode: 'normal', shape_hint: 'circle', task_kind: 'none', subtitle: 'confirm?' });
      case 'error':
        return this.broadcast({ type: 'orb_state', ...base, ...INFO, state: 'error', jobs_active: 0, mode: 'normal', shape_hint: 'circle', task_kind: 'none', subtitle: 'E_PROVIDER_429' });
      case 'reconnecting':
        return this.broadcast({ type: 'orb_state', ...base, ...INFO, state: 'reconnecting', jobs_active: 0, mode: 'normal', shape_hint: 'circle', task_kind: 'none' });
      case 'private':
        return this.broadcast({ type: 'orb_state', ...base, ...INFO, state: 'idle', jobs_active: 0, mode: 'private', shape_hint: 'circle', task_kind: 'none', private: true });
      case 'private_overlay':
        // PROTOCOL §8 legacy spelling: private expressed as a STATE (this is
        // what brain-core actually sends today — ws.py:264). It means the same
        // thing as mode:'private', so it must render identically.
        return this.broadcast({ type: 'orb_state', ...base, ...INFO, state: 'private_overlay', jobs_active: 0, mode: 'private', shape_hint: 'circle', task_kind: 'none', private: true });
      case 'paused':
        return this.broadcast({ type: 'orb_state', ...base, ...INFO, state: 'idle', jobs_active: 0, mode: 'paused', shape_hint: 'circle', task_kind: 'none' });
      case 'private_speaking':
        return this.broadcast({ type: 'orb_state', ...base, ...INFO, state: 'speaking', jobs_active: 1, mode: 'private', shape_hint: 'circle', task_kind: 'none', private: true });
      case 'jobs':
        return this.broadcast({ type: 'orb_state', ...base, ...INFO, state: 'thinking', jobs_active: 6, mode: 'normal', shape_hint: 'hexagon', task_kind: 'media' });
      case 'subtitle':
        return this.broadcast({ type: 'subtitle', ...base, text: 'subtitle frame', fade_ms: 4000 });
      case 'fan':
        // PROTOCOL §5 additive: `parent` = parallel-minds fan-out tag
        this.broadcast({ type: 'orb_state', ...base, ...INFO, state: 'thinking',
                         jobs_active: 3, mode: 'normal', shape_hint: 'octagram', task_kind: 'llm' });
        this.broadcast({ type: 'job_event', ...base, job: 'j_parent', seq: 1, status: 'running',
                         stage: 'tool', text: 'fan-out root', kind: 'chat' });
        this.broadcast({ type: 'job_event', ...base, job: 'j_child_a', seq: 1, status: 'running',
                         stage: 'llm', text: 'child A analysis', kind: 'analysis', parent: 'j_parent' });
        this.broadcast({ type: 'job_event', ...base, job: 'j_child_b', seq: 1, status: 'running',
                         stage: 'llm', text: 'child B sim', kind: 'simulation', parent: 'j_parent' });
        return { type: 'fan', jobs: 3 };
      case 'answer':
        return this.broadcast({ type: 'answer', ...base, job: 'j_parent', format: 'answer',
                                text: 'The quick brown fox jumps over the lazy dog.',
                                provider: 'groq', model: 'llama-3.3-70b-versatile' });
      case 'report':
        return this.broadcast({ type: 'report', ...base, job: 'j_parent', format: 'report',
                                title: 'Weekly pipeline report',
                                summary: '4 jobs run, 0 failures, GPU idle 96% of the week.',
                                sections: [{ heading: 'Jobs', text: 'ok' }] });
      case 'notice':
        // PROTOCOL §3 notice: text/level/ts/job — no state change, ever
        return this.broadcast({ type: 'notice', ...base, text: 'Notice: disk almost full',
                                level: 'warn', ts: Date.now() });
      case 'needs_confirm':
        return this.broadcast({ type: 'needs_confirm', ...base, job: 'j_mock_1', question: 'Open YouTube?', actions: ['yes', 'no'], expires_at: Date.now() + 30000 });
      default:
        throw new Error('unknown mock-brain step: ' + name);
    }
  }

  /** A short deterministic amplitude envelope (renderer smooths 30/150 ms). */
  /** Begin a fresh utterance — the Brain restarts `seq` at 0 for each one. */
  speakReset() { this._seq = 0; }

  speakBurst(peak = 0.8) {
    // Each utterance is a NEW seq run (BUGS-WAVE2 Bug C). The old mock kept one
    // monotonic counter forever, so it could never reproduce the bug: the real
    // guard then dropped every utterance after the first.
    this._seq = 0;
    const pts = [0.1, 0.45, peak, 0.7, 0.9, 0.5, 0.62, 0.7]; // ends mid-high -> a settled, screenshot-stable amplitude
    const self = this;
    pts.forEach((a, i) => {
      setTimeout(() => {
        if (self.closed) return;
        // increment at SEND time so `seq` is strictly monotonic against
        // speakAt() — reserving it up front made later frames look stale and
        // the renderer silently dropped them (seq <= lastSpeakSeq).
        const s = ++self._seq;
        self.broadcast({ type: 'speak', v: 1, event: 'chunk', seq: s,
                         amplitude: a, pitch_hz: 180 + a * 80, cached: false });
      }, i * 90);
    });
    return { type: 'speak', _burst: pts.length };
  }

  /** Drive TTS amplitude directly (§4: speaking filmstrip at low/high amp). */
  speakAt(a, pitch) {
    const s = ++this._seq;
    this.broadcast({ type: 'speak', v: 1, event: 'chunk', seq: s,
                     amplitude: a, pitch_hz: pitch || (170 + a * 60), cached: false });
    return { type: 'speak', amplitude: a, seq: s };
  }

  async listen() {
    await new Promise((res, rej) => {
      this.server.once('error', rej);
      this.server.listen(this.port, '127.0.0.1', res);
    });
    return this;
  }

  /** Hard close every client — the orb must fall back to reconnecting/offline. */
  dropClients() {
    for (const ws of this.clients) { try { ws.close(); } catch (e) { /* gone */ } }
    this.clients.clear();
  }

  async close() {
    this.closed = true;
    this.dropClients();
    await new Promise((res) => this.wss.close(() => res()));
    await new Promise((res) => this.server.close(() => res()));
  }
}

module.exports = { MockBrain };

if (require.main === module) {
  const Instance = require('../src/main/instance');
  const port = parseInt(process.argv[2] || '', 10) || Instance.wsPort();
  const brain = new MockBrain({ port, verbose: true });
  brain.listen().then(() => {
    console.log(`[mock-brain] listening ws://127.0.0.1:${port}/ws (instance=${Instance.instance()})`);
  }).catch((e) => { console.error('[mock-brain] FAILED', e.message); process.exit(1); });
}

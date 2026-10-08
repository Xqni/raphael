const EventEmitter = require('events');
const { WebSocket } = require('ws');

// AMENDMENT 2 (user): starting must be BRIEF and must always settle to idle
// next, whatever else is going on. Two mechanisms:
//   * auto-escape — if no frame arrives while we are `starting`, fall back to
//     idle after STARTING_ESCAPE_MS instead of lingering;
//   * settle beat — if the Brain's first non-boot frame is already `thinking`
//     (jobs exist), show `idle` for BOOT_IDLE_BEAT_MS first so the sequence is
//     always starting -> idle -> <event>, never starting -> thinking.
// brain-core owns the emission half (settle-to-idle-first after finish_boot);
// this is the orb's half so the guarantee holds even if that half regresses.
const STARTING_ESCAPE_MS = 4000;
const BOOT_IDLE_BEAT_MS = 400;

const ORB_STATES = new Set([
  'starting',
  'reconnecting',
  'offline',
  'idle',
  'listening',
  'thinking',
  'acting',
  'speaking',
  'confirm',
  'error',
  'private_overlay',
]);

class StatusWS extends EventEmitter {
  constructor(config) {
    super();
    this.config = config;
    this.ws = null;
    this.connected = false;
    this.session = null;
    this.backoff = config.reconnectInitial;
    this.pongMiss = 0;
    this.heartbeatTimer = null;
    this.reconnectTimer = null;
    this.authSent = false;
    this.fatalAuth = false;
    this.seq = 0;
    // Wave 5: job_event's additive `kind`/`parent` (PROTOCOL §5) are STYLING
    // hints for the renderer — parallel-minds fan-out + Analysis/Simulation
    // looks. Tracked here, never turned into an orb_state.
    this.jobs = [];
    // Frame trace (W2.1): every WS frame the orb RECEIVES, bounded ring.
    // Read over IPC by test/orb-trace.cjs — this is the "frames received"
    // half of the end-to-end evidence.
    this.rx = [];
    this.state = {
      orbState: 'starting',
      jobsActive: 0,
      mode: 'normal',
      private: false,
      paused: false,
      subtitle: null,
      // null until a frame carries one (PROTOCOL §8: absent shape_hint -> the
      // orb falls back to the per-state default, not to a stale leftover)
      shapeHint: null,
      taskKind: 'none',
      provider: null,
      model: null,
      amplitude: null,   // optional 0..1 on orb_state (listening reactivity)
      // RESERVED (docs/orb/THEMES.md §5): forwarded but deliberately unused —
      // a future evolution flourish must not need a protocol change.
      evolveStage: null,
    };
    // AMENDMENT 2 boot-sequence state
    this.bootSettled = false;   // true once `starting` has resolved to idle
    this._bootTimer = null;
    this._disposed = false;      // set by dispose(): no further reconnects
    this._armBootEscape();
  }

  /** One auto-escape per `starting` period (re-armed only when we re-enter it). */
  _armBootEscape() {
    if (this._bootTimer) return;
    // bootEscapeMs lets the unit test exercise this in ~200 ms instead of 4 s.
    const escapeMs = (this.config && this.config.bootEscapeMs) || STARTING_ESCAPE_MS;
    this._bootTimer = setTimeout(() => {
      this._bootTimer = null;
      if (this.state.orbState === 'starting') {
        console.warn(`[ws-status] boot auto-escape: no frame within ${escapeMs}ms -> idle`);
        this.updateOrbState('idle');
        this.emit('state', this.state);
      }
    }, escapeMs);
  }

  /** `starting` has resolved — retire the escape timer for this boot. */
  _settleBoot() {
    this.bootSettled = true;
    if (this._bootTimer) { clearTimeout(this._bootTimer); this._bootTimer = null; }
  }

  /** Job table for parallel-minds / kind styling (idempotent; terminal rows drop out). */
  _trackJob(msg) {
    const id = msg.job;
    if (!id) return;
    const TERMINAL = ['done', 'failed', 'cancelled', 'interrupted'];
    let j = this.jobs.find((x) => x.job === id);
    if (!j) { j = { job: id, status: null, kind: null, parent: null, text: null }; this.jobs.push(j); }
    if (msg.status) j.status = msg.status;
    if (msg.kind) j.kind = msg.kind;             // chat | analysis | simulation | act
    if (msg.parent) j.parent = msg.parent;       // parallel-minds fan-out tag
    if (msg.text) j.text = msg.text;
    if (TERMINAL.includes(j.status)) this.jobs = this.jobs.filter((x) => x.job !== id);
    this.emit('jobs', this.jobs);
  }

  _rx(frame) {
    this.rx.push({ t: Date.now(), type: frame && frame.type, frame });
    if (this.rx.length > 300) this.rx.shift();
  }

  traceFrames() {
    return this.rx.slice();
  }

  start() {
    this.connect();
  }

  connect() {
    if (!this.config.token) {
      this.state.orbState = 'offline';
      this.emit('state', this.state);
      return;
    }
    this.clearTimers();
    try {
      this.ws = new WebSocket(this.config.wsUrl);
    } catch (e) {
      this.scheduleReconnect();
      return;
    }
    this.ws.on('open', () => {
      this.connected = true;
      this.pongMiss = 0;
      this.authSent = false;
      this.sendAuth();
      this.startHeartbeat();
      this.emit('state', this.state);
    });
    this.ws.on('message', (data, isBinary) => {
      this.pongMiss = 0;
      if (isBinary) return;
      let msg;
      try {
        msg = JSON.parse(data.toString());
      } catch (e) {
        return;
      }
      this.handle(msg);
    });
    this.ws.on('pong', () => {
      this.pongMiss = 0;
    });
    this.ws.on('close', () => {
      this.connected = false;
      this.ws = null;
      if (this._disposed) { this.authSent = false; this.clearTimers(); return; }
      this.authSent = false;
      this.clearTimers();
      if (this.fatalAuth) {
        this.state.orbState = 'offline';
        this.emit('state', this.state);
        return;
      }
      this.updateOrbState('reconnecting');
      this.emit('state', this.state);
      this.scheduleReconnect();
    });
    this.ws.on('error', () => {
      if (this.ws) this.ws.close();
    });
  }

  handle(msg) {
    this._rx(msg);
    switch (msg.type) {
      case 'ping':
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
          this.ws.send(JSON.stringify({ type: 'pong' }));
        }
        break;
      case 'auth_ok':
        this.session = msg.session;
        this.backoff = this.config.reconnectInitial;
        this.fatalAuth = false;
        this.updateOrbState('idle');
        this.emit('state', this.state);
        break;
      case 'auth_fail':
        this.fatalAuth = true;
        this.updateOrbState('offline');
        this.emit('state', this.state);
        this.ws && this.ws.close();
        break;
      case 'orb_state':
        // AMENDMENT 2 (user): "starting state → idle state → then change based
        // on what's happening." If the Brain's very first non-boot frame is
        // already an event state (jobs exist the moment boot finishes), we must
        // NOT jump starting → thinking. Settle on `idle` for one beat, then
        // apply the real frame. This is the orb's half of the guarantee; the
        // brain-core half settles to idle after finish_boot, so normally the
        // frame arriving here IS `idle` and no delay happens at all.
        if (!this.bootSettled && this.state.orbState === 'starting' &&
            msg.state && msg.state !== 'starting' && msg.state !== 'idle') {
          this._settleBoot();
          this.updateOrbState('idle');
          this.emit('state', this.state);
          const deferred = msg;
          if (this._bootTimer) { clearTimeout(this._bootTimer); this._bootTimer = null; }
          this._bootTimer = setTimeout(() => {
            this._bootTimer = null;
            this._applyOrbState(deferred);
          }, BOOT_IDLE_BEAT_MS);
          break;
        }
        this._applyOrbState(msg);
        break;
      case 'needs_confirm':
        // PROTOCOL §9: brain emits needs_confirm; base state follows it even if
        // the paired orb_state frame is late/lost (orb renders, never decides).
        this.updateOrbState('confirm');
        this.state.jobsActive = Math.max(1, this.state.jobsActive);
        this.state.subtitle = msg.question || this.state.subtitle;
        this.emit('state', this.state);
        this.emit('confirm', msg);
        break;
      case 'job_event':
        this._trackJob(msg);
        this.emit('job_event', msg);
        break;
      case 'answer':
        // PROTOCOL §3: the final conversational reply (additive 2026-10-07).
        // Rendered as a banner — NOT as an orb_state.
        this.emit('answer', msg);
        break;
      case 'report':
        // PROTOCOL §3: long-form on-screen artifact. Banner only.
        this.emit('report', msg);
        break;
      case 'job_list':
        this.emit('job_list', msg.jobs || []);
        break;
      case 'notice':
        // PROTOCOL §3 `notice` (integrator-approved): roles ui+cli, fields
        // text/level/ts/job?. Explicitly NOT an orb_state — it must never move
        // the orb off its current state, it only speaks.
        this.emit('notice', msg);
        break;
      case 'subtitle':
        this.emit('subtitle', { job: msg.job, text: msg.text, fade_ms: msg.fade_ms });
        break;
      case 'speak':
        this.emit('speak', msg);
        break;
      case 'error':
        if (msg.code) {
          this.updateOrbState('error');
          this.emit('state', this.state);
        }
        break;
      case 'pong':
        this.pongMiss = 0;
        break;
      default:
        break;
    }
  }

  sendAuth() {
    if (this.authSent || !this.ws) return;
    this.authSent = true;
    this.ws.send(
      JSON.stringify({
        type: 'auth',
        v: 1,
        token: this.config.token || '',
        role: 'ui',
        client: this.config.client,
        client_v: this.config.clientV,
      })
    );
  }

  sendOrbInput(msg) {
    if (!this.ws || !this.connected) return;
    this.ws.send(JSON.stringify({ type: 'orb_input', ...msg }));
  }

  sendControl(msg) {
    if (!this.ws || !this.connected) return;
    this.ws.send(JSON.stringify({ type: 'control', ...msg }));
  }

  /** PROTOCOL §3 `command` — typed input entered on the orb (TODO §3e). */
  sendCommand(text) {
    if (!this.ws || !this.connected || !text) return false;
    this.ws.send(JSON.stringify({ type: 'command', v: 1, text, source: 'orb' }));
    return true;
  }

  /** PROTOCOL §3 `job_list` request — right-click menu job list. */
  requestJobList() {
    if (!this.ws || !this.connected) return false;
    this.ws.send(JSON.stringify({ type: 'job_list', v: 1 }));
    return true;
  }

  /** PROTOCOL §3 `cancel` — menu job cancel. scope `full`, because `gui`
   *  only releases the input lock and would leave the job running. */
  cancelJob(ref) {
    if (!this.ws || !this.connected) return false;
    this.ws.send(JSON.stringify({ type: 'cancel', v: 1, job: ref, scope: 'full' }));
    return true;
  }

  getOrbState() {
    return { ...this.state };
  }

  /** Apply one brain `orb_state` frame to the status state (AMENDMENT 2 split). */
  _applyOrbState(msg) {
    if (msg.state && ORB_STATES.has(msg.state)) {
      this.state.orbState = msg.state;
    } else if (msg.state) {
      // Unknown state name (state-name mismatch) — keep the last good one
      // but record it so the trace can prove WHO sent an unknown value.
      this.state.unknownState = msg.state;
    }
    this.state.jobsActive = msg.jobs_active || 0;
    this.state.mode = msg.mode || 'normal';
    this.state.private = this.state.mode === 'private' || msg.state === 'private_overlay' || !!msg.private;
    this.state.paused = this.state.mode === 'paused';
    this.state.subtitle = msg.subtitle || null;
    if (msg.provider) this.state.provider = msg.provider;
    if (msg.model) this.state.model = msg.model;
    this.state.shapeHint = (msg.shape_hint &&
      ['circle','triangle','square','pentagon','hexagon','octagram'].includes(msg.shape_hint))
      ? msg.shape_hint : null;
    if (msg.task_kind) this.state.taskKind = msg.task_kind;
    this.state.amplitude = (typeof msg.amplitude === 'number') ? msg.amplitude : null;
    // reserved + forwarded, never acted on (THEMES.md §5)
    this.state.evolveStage = ('evolve_stage' in msg) ? msg.evolve_stage : null;
    this.updateOrbState(this.state.orbState);
    this.emit('state', this.state);
  }

  updateOrbState(s) {
    if (s && ORB_STATES.has(s)) this.state.orbState = s;
    // AMENDMENT 2: leaving `starting` retires the auto-escape; re-entering it
    // starts a fresh (brief) window.
    if (this.state.orbState === 'starting') this._armBootEscape();
    else this._settleBoot();
  }

  clearTimers() {
    if (this.heartbeatTimer) clearInterval(this.heartbeatTimer);
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.heartbeatTimer = null;
    this.reconnectTimer = null;
  }

  /** Full shutdown — also retires the boot auto-escape timer so quit is clean. */
  dispose() {
    this._disposed = true;
    this.clearTimers();
    if (this._bootTimer) { clearTimeout(this._bootTimer); this._bootTimer = null; }
    try { if (this.ws) this.ws.close(); } catch (e) { /* already closed */ }
    this.ws = null;
  }

  startHeartbeat() {
    this.clearTimers();
    this.heartbeatTimer = setInterval(() => {
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
      this.pongMiss += 1;
      if (this.pongMiss >= 3) {
        this.ws.close();
        return;
      }
    }, this.config.heartbeatInterval);
  }

  scheduleReconnect() {
    if (this._disposed) return;
    const base = this.backoff;
    const jitter = (Math.random() * 2 - 1) * base * 0.2;
    let d = base + jitter;
    if (d < 100) d = 100;
    if (d > this.config.reconnectMax) d = this.config.reconnectMax;
    this.reconnectTimer = setTimeout(() => {
      this.backoff = Math.min(this.backoff * 1.5, this.config.reconnectMax);
      this.connect();
    }, d);
  }
}

module.exports = StatusWS;

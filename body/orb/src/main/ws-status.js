const EventEmitter = require('events');
const { WebSocket } = require('ws');

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
    };
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
        this.updateOrbState(this.state.orbState);
        this.emit('state', this.state);
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
      case 'job_list':
        this.emit('job_list', msg.jobs || []);
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

  /** PROTOCOL §3 `cancel` — menu job cancel. */
  cancelJob(ref) {
    if (!this.ws || !this.connected) return false;
    this.ws.send(JSON.stringify({ type: 'cancel', v: 1, job: ref, scope: 'gui' }));
    return true;
  }

  getOrbState() {
    return { ...this.state };
  }

  updateOrbState(s) {
    if (s && ORB_STATES.has(s)) this.state.orbState = s;
  }

  clearTimers() {
    if (this.heartbeatTimer) clearInterval(this.heartbeatTimer);
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.heartbeatTimer = null;
    this.reconnectTimer = null;
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

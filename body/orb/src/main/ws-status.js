const EventEmitter = require('events');
const { WebSocket } = require('ws');

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
    this.seq = 0;
    this.state = {
      orbState: 'starting',
      jobsActive: 0,
      mode: 'normal',
      private: false,
      paused: false,
      subtitle: null,
      shapeHint: 'circle',
      taskKind: 'none',
    };
  }

  start() {
    this.connect();
  }

  connect() {
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
      this.updateOrbState(this.state.private ? 'reconnecting' : 'reconnecting');
      this.scheduleReconnect();
    });
    this.ws.on('error', () => {
      if (this.ws) this.ws.close();
    });
  }

  handle(msg) {
    switch (msg.type) {
      case 'auth_ok':
        this.session = msg.session;
        this.backoff = this.config.reconnectInitial;
        this.updateOrbState('idle');
        this.emit('state', this.state);
        break;
      case 'auth_fail':
        this.updateOrbState('offline');
        this.emit('state', this.state);
        this.ws && this.ws.close();
        break;
      case 'orb_state':
        this.state.orbState = msg.state || this.state.orbState;
        this.state.jobsActive = msg.jobs_active || 0;
        this.state.mode = msg.mode || 'normal';
        this.state.private = this.state.mode === 'private' || !!msg.private;
        this.state.paused = this.state.mode === 'paused';
        this.state.subtitle = msg.subtitle || null;
        this.state.shapeHint = msg.shape_hint || 'circle';
        this.state.taskKind = msg.task_kind || 'none';
        this.updateOrbState(this.state.orbState);
        this.emit('state', this.state);
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
    this.ws.send(
      JSON.stringify({
        type: 'orb_input',
        ...msg,
      })
    );
  }

  sendControl(msg) {
    if (!this.ws || !this.connected) return;
    this.ws.send(
      JSON.stringify({
        type: 'control',
        ...msg,
      })
    );
  }

  getOrbState() {
    return { ...this.state };
  }

  updateOrbState(s) {
    // degraded states map as per §8
    if (s === 'starting') this.state.orbState = 'starting';
    else if (s === 'reconnecting') this.state.orbState = 'reconnecting';
    else if (s === 'offline') this.state.orbState = 'offline';
    else this.state.orbState = s;
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
      // server pings every 10s; client just needs to stay alive
      this.pongMiss += 1;
      if (this.pongMiss >= 3) {
        this.ws.close();
        return;
      }
    }, this.config.heartbeatInterval);
  }

  scheduleReconnect() {
    const jitter = Math.floor(Math.random() * (this.backoff * 0.4));
    const d = Math.min(this.backoff + (Math.random() > 0.5 ? jitter : -jitter), this.config.reconnectMax);
    this.reconnectTimer = setTimeout(() => {
      this.backoff = Math.min(this.backoff * 1.5, this.config.reconnectMax);
      this.connect();
    }, d);
  }
}

module.exports = StatusWS;

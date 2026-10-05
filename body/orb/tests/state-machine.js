// Pure state machine (unit-testable) as specified
class StateMachine {
  constructor(initial = {}) {
    this.state = {
      orbState: initial.orbState || 'starting',
      mode: initial.mode || 'normal',
      private: initial.mode === 'private' || !!initial.private,
      paused: initial.mode === 'paused' || !!initial.paused,
      shapeHint: initial.shapeHint || 'circle',
      taskKind: initial.taskKind || 'none',
      jobsActive: initial.jobsActive || 0,
      animation: 'rest',
      speakAmp: 0,
      speakPitch: null,
      crossfadeActive: false,
      crossfadeStart: 0,
      crossfadeDuration: 300,
    };
  }

  transitionTo(s) {
    if (s === this.state.orbState) return this.state;
    this.state.orbState = s;
    this.state.crossfadeActive = true;
    this.state.crossfadeStart = Date.now();
    if (s === 'speaking') {
      this.state.animation = 'speaking';
    } else if (s === 'acting') {
      this.state.animation = 'acting';
    } else {
      this.state.animation = 'rest';
    }
    return this.state;
  }

  onSpeak(ev) {
    if (!ev) return this.state;
    this.transitionTo('speaking');
    if (ev.event === 'start' || ev.event === 'chunk') {
      this.state.speakAmp = ev.amplitude !== undefined ? ev.amplitude : this.state.speakAmp;
      this.state.speakPitch = ev.pitch_hz !== undefined ? ev.pitch_hz : this.state.speakPitch;
    }
    if (ev.event === 'end') {
      this.state.speakAmp = 0;
      this.state.speakPitch = null;
      this.transitionTo('idle');
    }
    return this.state;
  }

  onAct(ev) {
    if (!ev) return this.state;
    this.transitionTo('acting');
    if (ev.shape_hint) this.state.shapeHint = ev.shape_hint;
    if (ev.task_kind) this.state.taskKind = ev.task_kind;
    if (ev.jobs_active !== undefined) this.state.jobsActive = ev.jobs_active;
    return this.state;
  }

  onOrbState(msg) {
    if (!msg) return this.state;
    if (msg.state) this.state.orbState = msg.state;
    if (msg.mode) {
      this.state.mode = msg.mode;
      this.state.private = msg.mode === 'private';
      this.state.paused = msg.mode === 'paused';
    }
    if (msg.shape_hint) this.state.shapeHint = msg.shape_hint;
    if (msg.task_kind) this.state.taskKind = msg.task_kind;
    if (msg.jobs_active !== undefined) this.state.jobsActive = msg.jobs_active;
    return this.state;
  }

  onPrivate(v) {
    this.state.private = !!v;
    this.state.mode = this.state.private ? 'private' : 'normal';
    return this.state;
  }
}

module.exports = StateMachine;

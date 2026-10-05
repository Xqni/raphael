const StateMachine = require('./state-machine');

function assertEqual(a, b, msg) {
  if (a !== b) throw new Error(`${msg}: ${a} !== ${b}`);
}
function assertClose(a, b, eps, msg) {
  if (Math.abs(a - b) > eps) throw new Error(`${msg}: |${a}-${b}| > ${eps}`);
}

function testIdleToSpeaking() {
  const sm = new StateMachine({ orbState: 'idle' });
  sm.onSpeak({ event: 'start', amplitude: 0.5, pitch_hz: 200, seq: 1 });
  assertEqual(sm.state.animation, 'speaking', 'speaking');
  assertClose(sm.state.speakAmp, 0.5, 1e-9);
  assertClose(sm.state.speakPitch, 200, 1e-9);
}

function testActShapeMorph() {
  const sm = new StateMachine({ orbState: 'idle', shapeHint: 'circle' });
  sm.onAct({ shape_hint: 'octagram', task_kind: 'llm', jobs_active: 2 });
  assertEqual(sm.state.orbState, 'acting');
  assertEqual(sm.state.shapeHint, 'octagram');
  assertEqual(sm.state.taskKind, 'llm');
  assertEqual(sm.state.jobsActive, 2);
}

function testCrossfade() {
  const sm = new StateMachine({ orbState: 'thinking' });
  sm.transitionTo('acting');
  assertEqual(sm.state.crossfadeActive, true);
}

function testPrivateOverlay() {
  const sm = new StateMachine({ orbState: 'idle', mode: 'private' });
  sm.onPrivate(true);
  assertEqual(sm.state.mode, 'private');
  assertEqual(sm.state.private, true);
}

function testSpeakEndReset() {
  const sm = new StateMachine({ orbState: 'idle' });
  sm.onSpeak({ event: 'start', amplitude: 0.7, seq: 1 });
  sm.onSpeak({ event: 'end', seq: 2 });
  assertEqual(sm.state.speakAmp, 0, 'amp reset');
  assertEqual(sm.state.speakPitch, null, 'pitch reset');
}

function testMissingPitchAmplitudeOnly() {
  const sm = new StateMachine({ orbState: 'idle' });
  sm.onSpeak({ event: 'chunk', amplitude: 0.3, seq: 1 });
  assertClose(sm.state.speakAmp, 0.3, 1e-9);
  assertEqual(sm.state.speakPitch, null);
}

function testConfirmTransition() {
  const sm = new StateMachine({ orbState: 'thinking' });
  sm.transitionTo('confirm');
  assertEqual(sm.state.orbState, 'confirm');
  assertEqual(sm.state.crossfadeActive, true);
}

function testStaleSeqDrop() {
  const sm = new StateMachine({ orbState: 'idle' });
  sm.onSpeak({ event: 'start', amplitude: 0.9, seq: 5 });
  sm.onSpeak({ event: 'chunk', amplitude: 0.1, seq: 5 });
  assertClose(sm.state.speakAmp, 0.9, 1e-9);
}

testIdleToSpeaking();
testActShapeMorph();
testCrossfade();
testPrivateOverlay();
testSpeakEndReset();
testMissingPitchAmplitudeOnly();
testConfirmTransition();
testStaleSeqDrop();
console.log('All state machine tests passed');
process.exit(0);

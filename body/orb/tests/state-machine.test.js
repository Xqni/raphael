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

// Was `testStaleSeqDrop`: it asserted that a repeated seq was dropped. That
// contract is what caused BUGS-WAVE2 Bug C — a fresh utterance legitimately
// re-uses seqs, so "dropping" them meant dropping the pulse. The transport is
// an ordered WebSocket, so nothing needs to be dropped; the high-water mark is
// kept for diagnostics only.
function testRepeatedSeqIsNotDropped() {
  const sm = new StateMachine({ orbState: 'idle' });
  sm.onSpeak({ event: 'start', amplitude: 0.9, seq: 5 });
  sm.onSpeak({ event: 'chunk', amplitude: 0.1, seq: 5 });
  assertClose(sm.state.speakAmp, 0.1, 1e-9, 'the newest amplitude wins');
  assertEqual(sm.state.lastSpeakSeq, 5, 'high-water mark is unchanged');
}

// --- Bug C regressions: the pulse must survive a seq reset ----------------
function testSeqResetWithinRun() {
  const sm = new StateMachine({ orbState: 'idle' });
  sm.onSpeak({ event: 'chunk', amplitude: 0.2, seq: 8 });
  assertClose(sm.state.speakAmp, 0.2, 1e-9, 'utterance 1');
  // fresh utterance, no `start` event, counter restarts at 0 -> must be ACCEPTED
  sm.onSpeak({ event: 'chunk', amplitude: 0.9, seq: 0 });
  assertClose(sm.state.speakAmp, 0.9, 1e-9, 'utterance 2 after seq reset');
  // lastSpeakSeq is a HIGH-WATER MARK now (nothing is dropped), so it must NOT
  // go backwards — that is the whole point of the Bug C fix.
  assertEqual(sm.state.lastSpeakSeq, 8, 'high-water mark unchanged');
}

function testSeqResetOnStartEvent() {
  const sm = new StateMachine({ orbState: 'idle' });
  sm.onSpeak({ event: 'chunk', amplitude: 0.3, seq: 12 });
  sm.onSpeak({ event: 'start', amplitude: 0.7, seq: 0 });
  assertClose(sm.state.speakAmp, 0.7, 1e-9, 'start event restarts the run');
}

function testSeqEndResets() {
  const sm = new StateMachine({ orbState: 'speaking' });
  sm.onSpeak({ event: 'chunk', amplitude: 0.4, seq: 6 });
  sm.onSpeak({ event: 'end', seq: 7 });
  assertEqual(sm.state.lastSpeakSeq, -1, 'end clears the tracker');
  assertEqual(sm.state.speakAmp, 0, 'end clears amplitude');
  sm.onSpeak({ event: 'chunk', amplitude: 0.95, seq: 0 });
  assertClose(sm.state.speakAmp, 0.95, 1e-9, 'next utterance pulses again');
}

testSeqResetWithinRun();
testSeqResetOnStartEvent();
testSeqEndResets();
testIdleToSpeaking();
testActShapeMorph();
testCrossfade();
testPrivateOverlay();
testSpeakEndReset();
testMissingPitchAmplitudeOnly();
testConfirmTransition();
testRepeatedSeqIsNotDropped();
console.log('All state machine tests passed');
process.exit(0);

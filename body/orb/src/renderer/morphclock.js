// Morph ramp clock (Wave 4 — reconnect-storm / state-spam hardening).
//
// `startMorphTo` is called on every shape change. The ramp clock is a piece of
// mutable state that must behave DIFFERENTLY depending on whether a ramp is
// already running:
//
//   fresh ramp  -> start now
//   RETARGET    -> KEEP the original start, so progress keeps advancing
//
// The bug this prevents: resetting the clock on every retarget means a state
// that flips faster than the ramp duration (the `speaking -> listening ->
// speaking` flicker of BUGS-WAVE2 Bug E, or any reconnect storm) restarts from
// 0 each time and the lattice never gets past a few percent — it parks at its
// start shape and looks "stuck". Keeping the clock means progress is a function
// of WALL-CLOCK time, so a storm still converges on the newest target.
//
// Pure (no DOM, no clock) so it can be simulated in plain Node.

/** @returns {number} the morphStart to use after a (re)target request */
export function nextMorphStart({ active, morphStart, now }) {
  if (!active || !Number.isFinite(morphStart)) return now;   // fresh ramp
  return morphStart;                                          // retarget: keep progress
}

/** Clamped 0..1 ramp progress from an elapsed time. */
export function morphProgress(elapsed, duration) {
  if (!(duration > 0)) return 1;
  const p = elapsed / duration;
  return p < 0 ? 0 : p > 1 ? 1 : p;
}

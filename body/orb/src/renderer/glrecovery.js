// GPU context loss recovery (Wave 4, hardening).
//
// A WebGL context can be lost at any time (driver reset, sleep/resume, another
// app taking the GPU). Chromium only fires `webglcontextrestored` if the
// `webglcontextlost` listener calls preventDefault(), so the handler MUST do
// that or the canvas is dead forever.
//
// Recovery is a page reload: Three.js has already uploaded every buffer to the
// old context and there is no safe way to replay that here. The reload is
// rate-limited, because a context that keeps dying would otherwise put the orb
// into a reload loop — which is strictly worse than a frozen orb.
//
// Pure on purpose: no DOM, no GPU, injectable clock — so the policy is unit
// tested in plain Node (AGENTS rule: smallest test target first).
export function createGlRecovery(opts = {}) {
  const reload = opts.reload || (() => {});
  const now = opts.now || (() => Date.now());
  const cooldownMs = opts.cooldownMs === undefined ? 15000 : opts.cooldownMs;

  let lost = false;
  let restores = 0;
  let reloads = 0;
  let suppressed = 0;
  let lastReload = -Infinity;

  return {
    /** @returns {boolean} whether the event was cancelled (required for restore) */
    onLost(e) {
      if (e && typeof e.preventDefault === 'function') e.preventDefault();
      lost = true;
      restores = 0;
      return true;
    },
    /** @returns {'reloaded'|'suppressed'} */
    onRestored() {
      lost = false;
      restores += 1;
      if (now() - lastReload < cooldownMs) {
        suppressed += 1;
        return 'suppressed';
      }
      lastReload = now();
      reloads += 1;
      reload();
      return 'reloaded';
    },
    /** true while the context is gone — the render loop must skip GL work */
    isLost: () => lost,
    state: () => ({ lost, restores, reloads, suppressed, lastReload }),
  };
}

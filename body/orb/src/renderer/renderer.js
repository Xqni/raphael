import * as THREE from 'three';
import { vertexShader, sphereVert } from './shaders/vertex.glsl.js';
import { fragmentShader, glowShader } from './shaders/fragment.glsl.js';
import { blurVert, blurFrag } from './shaders/blur.glsl.js';
import { initSageCore, initCageShape, updateSageCore, lockSageCore, projectShape, applySagePalette } from './sagecore.js';
import { initAnswerMode, updateAnswerMode, lockAnswerMode, applyAnswerPalette } from './answermode.js';
import { initDataRings, updateDataRings, lockDataRings } from './datarings.js';
import { initJobDots, updateJobDots, lockJobDots, applyJobPalette } from './jobdots.js';
import { resolvePalette } from './palette.js';
import { makeMorphTarget, MORPH_SHAPES, BASE_VERTEX_COUNT } from './morphtargets.js';
import { createGlRecovery } from './glrecovery.js';
import { nextMorphStart, morphProgress } from './morphclock.js';

// Configuration injected via preload
const cfg = window.orbConfig || {
  sizePx: 280, contentPx: 200, opacity: 0.95, fpsCap: 60, quality: 'auto',
  backingDiscAlpha: 0.0, reducedMotion: false,
  theme: 'raphael', vibrance: 1.15, motionBlur: 'auto', startupSpinTauMs: 1400,
};

// §5 theme hook + §3.7 vibrance — resolved at page load, then RE-RESOLVED live
// when main reports the config changed (persona.tier switch, see docs/orb/THEMES.md).
// MUST come after `cfg`.
let PAL = resolvePalette(cfg);
/** Push the current palette into every themed uniform (cheap, no reallocation). */
function applyPalette() {
  applySagePalette(sage, PAL);
  applyAnswerPalette(AM, PAL);
  applyJobPalette(JD, PAL);
}
const palInt = (hex) => parseInt(String(hex).replace('#', ''), 16);

let sizePx = cfg.sizePx;
let fpsCap = cfg.fpsCap;
let quality = cfg.quality;
let backingDiscAlpha = cfg.backing_disc_alpha || cfg.backingDiscAlpha || 0.0;
let lastFrame = 0;
let frameCount = 0;
let lastFpsUpdate = performance.now();
const fpsEl = document.getElementById('fps'); // null on production page (index.html)
// Glide lag state — main sends velocity during roam glides (solar inertia)
let glideTX = 0, glideTY = 0, glideTB = 0;
let GLX = 0, GLY = 0, GLB = 0;
let frameInterval = 1000 / fpsCap;

// --- Frame-time governor (spec §5: "automatic downgrade if frames are slow").
// Only meaningful for quality:'auto' — explicit low/medium/high stay forced.
// Policy: EMA of achieved frame intervals vs the current target interval;
// ~1.5s sustained slow -> downshift pixel-ratio one rung (4s cooldown);
// ~6s sustained headroom -> climb back, never above the startup rung.
const GOV_LADDER = [0.5, 0.75, 1, 1.5, 2]; // pixel-ratio rungs
const GOV = { on: quality === 'auto', idx: 0, ceiling: 0, ema: 0,
              slow: 0, fast: 0, nextAt: 0, seen: 0, lastAt: 0, acted: 0 };
let govApply = null; // bound inside initScene (closure over resizeEdgeRT)


const canvas = document.getElementById('webgl');
// Wave-4 hardening: recover from a lost GPU context. preventDefault() on
// `webglcontextlost` is mandatory (Chromium only fires `restored` if it is
// called); recovery reloads the page because Three.js cannot replay its
// uploads into a new context, rate-limited so a dying context cannot loop.
const glRecovery = createGlRecovery({ reload: () => window.location.reload() });
if (canvas) {
  canvas.addEventListener('webglcontextlost', (e) => {
    console.warn('[orb] WEBGL CONTEXT LOST');
    glRecovery.onLost(e);
  }, false);
  canvas.addEventListener('webglcontextrestored', () => {
    const how = glRecovery.onRestored();
    console.warn('[orb] WEBGL CONTEXT RESTORED ->', how);
  }, false);
}
window.__orbGl = () => glRecovery.state();
const subtitleEl = document.getElementById('subtitle');
// AMENDMENT 3 (user, 2026-10-07): NO ON-SCREEN TEXT — "text displays under
// her, a whole box of the answer, the red mic->cloud pill — none of that.
// Just speech." EVERYTHING the orb could draw as text funnels through
// updateSubtitle() — the brain's own `subtitle` frame, `notice`, `answer`,
// `report` cards and the demo label — so this one gate kills all of it, and the
// `#micbadge` element was deleted outright (the pill was the named offender).
//
// The PROTOCOL §3 frames are UNCHANGED: they still arrive and are still
// recorded by traceRx, so CLI/API consumers keep working. The orb simply never
// renders them. "KEEP cage/colors/pulse/job-dots + on-demand menu" — the
// right-click menu (incl. the mic-cloud row) is user-invoked and untouched.
const ORB_TEXT_ENABLED = false;

// WAVE 5U §5.6 task 1 — ORB CONFIRM CARD (owner pre-approval 3: "confirm cards
// allowed in the chat UI and on the orb (orb only in confirm state)").
// The ONLY text allowed through while ORB_TEXT_ENABLED is false. Painted with
// `textContent` (never innerHTML) because PROTOCOL §9 question / §3 frames are
// UNTRUSTED input, and hidden with `display:none` so document.body.innerText
// stays 0 everywhere else — which is exactly the gate's check.
const cc = {
  root: document.getElementById('confirmcard'),
  head: document.querySelector('#confirmcard .cc-head'),
  risk: document.querySelector('#confirmcard .cc-risk'),
  detail: document.querySelector('#confirmcard .cc-detail'),
  job: document.querySelector('#confirmcard .cc-job'),
  pending: null,   // last needs_confirm payload, or null once resolved/expired
};
if (cc.root) {
  cc.root.querySelectorAll('.cc-actions button').forEach((btn) => {
    btn.addEventListener('click', () => {
      // PROTOCOL §3 orb_input -> brain/ws.py:664 resolves the oldest pending
      // confirm for any of menu|click|confirm. The card does NOT hide here: it
      // hides when the Brain moves the state off `confirm`, so a REJECTED
      // confirmation keeps the card up instead of silently vanishing.
      const answer = btn.getAttribute('data-answer');
      if (!answer || !cc.pending) return;
      traceRx('confirm_out', { kind: 'confirm', value: answer, job: cc.pending.job || null });
      window.raphael.sendOrbInput({ kind: 'confirm', value: answer });
    });
  });
}

/** Paint a needs_confirm payload. Only renders fields that ACTUALLY arrived —
 *  action/target/detail are brain-core P0.3 and may be absent, in which case the
 *  card degrades to the guaranteed question + risk + job rather than showing a
 *  placeholder that lies. */
function renderConfirmCard(c) {
  if (!cc.root || !c) return;
  const headline = (c.action && c.target) ? `${c.action} \u2192 ${c.target}`
                                          : (c.question || '');
  cc.head.textContent = headline;                     // textContent = escaped
  cc.risk.textContent = c.risk ? String(c.risk) : '';
  cc.risk.hidden = !c.risk;
  cc.detail.textContent = c.detail ? String(c.detail) : '';
  cc.detail.hidden = !c.detail;
  cc.job.textContent = c.job ? `job ${c.job}` : '';
  cc.job.hidden = !c.job;
}

/** Visible ONLY while the orb is in `confirm` with a live, unexpired request —
 *  the state is the single authority (PROTOCOL §9: the orb renders, it never
 *  decides). */
function updateConfirmCard() {
  if (!cc.root) return;
  const inConfirm = orbState.orbState === 'confirm';
  // Resolved means the Brain moved OFF `confirm` — the request is no longer
  // pending, so drop it. A REJECTION never moves the state, which is exactly
  // why the card stays up there (and why dropping on state-change is safe).
  // Without this the last payload would linger and be re-shown by a later
  // synthetic `confirm` state with stale text.
  if (!inConfirm) cc.pending = null;
  const live = !!cc.pending && inConfirm &&
               (!cc.pending.expires_at || Date.now() < cc.pending.expires_at);
  cc.root.classList.toggle('show', live);
}
const params = new URLSearchParams(window.location.search);
const DEMO = params.get('demo') === '1';

let orbState = {
  orbState: 'starting',
  jobsActive: 0,
  mode: 'normal',
  private: false,
  paused: false,
  shapeHint: 'circle',
  serverShapeHint: null, // last `shape_hint` that arrived on an orb_state frame
  taskKind: 'none',
  provider: null,
  model: null,
};
let speakAmp = 0;
let speakPitch = null;
let lastSpeakSeq = -1;
let subtitleTimer = null;

// --- W2.1 frame trace: every state/speak/subtitle frame the renderer RECEIVES
// (IPC) plus the state it APPLIED. Read by test/orb-trace.cjs over CDP — this
// is the renderer half of the end-to-end evidence chain.
const TRACE_MAX = 200;
const TRACE_RX = [];
function traceRx(kind, data) {
  TRACE_RX.push({ t: Math.round(performance.now()), kind, data });
  if (TRACE_RX.length > TRACE_MAX) TRACE_RX.shift();
}

// AMENDMENT 2 evidence: every RENDERED state transition, seeded at module scope
// with the constructor's `starting` (not on the first animation frame — a fast
// auth_ok can land before rAF ever ticks). Read by test/orb-trace.cjs over CDP
// so the sequence can be asserted end-to-end through the IPC wiring.
const STATE_HISTORY = [{ state: orbState.orbState, at: 0 }];
function noteState(now) {
  const last = STATE_HISTORY[STATE_HISTORY.length - 1];
  if (last && last.state === orbState.orbState) return;
  STATE_HISTORY.push({ state: orbState.orbState, at: Math.round(now || performance.now()) });
  if (STATE_HISTORY.length > 60) STATE_HISTORY.shift();
}

// Crossfade
const CROSSFADE_DURATION = 300;
let crossfadeActive = false;
let crossfadeStart = 0;
let crossfadeTargetState = null;
let crossfadeFrom = { tint: 0xffffff, intensity: 1 };

// Morph
const MORPH_DURATION = 600;
const GROUP_SPIN = Math.random() > 0.5 ? 1 : -1; // randomized y-spin direction per launch
let morphActive = false;
let morphStart = 0;
let morphFrom = null;
let morphTo = null;

// Damping utility
function damp(current, target, tau, dt) {
  const alpha = 1 - Math.exp(-dt / tau);
  return current + (target - current) * alpha;
}

// Layer weight targets per state. latticeOpacity = the CYAN morph lattice,
// which now carries each state's signature SHAPE (user: "morph the states").
// `paused` is reached through MODE (INTERFACES §e) and fully overrides the
// base state's look — see modeTarget() below.
const STATE_LAYER_TARGETS = {
  idle: { coreScale:1, haloOpacity:0.25, latticeOpacity:0.14 },
  listening: { coreScale:1.1, haloOpacity:0.3, latticeOpacity:0.5 },
  thinking: { coreScale:1.2, haloOpacity:0.35, latticeOpacity:0.6 },  // §3.3: fewer lines, not yarn
  acting: { coreScale:1.3, haloOpacity:0.4, latticeOpacity:0.6 },
  speaking: { coreScale:1.2, haloOpacity:0.35, latticeOpacity:0.55 },
  error: { coreScale:0.9, haloOpacity:0.2, latticeOpacity:0.75 },
  reconnecting: { coreScale:1, haloOpacity:0.2, latticeOpacity:0.45 },
  offline: { coreScale:0.8, haloOpacity:0.1, latticeOpacity:0.06 },
  private_overlay: { coreScale:1, haloOpacity:0.25, latticeOpacity:0.14 },
  confirm: { coreScale:1, haloOpacity:0.3, latticeOpacity:0.7 },
  starting: { coreScale:1, haloOpacity:0.25, latticeOpacity:0.35 },
  paused: { coreScale:0.85, haloOpacity:0.15, latticeOpacity:0.5 },
};
/** MODE wins over state for layer weights (private is an OVERLAY: base look). */
function modeTarget(state, mode) {
  if (mode === 'paused') return STATE_LAYER_TARGETS.paused;
  return STATE_LAYER_TARGETS[state] || STATE_LAYER_TARGETS.idle;
}

// ---------------------------------------------------------------------------
// USER DIRECTIVE (2026-10-07) — shape morphing is OFF.
//
//   "revert back the shape change — the color change (+ the speaking state) is
//    the only thing we are okay with. i have other plans for shape changing
//    for future."
//
// The lattice and the cage hold ONE stable base shape (the plain ball) at all
// times: no per-state morph, no task-kind morph, no kind accents. Everything
// else stays — colour/theme per state, the speaking pulse/amplitude animation,
// banners, the parallel-minds fan-out.
//
// The machinery is deliberately NOT deleted, only not applied: STATE_SHAPE,
// MORPH_SHAPES, orb.shape_map, the morph engine, startMorphTo and the kind
// map are all still here. Setting the two flags below re-enables it.
//
// Bonus: with morphs off the lattice/cage can never wedge again — this closes
// the "cages stuck in weird shape" complaint for good.
// ---------------------------------------------------------------------------
// USER (2026-10-07): the CAGES are built as 3D wireframe SPHERES (sagecore);
// the lattice's constant morph key is the circle — the sphere's silhouette —
// so nothing on screen morphs. Constant either way: no per-state morph, no
// task-kind morph, no kind accents. "the only change in state would be the
// color."
const BASE_SHAPE = 'circle';
const SHAPE_MORPHS_ENABLED = false;
const KIND_ACCENTS_ENABLED = false;

/**
 * Effective lattice shape (PROTOCOL §8 + ORB_REBUILD §3).
 * Below the flag is the original mapping, kept intact for the future:
 * each state owns a signature shape; the server's `shape_hint` wins only while
 * a foreground task is running (task_kind !== 'none'), which is exactly the
 * "morph by task kind" case from config orb.shape_map.
 */
function effectiveShape() {
  if (!SHAPE_MORPHS_ENABLED) return BASE_SHAPE;
  const taskOwned = !!orbState.taskKind && orbState.taskKind !== 'none';
  if (taskOwned && orbState.serverShapeHint) return orbState.serverShapeHint;
  return STATE_SHAPE[orbState.orbState] || orbState.serverShapeHint || BASE_SHAPE;
}
// State -> morph shape (600ms vertex morph, existing machinery). 'acting' is
// owned by the task-kind map (config orb.shape_map / shapeHint, spec §3).
const STATE_SHAPE = {
  idle: 'circle', listening: 'pentagon', thinking: 'octagram', acting: null,
  speaking: 'hexagon', error: 'triangle', confirm: 'square', starting: 'circle',
  reconnecting: 'circle', offline: 'circle', private_overlay: 'circle',
  paused: 'circle',
};
let lastShapeState = null;
let layerWeights = { coreScale:1, haloOpacity:0.25, latticeOpacity:0.35 };


// Scene
let renderer, scene, camera, clock;
let group, core, lattice, halo, rings = [], rays, starsMesh, sage, glowGhosts = [];
let AM = null; // Answer Mode (gold magic-circle) module handle
let DR = null; // Data Rings (prismatic thinking overlay) module handle
let JD = null; // jobs_active orbiting dots (PROTOCOL §8)
// Pose lock (test hook): see __orbLockPose(). Production never sets it.
let poseLock = false;
const POSE_T = 2.0; // pinned animation clock used while locked
let lastNow = 0;    // previous rAF tick (dt source — see animate())
const ft = { last: 0, ema: 0, n: 0 }; // frame-time probe (§2/§4)

// --- §2 cheap motion blur ---------------------------------------------------
// One LOW-RES angular smear of the scene we already rendered, mixed in by the
// existing edge-mask pass (so: zero extra full-resolution passes). Velocity
// gated — when the orb is calm the pass is not executed at all, which is what
// keeps idle cost identical to before.
let blurRT = null, blurScene = null, blurCam = null, blurMat = null;
const blurState = { amount: 0, angle: 0, taps: 0, skipped: true, reason: 'init' };
let motionBlurOverride = null;  // 'off' | 'force' | null (measurement hook)
const BLUR_CALM = 0.35;         // rad/s — below this the rim moves <0.1 deg/frame
const BLUR_FAST = 1.60;         // rad/s — full smear at/above this
const BLUR_MAX_ANGLE = 0.12;    // rad — cap so a hitch can never smear wildly
// Physical rotation (§1). ONE angular-velocity source drives the whole
// assembly: `angle` is integrated state (never reset, never eased), and
// `omega` relaxes exponentially toward its target with a configurable tau, so
// velocity is C1 across every hand-off. `omega` is a MAGNITUDE — GROUP_SPIN
// carries the direction, which keeps omega positive so a genuine reversal
// shows up as a zero crossing in the trace instead of hiding in a sign flip.
//
// BASELINE (2026-10-06, before this rewrite) measured against the old
// bell-curve `genSpin` velocity profile:
//   peak 21.12 rad/s, rest 0.50 rad/s, +6.13 rad/s JUMP at the hand-off,
//   fit R^2 0.89 / implied tau 977 ms, and only 6.9% of the delta left at
//   1.5x tau — i.e. it eased out far too early and then stopped decelerating.
let spin = null;
const SPIN_REST = 0.003 * 60;   // the group's rest rate at the 60 fps design point (rad/s)
const SPIN_PEAK = 3.2;          // startup spin-up target (rad/s)
const SPIN_UP_MS = 400;         // smooth rise into the peak — omega is never snapped
function ensureSpin() {
  if (!spin) {
    spin = {
      angle: 0,
      omega: SPIN_REST,
      target: SPIN_REST,
      tau: SPIN_UP_MS,
      rest: SPIN_REST,
      peak: SPIN_PEAK,
      tauStartup: (cfg && cfg.startupSpinTauMs) || 1400,
      phase: 'run',       // run -> spinup -> settle -> run
      phaseStart: 0,
    };
  }
  return spin;
}
/** Begin a startup sequence: relax omega UP to the peak, then decay it. */
function armStartup(now) {
  ensureSpin();
  spin.phase = 'spinup';
  spin.tau = SPIN_UP_MS;
  spin.target = spin.peak;
  spin.phaseStart = now;
}
/** dt-based integration, dt already clamped by the caller. */
function stepSpin(now, dt) {
  const s = ensureSpin();
  if (s.phase === 'spinup' && now - s.phaseStart >= SPIN_UP_MS) {
    s.phase = 'settle';
    s.tau = s.tauStartup;      // the configured orb.startup.spin_tau_ms
    s.target = s.rest;
    s.phaseStart = now;
  } else if (s.phase === 'settle' &&
             Math.abs(s.omega - s.rest) < 0.05 * Math.max(s.peak - s.rest, 1e-6)) {
    s.phase = 'run';           // no snap: target stays at rest, relax continues
  }
  s.omega += (s.target - s.omega) * (1 - Math.exp(-dt / s.tau));
  if (s.omega < 0) s.omega = 0; // magnitude, never negative
  s.angle += s.omega * (dt / 1000);
  return s;
}
/** True while the startup spin-down is still visibly in progress (§1: the
 *  frame-time governor must not change quality mid-startup and cause a hitch). */
function spinSettling() {
  return !!spin && (spin.phase !== 'run' || orbState.orbState === 'starting');
}
let edgeRT = null, maskScene = null, maskCam = null, maskMat = null;
const sceneStats = { calls: 0, tris: 0 }; // cached AFTER the scene pass (mask pass resets renderer.info)

// Geometry targets for morph
function easeInOutCubic(x) {
  return x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2;
}

function initScene() {
  renderer = new THREE.WebGLRenderer({ canvas, antialias: false, alpha: true, premultipliedAlpha: true }); // AA off: fill-rate cost (software GL in WSLg; lines are shader-thin anyway)
  // Quality tier handling
  if (quality === 'low') renderer.setPixelRatio(0.5);
  else if (quality === 'medium') renderer.setPixelRatio(1);
  else if (quality === 'high') renderer.setPixelRatio(2);
  else {
    let d = window.devicePixelRatio;
    try { // auto: software GL (SwiftShader/llvmpipe) -> cut pixels (spec §5: tiers by GPU type)
      const gl = renderer.getContext();
      const dbg = gl.getExtension('WEBGL_debug_renderer_info');
      const rname = String(dbg ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER) || '');
      if (/swiftshader|llvmpipe|softpipe|software/i.test(rname)) d = 0.75;
    } catch (e) { /* keep dPR */ }
    renderer.setPixelRatio(d); // auto
  }
  renderer.setClearColor(0x000000, 0);
  renderer.setSize(sizePx, sizePx);

  // --- Screen-space EDGE MASK (post pass): everything is composited through
  // this, and the outer 8% of every side fades to zero. Glide offsets push
  // layer content PAST its per-shader fades into the window boundary (user:
  // "glow hits the sides of the box and seems cut on the edge") — this
  // guarantees a soft fade instead of a hard cut, for ALL layers at once.
  const dprNow = renderer.getPixelRatio();
  edgeRT = new THREE.WebGLRenderTarget(
    Math.max(2, Math.round(sizePx * dprNow)),
    Math.max(2, Math.round(sizePx * dprNow)),
    { minFilter: THREE.LinearFilter, magFilter: THREE.LinearFilter, format: THREE.RGBAFormat, depthBuffer: true }
  );
  maskScene = new THREE.Scene();
  maskCam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
  maskMat = new THREE.ShaderMaterial({
    uniforms: { tScene: { value: edgeRT.texture }, uCA: { value: 0 },
                tBlur: { value: null }, uBlur: { value: 0 } },
    vertexShader: 'varying vec2 vUv; void main() { vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }',
    fragmentShader: [
      'precision mediump float;',
      'varying vec2 vUv;',
      'uniform sampler2D tScene;',
      'uniform sampler2D tBlur;',
      'uniform float uCA;',
      'uniform float uBlur;',
      'void main() {',
      '  vec4 c = texture2D(tScene, vUv);',
      // §2: mix in the low-res angular smear. BOTH inputs are premultiplied
      // RGBA, so the mix is too — no dark box, halo or ghost on any wallpaper.
      '  if (uBlur > 0.001) c = mix(c, texture2D(tBlur, vUv), uBlur);',
      // chromatic aberration at the outer edge while Answer Mode is active
      '  vec2 rc = vUv - 0.5;',
      '  vec2 off = rc * 0.010 * uCA * smoothstep(0.35, 0.75, length(rc));',
      '  vec3 col = vec3(texture2D(tScene, vUv + off).r, c.g, texture2D(tScene, vUv - off).b);',
      '  float m = smoothstep(0.0, 0.06, vUv.x) * smoothstep(1.0, 0.94, vUv.x)',
      '          * smoothstep(0.0, 0.06, vUv.y) * smoothstep(1.0, 0.94, vUv.y);',
      '  gl_FragColor = vec4(col * m, c.a * m);', // premultiplied out
      '}',
    ].join('\n'),
    depthTest: false,
    depthWrite: false,
    blending: THREE.NoBlending, // straight replace of the framebuffer
  });
  maskScene.add(new THREE.Mesh(new THREE.PlaneGeometry(2, 2), maskMat));

  // §2: the low-res blur target + its fullscreen quad. Created once; the
  // runtime decides every frame whether the pass runs at all.
  blurScene = new THREE.Scene();
  blurCam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
  blurMat = new THREE.ShaderMaterial({
    uniforms: {
      tScene: { value: edgeRT.texture },
      uAngle: { value: 0 },
      uRadius: { value: 1.0 },
      uTaps: { value: 4 },
    },
    vertexShader: blurVert,
    fragmentShader: blurFrag,
    depthTest: false,
    depthWrite: false,
    blending: THREE.NoBlending,
  });
  blurScene.add(new THREE.Mesh(new THREE.PlaneGeometry(2, 2), blurMat));
  blurRT = new THREE.WebGLRenderTarget(2, 2, {
    minFilter: THREE.LinearFilter, magFilter: THREE.LinearFilter,
    format: THREE.RGBAFormat, depthBuffer: false, stencilBuffer: false,
  });
  maskMat.uniforms.tBlur.value = blurRT.texture;

  function resizeEdgeRT(w, h) {
    const dpr = renderer.getPixelRatio();
    const ew = Math.max(2, Math.round(w * dpr));
    const eh = Math.max(2, Math.round(h * dpr));
    if (edgeRT) edgeRT.setSize(ew, eh);
    // the blur target is a fixed FRACTION of the scene target — §2 forbids a
    // full-resolution post pass
    if (blurRT) blurRT.setSize(Math.max(2, Math.round(ew * 0.5)), Math.max(2, Math.round(eh * 0.5)));
  }
  resizeEdgeRT(sizePx, sizePx);

  // Governor binding: snap the ladder to the STARTUP ratio (never climb above
  // what the GPU was trusted with) and capture resizeEdgeRT in a closure —
  // it is function-scoped here, not visible from animate().
  if (GOV.on) {
    const startRatio = renderer.getPixelRatio();
    GOV.ceiling = GOV_LADDER.reduce((best, v, i) =>
      Math.abs(v - startRatio) < Math.abs(GOV_LADDER[best] - startRatio) ? i : best, 0);
    GOV.idx = GOV.ceiling;
    govApply = () => {
      renderer.setPixelRatio(GOV_LADDER[GOV.idx]);
      renderer.setSize(sizePx, sizePx);
      resizeEdgeRT(sizePx, sizePx); // edge RT bakes dpr — must follow the tier
    };
  }

  scene = new THREE.Scene();
  camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
  // Box vs content decoupled (user): window = size_px (280), Raphael renders
  // at content_px (200) by zooming OUT — structured content then sits deep
  // inside the edge-safe zone; rays can never touch the mask (cut-proof).
  const contentPx = cfg.contentPx || 200;
  // §3.6 legibility: the orb must fill ~85-90% of content_px AND never be
  // clipped by the 6% edge mask. `1.5 * size/content` breaks once the window
  // is smaller than content_px (160 px -> halfW 1.2 -> the outer layers land
  // OUTSIDE the window), so clamp to the outermost layer's safe radius.
  const OUTER_R = 1.35;                      // job dots, the outermost layer
  const halfW = Math.max(1.5 * (sizePx / contentPx), OUTER_R / 0.86);
  camera.position.z = halfW / Math.tan(THREE.MathUtils.degToRad(camera.fov / 2));

  clock = new THREE.Clock();

  group = new THREE.Group();
  scene.add(group);

  // Core = 3D SPHERE ball (normal-based anime shading) + glow billboard behind
  // it, sharing ONE uniforms object (single brightness damping path).
  const coreU = { color: { value: new THREE.Color(0xffffff) }, uBright: { value: 1.0 }, uAmp: { value: 0.0 } };
  const coreMat = new THREE.ShaderMaterial({
    vertexShader: sphereVert,
    fragmentShader,
    uniforms: coreU,
    transparent: true,   // soft limb must blend to transparent (no opaque halo ring)
    // USER (2026-10-07): "get rid of the black haze around the sun at the
    // center". Root cause: this shader writes PREMULTIPLIED `vec4(base*a, a)`
    // (fragment.glsl.js:36) but the material left premultipliedAlpha at its
    // default false, so three.js blended with SRC_ALPHA and applied `a` a
    // SECOND time -> col*a*a + bg*(1-a), which dips BELOW the backdrop
    // wherever a is partial. Measured on docs/orb/idle-light.png (bg 235):
    // mean 195 with 91% of the r=24px ring under backdrop -> a dark annulus
    // hugging the sun. With the flag on it can only ever be bg + col*a.
    premultipliedAlpha: true,
  });
  core = new THREE.Mesh(new THREE.SphereGeometry(0.52, 48, 32), coreMat);
  const glowMat = new THREE.ShaderMaterial({
    vertexShader,
    fragmentShader: glowShader,
    uniforms: coreU,
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    // NB: deliberately left at the default (false) even though this shader also
    // writes premultiplied output. Fixing it brightened the corona SKIRT
    // (exp(-r*1.15) over a 2.6-unit plane), which pushed lit pixels past the
    // cage and grew the measured orb: orb:size went 183px -> 199px vs the 175px
    // target (13.8% drift > the 12% allowance) and scales_with_window failed.
    // The user did not ask for a brighter glow, and weakening the size gate is
    // not an option — so this one stays as-is and is recorded as a known gap.
  });
  const glow = new THREE.Mesh(new THREE.PlaneGeometry(2.6, 2.6), glowMat);
  glow.position.z = 0.58;    // just beyond the front pole (0.52): haze ALWAYS on top of the ball
  core.add(glow);            // inherits breath/pulse scaling with the ball
  // Motion-blur ghost trails: two extra glow copies trailing the sun during
  // glides (offsets handled per-frame; brightness = GLB-scaled so they are
  // invisible at rest).
  for (let gi = 1; gi <= 2; gi++) {
    const gm = glowMat.clone(); // deep-cloned uniforms (independent of coreU)
    const ghost = new THREE.Mesh(glow.geometry, gm);
    ghost.position.z = 0.58 + gi * 0.02;
    core.add(ghost);
    glowGhosts.push({ mesh: ghost, k: 0.85 + gi * 0.75, f: gi === 1 ? 0.5 : 0.32, z: 0.58 + gi * 0.02 });
  }
  group.add(core);

  const haloGeo = new THREE.RingGeometry(1.0, 1.15, 64);
  const haloMat = new THREE.MeshBasicMaterial({ color: 0xffda7a, side: THREE.DoubleSide, transparent: true, opacity: 0.25 });
  halo = new THREE.Mesh(haloGeo, haloMat);
  group.add(halo);
if (backingDiscAlpha > 0) {
  // Soft radial-gradient disc (user review: NOT a solid grey circle).
  const discGeo = new THREE.CircleGeometry(1.35, 48);
  const c = document.createElement('canvas');
  c.width = c.height = 128;
  const g = c.getContext('2d');
  const grad = g.createRadialGradient(64, 64, 0, 64, 64, 64);
  grad.addColorStop(0, 'rgba(0,0,0,1)');
  grad.addColorStop(0.5, 'rgba(0,0,0,0.7)');
  grad.addColorStop(1, 'rgba(0,0,0,0)');
  g.fillStyle = grad;
  g.fillRect(0, 0, 128, 128);
  const discTex = new THREE.CanvasTexture(c);
  const discMat = new THREE.MeshBasicMaterial({ map: discTex, transparent: true, opacity: backingDiscAlpha, depthWrite: false });
  const disc = new THREE.Mesh(discGeo, discMat);
  disc.position.z = -0.01;
  group.add(disc);
}

  for (let i = 0; i < 2; i++) {
    const geo = new THREE.RingGeometry(1.2 + i * 0.15, 1.25 + i * 0.15, 64, 1);
    const mat = new THREE.MeshBasicMaterial({ color: 0xffd700, side: THREE.DoubleSide, transparent: true, opacity: 0.5 });
    const m = new THREE.Mesh(geo, mat);
    group.add(m);
    rings.push(m);
  }

  const latGeo = new THREE.BufferGeometry();
  // built at the constant base shape so the lattice is correct from frame 0
  latGeo.setAttribute('position', new THREE.BufferAttribute(makeMorphTarget(BASE_SHAPE), 3));
  const latMat = new THREE.MeshBasicMaterial({ color: 0x58c4f2, wireframe: true, transparent: true, opacity: 0.35 });
  lattice = new THREE.Mesh(latGeo, latMat);
  group.add(lattice);

  const rayGeo = new THREE.RingGeometry(0.9, 1.3, 8, 1);
  const rayMat = new THREE.MeshBasicMaterial({ color: 0xffb32c, side: THREE.DoubleSide, transparent: true, opacity: 0.2 });
  rays = new THREE.Mesh(rayGeo, rayMat);
  rays.rotation.x = Math.PI / 4;
  group.add(rays);

  const starGeo = new THREE.BufferGeometry();
  const cnt = 80;
  const pos = new Float32Array(cnt * 3);
  for (let i = 0; i < cnt; i++) {
    pos[i * 3] = (Math.random() - 0.5) * 8;
    pos[i * 3 + 1] = (Math.random() - 0.5) * 8;
    pos[i * 3 + 2] = (Math.random() - 0.5) * 6;
  }
  starGeo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  // USER (2026-10-07): "just remove those blue particles you are using bruh
  // they are looking very weird." They were 80 raw PointsMaterial dots in
  // #58c4f2 (sky blue) scattered ±4 units across the frame — PointsMaterial with
  // no map draws SQUARE points, and the cyan specks read as dirt on the screen
  // rather than stars. Removed outright (his first, explicit choice over
  // "make them very small and blue"). The starfield was decorative only: no
  // state, gate or test references it (orb:size measures the lit-pixel RADIUS,
  // and these sat outside r97 anyway).
  //
  // `starGeo` is still built above and left in place deliberately — nothing
  // renders it now, and re-adding a star layer later is a two-line change.
  starsMesh = null;

  sage = initSageCore(THREE, group, scene, PAL); // Sage Core layers (spec §2.1)
  // Both the OUTER cage (L.poly) and the INNER cage (L.cage) share polyGeo, so
  // projecting it once makes them the same octagram by construction — and doing
  // it at BUILD time means the cage is correct from the first frame with no
  // boot morph (AMENDMENT item 2: "verify the renderer INIT path").
  initCageShape(sage, effectiveShape());
  AM = initAnswerMode(THREE, group, PAL);        // Answer Mode gold look (spec §2.2)
  DR = initDataRings(THREE, group);              // Data Rings thinking overlay (spec §2.3)
  JD = initJobDots(THREE, group, PAL);           // jobs_active dots (PROTOCOL §8)
  // User review fix: hide Phase-1 gold leftovers (halo/gold rings/orange ray
  // ring read as "a big flat golden 2D circle"). Sage Core supplies the glow
  // (core) + the white tilted orbit ring; later phases re-show what they need.
  halo.visible = false;
  rays.visible = false;
  for (const r of rings) r.visible = false;

  animate(0);
}

function startMorphTo(targetName) {
  const posAttr = lattice.geometry.getAttribute('position');
  const need = posAttr.count * 3;
  const raw = makeMorphTarget(targetName);
  // Safety net for Bug C: every target is built at BASE_VERTEX_COUNT now, but
  // a SHORTER target is what permanently wedged the lattice (the untouched tail
  // of the buffer was re-used as the next `from`). Cycle instead of leaving a
  // stale tail — the shape stays right even if a target is ever mis-sized.
  let to = raw;
  if (raw.length !== need) {
    console.error('[orb] MORPH TARGET LENGTH MISMATCH', targetName, raw.length, 'vs', need);
    to = new Float32Array(need);
    for (let i = 0; i < need; i++) to[i] = raw[i % raw.length];
  }
  const fromArr = new Float32Array(need);
  fromArr.set(posAttr.array);
  morphFrom = fromArr;
  morphTo = to;
  // Wave-4 reconnect-storm hardening: a RETARGET must not restart the ramp
  // clock, or states flipping faster than MORPH_DURATION (Bug E's flicker, or
  // any reconnect storm) leave progress pinned near 0 and the lattice parks at
  // its start shape. Keeping the clock makes progress a function of wall time,
  // so a storm still converges on the newest target. See morphclock.js.
  morphStart = nextMorphStart({ active: morphActive, morphStart, now: performance.now() });
  morphActive = true;
}

function updateMorph(now) {
  if (!morphActive || !morphFrom || !morphTo) return;
  const elapsed = now - morphStart;
  const t = morphProgress(elapsed, MORPH_DURATION);
  const et = easeInOutCubic(t);
  const posAttr = lattice.geometry.getAttribute('position');
  const arr = posAttr.array;
  const n = Math.min(morphFrom.length, morphTo.length);
  for (let i = 0; i < n; i++) {
    arr[i] = morphFrom[i] + (morphTo[i] - morphFrom[i]) * et;
  }
  posAttr.needsUpdate = true;
  if (t >= 1) {
    morphActive = false;
    morphFrom = null;
    morphTo = null;
  }
}

// Single owner of the lattice morph (Bug C-2). Idempotent via `lastMorphShape`,
// so the IPC path and the per-frame path can both call it safely, and a
// mid-ramp restart stays continuous because startMorphTo captures the CURRENT
// positions as its `from`.
let lastMorphShape = BASE_SHAPE;   // matches the initial geometry -> no boot morph
function snapLatticeTo(shape) {
  if (!lattice) return;
  const posAttr = lattice.geometry.getAttribute('position');
  const need = posAttr.count * 3;
  const to = makeMorphTarget(shape);
  for (let i = 0; i < need; i++) posAttr.array[i] = to[i % to.length];
  posAttr.needsUpdate = true;
  morphActive = false; morphFrom = null; morphTo = null;
}
function applyLatticeShape() {
  const want = effectiveShape();
  orbState.shapeHint = want;
  if (poseLock) { snapLatticeTo(want); lastMorphShape = want; return; }
  if (want === lastMorphShape) return;
  lastMorphShape = want;
  startMorphTo(want);
}

const demoSeq = [
  { t: 0, state: 'idle' },
  { t: 1000, state: 'listening' },
  { t: 2000, state: 'thinking' },
  { t: 3000, state: 'acting', shapeHint: 'octagram', taskKind: 'llm', jobsActive: 2 },
  { t: 4500, state: 'speaking', speak: { amplitude: 0.8, pitch_hz: 220 } },
  { t: 5500, state: 'speaking', speak: { amplitude: 0.4, pitch_hz: 180 } },
  { t: 6500, state: 'acting', shapeHint: 'square', taskKind: 'files', jobsActive: 1 },
  { t: 7500, state: 'confirm', jobsActive: 1 },
  { t: 8500, state: 'idle', jobsActive: 0, shapeHint: 'circle' },
  { t: 9500, state: 'reconnecting' },
  { t: 10500, state: 'offline' },
  { t: 11500, state: 'error' },
  { t: 12500, state: 'private_overlay' },
  { t: 13500, state: 'starting' },
  { t: 14500, state: 'idle' },
];

function runDemo(now) {
  for (let i = demoSeq.length - 1; i >= 0; i--) {
    if (now >= demoSeq[i].t) {
      const ev = demoSeq[i];
      if (ev.state !== orbState.orbState) {
        orbState.orbState = ev.state;
        updateSubtitle(`${ev.state}`);
      }
      if (ev.shapeHint) orbState.serverShapeHint = ev.shapeHint;
      // Route through the single owner so the shape-morph flag (user directive
      // 2026-10-07) governs this path too — runDemo must not be able to morph.
      applyLatticeShape();
      if (ev.taskKind) orbState.taskKind = ev.taskKind;
      if (ev.jobsActive !== undefined) orbState.jobsActive = ev.jobsActive;
      if (ev.speak) {
        speakAmp = ev.speak.amplitude || 0;
        speakPitch = ev.speak.pitch_hz || null;
        lastSpeakSeq = Math.max(lastSpeakSeq, 0);
      } else if (ev.state !== 'speaking') {
        speakAmp = 0;
        speakPitch = null;
      }
      break;
    }
  }
}

// MODE first (INTERFACES §e): private/paused are overlays on whatever base
// state is live, so a mode tint must never be reachable through `s` alone.
// Private deliberately keeps the BASE look (ORB_REBUILD §3.5 — only the teal
// ring says "cloud is off"); only paused/offline desaturate.
// Wave 5: `job_event.kind` (chat|analysis|simulation|act) drives a LOOK only —
// it is deliberately NOT an orb_state (PROTOCOL §5/§e). The lattice carries the
// state's signature shape, so it is also what carries the kind accent.
const KIND_TINT = {
  analysis: 0x7fd4ff,   // cool cyan — reading/reasoning
  simulation: 0x9d8cff, // violet — running a what-if
  act: 0xffb000,        // amber — doing something to the machine
  chat: 0x58c4f2,       // default cyan
};
const DEFAULT_LATTICE_TINT = 0x58c4f2;
const TERMINAL_JOB = ['done', 'failed', 'cancelled', 'interrupted'];
/**
 * Which `job_event.kind` should style the orb (null when none).
 *
 * The contract says `kind` exists for "Analysis/Simulation styling", so a live
 * `analysis`/`simulation` job wins over a `chat` root that happens to be first
 * in the list — otherwise a parallel-minds fan-out (root=chat, children
 * analysis+simulation) would style as plain chat and the accent would never
 * appear in exactly the case it was added for.
 */
function activeJobKind() {
  if (!orbJobs.length) return null;
  const live = orbJobs.filter((j) => !TERMINAL_JOB.includes(j.status));
  const pool = live.length ? live : orbJobs;
  const special = pool.find((j) => j.kind && j.kind !== 'chat' && j.kind !== 'act');
  const j = special || pool[0];
  return (j && j.kind) || null;
}

function getStateTint(s) {
  if (orbState.mode === 'paused') return 0x9fb6d8; // steel grey (spec §3)
  if (s === 'error') return 0xff3b3d;
  if (s === 'confirm') return 0xffb000;           // amber (spec §3)
  // per-state cage colour (user: "cages change shapes for different states
  // with color changes as well") — every state now owns a tint, not just the
  // error/confirm/offline family.
  if (s === 'listening') return 0xcfeeff;         // ice blue: receiving
  if (s === 'thinking') return 0x7fa8ff;          // saturated blue: reasoning
                                                 // (was 0xbfd4ff — only 25%
                                                 // saturation, so the cage
                                                 // read as plain white next to
                                                 // the pale-blue data rings)
  if (s === 'reconnecting') return 0x58c4f2;
  if (s === 'offline') return 0x9aa5b1;           // desaturated grey (spec §3)
  if (s === 'acting') return 0xffd700;
  if (s === 'speaking') return 0xffe9c0;          // gold-white core (spec §2.2)
  // USER (2026-10-07): "the starting state should be white not pink/purple".
  // Was 0xfff4d6 (warm cream) — with the nebula haze on top that read lavender.
  // Pure white; the existing bright 0.72 -> idle 1.00 ramp gives the requested
  // "dim white -> full glow white" hand-off unchanged.
  if (s === 'starting') return 0xffffff;
  return palInt(PAL.core_tint);                   // idle / private_overlay (theme token)
}

/**
 * §2 motion blur — VELOCITY GATED. Returns the uniforms for the one low-res
 * angular smear, or `on:false` when the orb is calm (in which case the pass is
 * not executed at all and idle costs exactly what it did before).
 *
 * Gates, in order: `orb.motion_blur: off` -> `reduced_motion` -> quality tier
 * `low` -> the frame-time governor (if it has already downshifted, cut the
 * tap budget) -> the velocity threshold itself.
 */
function computeMotionBlur(dt) {
  const want = cfg.motionBlur || 'auto';
  blurState.speed = spin ? spin.omega : 0;
  const off = (reason) => {
    Object.assign(blurState, { amount: 0, angle: 0, taps: 0, skipped: true, reason });
    return { on: false, angle: 0, taps: 0, amount: 0 };
  };
  if (motionBlurOverride === 'off') return off('override-off');
  if (cfg.reducedMotion) return off('reduced_motion');
  if (want === 'off') return off('motion_blur-off');

  // speed: the physical assembly spin, plus whichever overlay layer is turning
  // fastest right now (Answer-Mode glyph bands / prismatic data rings)
  let speed = spin ? spin.omega : 0;
  if (AM && Math.max(AM.wFull, AM.wQuiet) > 0.15) speed = Math.max(speed, 0.55);
  if (DR && DR.w > 0.15) speed = Math.max(speed, 0.45);
  const raw = motionBlurOverride === 'force'
    ? 1
    : Math.max(0, Math.min(1, (speed - BLUR_CALM) / (BLUR_FAST - BLUR_CALM)));
  if (raw <= 0.02) return off('calm');          // idle rest spin -> no cost

  let taps;
  if (want === 'low') taps = 2;
  else if (want === 'high') taps = 6;
  else if (cfg.quality === 'low') taps = 0;
  else if (cfg.quality === 'medium') taps = 3;
  else if (cfg.quality === 'high') taps = 6;
  else taps = 4;                                 // auto
  if (GOV.on && GOV.idx < GOV.ceiling) taps = Math.min(taps, 2); // governor wins
  if (taps <= 0) return off('quality-tier');

  const angle = Math.min(BLUR_MAX_ANGLE, speed * (Math.min(dt, 50) / 1000));
  const amount = 0.9 * raw;
  Object.assign(blurState, { amount, angle, taps, skipped: false, reason: 'on', speed });
  return { on: true, angle, taps, amount };
}

function animate(now) {
  requestAnimationFrame(animate);
  noteState(now); // AMENDMENT 2: record the rendered state sequence (boot -> idle -> ...)
  updateConfirmCard(); // WAVE 5U: card visible only in `confirm`, and only while live
  if (DEMO && !manualState && window.__orbDemoTimeline === true) {
    // Auto-timeline is OPT-IN now (default off): the natural boot story owns
    // the opening — starting plays the generation sequence, eases into idle.
    // Scripts can enable the old showcase via window.__orbDemoTimeline = true.
    runDemo(now);
  }
  const t = poseLock ? POSE_T : clock.getElapsedTime();
  const pitchNorm = speakPitch ? Math.max(0.8, Math.min(1.2, speakPitch / 220)) : 1;
  const breathBase = 2 * pitchNorm;
  const breath = 1 + 0.08 * Math.sin(t * breathBase);
  // Amplitude source per state (ORB_REBUILD §6): mic RMS for `listening`
  // (forwards on orb_state by brain-core), TTS chunks for `speaking`.
  const reactiveAmp = orbState.orbState === 'listening'
    ? (typeof orbState.amplitude === 'number' ? orbState.amplitude : 0)
    : speakAmp;
  const pulse = 1 + reactiveAmp * 0.25;
  // dt (§1): time since the PREVIOUS animation tick, clamped to 50 ms so a
  // hitch or a throttled tab cannot distort the curve. It used to be
  // `now - lastFrame` (time since the last RENDER), which double-counted
  // between renders on the 30 fps idle cap and made every 300-600 ms blend
  // run ~1.5x fast. Pose-locked captures use a deliberately large dt so all
  // damped uniforms converge to their targets within a couple of frames.
  const dtRaw = now - lastNow;
  lastNow = now;
  const dt = poseLock ? 1000 : Math.max(1, Math.min(dtRaw, 50));
  // frame-time probe (§2/§4 evidence): rolling EMA of real tick intervals
  if (ft.last > 0) {
    const d = now - ft.last;
    if (d > 0 && d < 500) ft.ema = ft.ema ? ft.ema + 0.1 * (d - ft.ema) : d;
    if (ft.n < 1e9) ft.n++;
  }
  ft.last = now;
  if (!poseLock) stepSpin(now, dt);
  // Damping weights based on current orb state
  // state-shape morph: each state morphs the cyan lattice to its signature shape
  if (orbState.orbState !== lastShapeState) {
    lastShapeState = orbState.orbState;
    // echo the visual state to main (roam gating + future features)
    try { if (window.raphael && window.raphael.sendOrbState) window.raphael.sendOrbState(orbState.orbState); } catch (e) { /* no preload */ }
    // PROTOCOL §8 + Bug C(2): one owner for the lattice morph. The old code
    // only morphed when `want !== orbState.shapeHint`, but onOrbState had
    // ALREADY assigned shapeHint — so a state change never morphed at all and
    // the lattice kept its previous shape. The pose lock then snapped it for
    // every screenshot, which is exactly why the pixel gates never saw this.
    applyLatticeShape();
    // TTS amplitude belongs to `speaking` only: a missed speak{end} must not
    // keep pulsing every later state (W2.1 frame-trace finding).
    if (orbState.orbState !== 'speaking' && window.orbDemoAmp === undefined) {
      speakAmp = 0;
      speakPitch = null;
    }
    // §1: a NEW startup sequence relaxes omega up to the peak and then lets it
    // decay with orb.startup.spin_tau_ms. omega itself is never snapped, and
    // every other state change leaves it alone (C1 continuity).
    if (orbState.orbState === 'starting' && !poseLock) armStartup(now);
  }
  const target = modeTarget(orbState.orbState, orbState.mode);
  layerWeights.coreScale = damp(layerWeights.coreScale, target.coreScale, MORPH_DURATION, dt);
  layerWeights.haloOpacity = damp(layerWeights.haloOpacity, target.haloOpacity, MORPH_DURATION, dt);
  layerWeights.latticeOpacity = damp(layerWeights.latticeOpacity, target.latticeOpacity, MORPH_DURATION, dt);
  const ballScale = breath * pulse * layerWeights.coreScale;
  // glide inertia: fast attack / slow release toward main's velocity feed
  const gFast = (Math.abs(glideTX) > Math.abs(GLX) || Math.abs(glideTY) > Math.abs(GLY)) ? 90 : 420;
  GLX = damp(GLX, glideTX, gFast, dt);
  GLY = damp(GLY, glideTY, gFast, dt);
  GLB = damp(GLB, glideTB, gFast, dt);
  core.scale.setScalar(ballScale * (1 + GLB * 0.7));  // blur bump v2: bloom swells hard while gliding
  core.position.set(-GLX * 0.85, -GLY * 0.85, 0);     // the sun LEADS; everything else trails
  // ghost trail copies: trailing glow smears (the "motion blur" layer)
  for (let i = 0; i < glowGhosts.length; i++) {
    const gh = glowGhosts[i];
    gh.mesh.position.set(-(gh.k - 0.85) * GLX, -(gh.k - 0.85) * GLY, gh.z);
    gh.mesh.material.uniforms.uBright.value = core.material.uniforms.uBright.value * GLB * gh.f;
    gh.mesh.material.uniforms.uAmp.value = core.material.uniforms.uAmp.value;
    gh.mesh.material.uniforms.color.value.copy(core.material.uniforms.color.value);
  }
  halo.scale.setScalar(breath * (1 + reactiveAmp * 0.15));
  halo.material.opacity = 0.25 * layerWeights.haloOpacity;
  lattice.material.opacity = 0.35 * layerWeights.latticeOpacity;
  // Kind accent on the signature shape (Analysis / Simulation / act) — OFF by
  // the same user directive as the shape morphs (KIND_ACCENTS_ENABLED). Kept
  // behind the flag, not deleted, and not evaluated per frame while disabled
  // (ORB_REBUILD §5: no per-frame allocation). Kind is still TRACKED and
  // reported by __orbTrace().jobKind for observability.
  if (KIND_ACCENTS_ENABLED) {
    const k = activeJobKind();
    lattice.material.color.setHex((k && KIND_TINT[k]) || DEFAULT_LATTICE_TINT);
  }
  const mode = orbState.mode;
  updateSageCore(sage, { t, dt, state: orbState.orbState, mode, lock: poseLock, shape: effectiveShape(), amp: reactiveAmp, coreU: core.material.uniforms, ballScale, core, tint: getStateTint(orbState.orbState), glide: { x: GLX, y: GLY, blur: GLB } });
  if (AM) updateAnswerMode(AM, { t, dt, state: orbState.orbState, mode, lock: poseLock, amp: reactiveAmp, glide: { x: GLX, y: GLY } });
  if (DR) updateDataRings(DR, { t, dt, state: orbState.orbState, mode, lock: poseLock, amp: reactiveAmp, glide: { x: GLX, y: GLY } });
  if (JD) updateJobDots(JD, { t, dt, jobs: orbState.jobsActive, jobList: orbJobs, lock: poseLock });
  if (AM && maskMat) maskMat.uniforms.uCA.value = AM.wFull; // chromatic aberration at outer edge (Answer Mode)
  if (!poseLock) {
    // dt-based, never per-tick (§1): the old fixed `+= 0.01` style scaled with
    // the frame RATE, so a hitch or a throttled tab visibly changed speed.
    const dtSec = dt / 1000;
    rays.rotation.z += 0.60 * dtSec;
    rings[0].rotation.z += 0.48 * dtSec;
    rings[1].rotation.z -= 0.36 * dtSec;
    lattice.rotation.y += 0.24 * dtSec;
    // the whole assembly's rotation IS the integrated omega — angle is never
    // reset or eased, only omega relaxes (see stepSpin)
    group.rotation.y = (spin ? spin.angle : 0) * GROUP_SPIN;
  }
  group.rotation.x = Math.sin(t * 0.045) * 0.05; // gentle bounded sway on x (not one flat plane)

  const stateTint = getStateTint(orbState.orbState);
  core.material.uniforms.color.value.setHex(stateTint); // ShaderMaterial: color lives in uniforms, not .color

  // Apply demo controls if present
  if (window.orbDemoSize && sizePx !== window.orbDemoSize) {
    sizePx = window.orbDemoSize;
    renderer.setSize(sizePx, sizePx);
    if (typeof resizeEdgeRT === 'function') resizeEdgeRT(sizePx, sizePx);
  }
  if (window.orbDemoAmp !== undefined) {
    speakAmp = parseFloat(window.orbDemoAmp);
  }

  // Adjust frame interval based on state (active vs idle)
  const activeStates = ['listening','thinking','acting','speaking','error','private_overlay','reconnecting','offline','starting','confirm'];
  const isActive = activeStates.includes(orbState.orbState);
  const targetFps = isActive ? fpsCap : Math.max(30, Math.round(fpsCap/2)); // spec §5: 60 active / 30 idle — NOT forced (user)
  frameInterval = 1000 / targetFps;
  // Pause rendering when window is hidden
  if (document.hidden) return;
  // Wave-4: a lost context must not be hammered with draw calls
  if (glRecovery.isLost()) return;
  if (now - lastFrame < frameInterval) return;
  lastFrame = now;
  if (!poseLock) updateMorph(now);
  // Render scene -> offscreen target, then composite through the edge mask
  // (soft 8% fade on every side: no content ever meets the window box hard).
  const blur = computeMotionBlur(dt);   // §2 — evaluated before the pass runs
  if (edgeRT) {
    renderer.setRenderTarget(edgeRT);
    renderer.render(scene, camera);
    sceneStats.calls = renderer.info.render.calls;
    sceneStats.tris = renderer.info.render.triangles;
    // §2: ONE extra LOW-RES pass (edgeRT -> blurRT), and only while moving.
    // It never runs in the calm case, so idle cost is unchanged.
    if (blur.on) {
      blurMat.uniforms.uAngle.value = blur.angle;
      blurMat.uniforms.uTaps.value = blur.taps;
      renderer.setRenderTarget(blurRT);
      renderer.render(blurScene, blurCam);
    }
    renderer.setRenderTarget(null);
    maskMat.uniforms.uBlur.value = blur.on ? blur.amount : 0;
    renderer.render(maskScene, maskCam);
  } else {
    renderer.render(scene, camera);
    sceneStats.calls = renderer.info.render.calls;
    sceneStats.tris = renderer.info.render.triangles;
  }

  // --- frame-time governor: measure achieved intervals, drift the tier ---
  // §1: it must NOT change quality while the startup spin is still running —
  // a mid-startup dpr shift is exactly the "animation visibly hitches" cause.
  if (GOV.on && !document.hidden && !spinSettling()) {
    const d = GOV.lastAt ? (now - GOV.lastAt) : 0;
    GOV.lastAt = now;
    GOV.seen++;
    if (GOV.seen > 180 && d > 0 && d < 500) { // skip shader-compile warmup + hitches
      GOV.ema = GOV.ema ? GOV.ema + 0.08 * (d - GOV.ema) : d;
      if (GOV.ema > frameInterval * 1.6) { GOV.slow++; GOV.fast = 0; }
      else if (GOV.ema < frameInterval * 1.15) { GOV.fast++; GOV.slow = Math.max(0, GOV.slow - 1); }
      else { GOV.slow = Math.max(0, GOV.slow - 1); GOV.fast = Math.max(0, GOV.fast - 1); }
      const t = performance.now();
      if (GOV.slow >= 90 && t >= GOV.nextAt && GOV.idx > 0) {
        GOV.idx--; if (govApply) govApply(); GOV.acted++;
        GOV.nextAt = t + 4000; GOV.slow = 0;
        console.log('[gov] downshift dpr=' + GOV_LADDER[GOV.idx] + ' ema=' + GOV.ema.toFixed(1));
      } else if (GOV.fast >= 360 && t >= GOV.nextAt && GOV.idx < GOV.ceiling) {
        GOV.idx++; if (govApply) govApply(); GOV.acted++;
        GOV.nextAt = t + 8000; GOV.fast = 0;
        console.log('[gov] upshift dpr=' + GOV_LADDER[GOV.idx] + ' ema=' + GOV.ema.toFixed(1));
      }
    }
  } else { GOV.lastAt = now; GOV.seen = 0; GOV.ema = 0; GOV.slow = 0; GOV.fast = 0; }

  // FPS counter
  frameCount++;
  const nowFps = performance.now();
  if (nowFps - lastFpsUpdate >= 1000) {
    const fps = Math.round((frameCount * 1000) / (nowFps - lastFpsUpdate));
    if (fpsEl) fpsEl.textContent = `FPS: ${fps}`;
    frameCount = 0;
    lastFpsUpdate = nowFps;
  }
}

const NOTICE_TINT = {
  answer: 'rgba(255, 208, 122, 0.99)',   // warm gold — the reply that landed
  report: 'rgba(167, 139, 250, 0.99)',   // violet — a long-form artifact
  info: 'rgba(214, 240, 255, 0.98)',
  warn: 'rgba(255, 214, 102, 0.99)',
  error: 'rgba(255, 122, 112, 0.99)',
};
/** PROTOCOL §3 `notice` — a Brain->ui banner. It deliberately bypasses the
 *  Private-Mode subtitle suppression (notices are local system messages, not
 *  cloud content) and, per the contract, NEVER changes the orb state. */
function updateNotice(n) {
  if (!subtitleEl || !n || !n.text) return;
  updateSubtitle(String(n.text).slice(0, 240), {
    force: true,
    color: NOTICE_TINT[n.level] || NOTICE_TINT.info,
    duration: 4000,
  });
}

/** PROTOCOL §3 `answer` — the final reply: provenance + head of the text (the
 *  full reply is what she speaks; this confirms it landed and from where).
 *  Never an orb_state. */
function updateAnswer(a) {
  if (!a || !a.text) return;
  const prov = a.provider ? ` · ${a.provider}${a.model ? '/' + a.model : ''}` : '';
  const head = String(a.text).slice(0, 60);
  updateSubtitle(`Answer · ${head}${a.text.length > 60 ? '…' : ''}${prov}`,
    { force: true, color: NOTICE_TINT.answer, duration: 6000, banner: true });
}

/** PROTOCOL §3 `report` — long-form artifact: title + summary, wrapped. */
function updateReport(r) {
  if (!r || (!r.title && !r.summary)) return;
  const title = String(r.title || 'Report').slice(0, 70);
  const sum = r.summary ? String(r.summary).slice(0, 220) : '';
  updateSubtitle(sum ? `${title} — ${sum}` : title,
    { force: true, color: NOTICE_TINT.report, duration: 9000, banner: true });
}

function updateSubtitle(text, opts) {
  if (!subtitleEl) return; // demo page has no subtitle element
  // AMENDMENT 3: speech only. Never paint, and scrub anything already showing
  // so a frame that raced in ahead of the flag cannot leave words on screen.
  if (!ORB_TEXT_ENABLED) {
    if (subtitleTimer) { clearTimeout(subtitleTimer); subtitleTimer = null; }
    subtitleEl.classList.remove('show', 'banner');
    subtitleEl.classList.add('hide');
    subtitleEl.textContent = '';
    return;
  }
  const isPrivate = orbState.private || orbState.mode === 'private' || orbState.orbState === 'private_overlay';
  const force = !!(opts && opts.force);
  if (!text || (isPrivate && !force)) {
    subtitleEl.classList.remove('show');
    subtitleEl.classList.add('hide');
    return;
  }
  subtitleEl.style.color = (opts && opts.color) || 'rgba(255, 255, 255, 0.95)';
  subtitleEl.classList.toggle('banner', !!(opts && opts.banner));
  subtitleEl.textContent = text;
  subtitleEl.classList.remove('hide');
  subtitleEl.classList.add('show');
  if (subtitleTimer) clearTimeout(subtitleTimer);
  const duration = (opts && opts.duration) || 1200;
  subtitleTimer = setTimeout(() => {
    subtitleEl.classList.remove('show');
    subtitleEl.classList.add('hide');
  }, duration);
}

// --- Demo harness wiring (these elements exist only on demo.html) ---
let manualState = false; // first manual selection disables the auto timeline
const demoStateSel = document.getElementById('stateSelect');
if (demoStateSel) {
  for (const key of Object.keys(STATE_LAYER_TARGETS)) {
    const opt = document.createElement('option');
    opt.value = key;
    opt.textContent = key;
    demoStateSel.appendChild(opt);
  }
  demoStateSel.addEventListener('change', () => {
    manualState = true; // USER owns the state now — runDemo must stop overriding it
    orbState.orbState = demoStateSel.value;
    updateSubtitle(demoStateSel.value);
  });
}
window.__orbDebug = { get state() { return orbState.orbState; } }; // LIVE render state (not the dropdown)

// ---------------------------------------------------------------------------
// POSE LOCK (test hook, W2.1 / quality gates).
// The orb rotates continuously — a full polyhedron turn takes ~40 s — so two
// screenshots of the SAME state taken seconds apart differ by 5-8/255 purely
// from rotation. That self-noise is larger than several genuine state
// differences, which made the pixel-diff gate unable to tell "paused renders
// exactly like idle" from "paused adds a thin steel ring".
//
// Locking puts every layer back on a canonical pose, snaps every weight to its
// target and pins the animation clock, so a captured frame becomes a pure
// function of (state, mode, jobs, amplitude). The CDP harness locks before
// shooting and unlocks right after; production never calls it.
// ---------------------------------------------------------------------------
window.__orbLockPose = () => {
  const st = orbState.orbState;
  const mode = orbState.mode;
  poseLock = true;
  lastShapeState = st;
  const target = modeTarget(st, mode);
  layerWeights = { ...target };
  applyLatticeShape();   // snaps while poseLock is on (set above)
  // clear every accumulated transform so all scenes share one pose
  rays.rotation.set(Math.PI / 4, 0, 0);
  rings[0].rotation.set(0, 0, 0);
  rings[1].rotation.set(0, 0, 0);
  lattice.rotation.set(0, 0, 0);
  group.rotation.set(0, 0, 0);
  const la = st === 'listening'
    ? (typeof orbState.amplitude === 'number' ? orbState.amplitude : 0)
    : (st === 'speaking' ? speakAmp : 0);
  if (sage) lockSageCore(sage, st, mode, { tint: getStateTint(st), amp: la, shape: effectiveShape() });
  if (AM) lockAnswerMode(AM, st, { amp: la });
  if (DR) lockDataRings(DR, st, { amp: la });
  if (JD) lockJobDots(JD, orbState.jobsActive, orbJobs);
  return window.__orbTrace ? window.__orbTrace().applied : null;
};
window.__orbUnlockPose = () => { poseLock = false; };
window.__orbPoseLocked = () => poseLock;

// ---------------------------------------------------------------------------
// SPIN PROBE (§1). Reads the live rotation state without touching it, so the
// harness can plot omega/angle through `starting -> idle` BEFORE and AFTER the
// physical-rotation rewrite and assert on the real numbers.
//   omega      — the physical angular velocity once the rewrite is in, else null
//                (the harness then finite-differences `angles.cage`)
//   angles.*   — raw accumulated rotation of each assembly, radians
//   genT       — the wireframe build clock (ms) used by the startup sequence
// ---------------------------------------------------------------------------
window.__orbSpin = () => ({
  t: Math.round(performance.now()),
  angle: group ? group.rotation.y : null,   // primary rotation (integrates omega)
  omega: spin ? spin.omega : null,
  rest: spin ? spin.rest : null,
  peak: spin ? spin.peak : null,
  tau: spin ? spin.tau : null,
  phase: spin ? spin.phase : null,
  state: orbState.orbState,
  genT: sage ? sage.genT : null,
  bright: core ? core.material.uniforms.uBright.value : null,
  coreScale: core ? core.scale.x : null,
  angles: {
    group: group ? group.rotation.y : null,
    cage: sage && sage.cage ? sage.cage.rotation.y : null,
    poly: sage ? sage.poly.rotation.y : null,
    lattice: lattice ? lattice.rotation.y : null,
    rays: rays ? rays.rotation.z : null,
  },
  weights: {
    lattice: layerWeights.latticeOpacity,
    halo: layerWeights.haloOpacity,
    coreScale: layerWeights.coreScale,
  },
  govActed: GOV ? GOV.acted : 0,
  govDpr: GOV ? GOV_LADDER[GOV.idx] : null,
  frame: renderer ? renderer.info.render.frame : null,
});

// --- Bug C probes ----------------------------------------------------------
// MORPH TARGET INVARIANT: every lattice target must share one vertex count.
// Checked once at load so a regression is loud in the console, and reported by
// __orbMorphDiff so the CDP gate can assert it.
const MORPH_TARGET_LENGTHS = MORPH_SHAPES.map((s) => makeMorphTarget(s).length);
if (new Set(MORPH_TARGET_LENGTHS).size !== 1) {
  console.error('[orb] MORPH TARGET LENGTH MISMATCH', MORPH_SHAPES, MORPH_TARGET_LENGTHS);
}

/**
 * Is the lattice exactly where `shape` says it should be? A non-zero maxErr
 * after a settle means a morph was interrupted and left a stale tail (Bug C).
 * `cage` is the per-state 3D cage deformation, checked the same way.
 */
window.__orbMorphDiff = () => {
  if (!lattice) return null;
  const shape = effectiveShape();
  const have = lattice.geometry.getAttribute('position').array;
  const want = makeMorphTarget(shape);
  let lat = null;
  if (want.length !== have.length) {
    lat = { lengthMismatch: true, want: want.length, have: have.length };
  } else {
    let m = 0;
    for (let i = 0; i < want.length; i++) m = Math.max(m, Math.abs(want[i] - have[i]));
    lat = { lengthMismatch: false, maxErr: m, points: have.length / 3 };
  }
  let cage = null;
  if (sage && sage.polyBase && sage.cageTo) {
    projectShape(sage.polyBase, shape, sage.cageTo);
    const arr = sage.polyGeo.attributes.position.array;
    let m = 0;
    for (let i = 0; i < arr.length; i++) m = Math.max(m, Math.abs(arr[i] - sage.cageTo[i]));
    // SPHERICITY proof: every cage vertex must sit on ONE sphere, so the radius
    // spread has to be ~0. A star/prism/icosphere fails this instantly.
    let rMin = Infinity, rMax = 0;
    for (let i = 0; i < arr.length; i += 3) {
      const r = Math.hypot(arr[i], arr[i + 1], arr[i + 2]);
      if (r < rMin) rMin = r;
      if (r > rMax) rMax = r;
    }
    cage = { maxErr: m, active: !!sage.cageActive, shape: sage.cageShape,
             radiusMin: rMin, radiusMax: rMax,
             radiusSpread: rMax - rMin };
  }
  return { shape, shapeHintField: orbState.shapeHint, morphActive,
           targetLengths: MORPH_TARGET_LENGTHS, lattice: lat, cage };
};

// --- §2 / §4 probes ---------------------------------------------------------
window.__orbMotionBlur = () => ({ ...blurState, reducedMotion: !!cfg.reducedMotion,
                                  quality: cfg.quality, config: cfg.motionBlur });
// 'off' forces the pass out (baseline measurement), 'force' ignores the
// velocity gate so the COST of the pass can be measured in a calm state,
// null restores normal gating. Test-only; production never calls it.
window.__orbSetMotionBlur = (m) => { motionBlurOverride = m || null; return window.__orbMotionBlur(); };
window.__orbFrameTime = () => ({ ema: ft.ema, n: ft.n });
window.__orbResetFrameTime = () => { ft.ema = 0; ft.n = 0; return true; };

// --- §4 transparency probe --------------------------------------------------
// `Page.captureScreenshot` returns an EMPTY image for a transparent page in
// this environment (WSLg/ANGLE), so a screenshot-based edge check would pass
// vacuously. Instead read the actual drawing buffer: re-composite the last
// scene target through the edge mask, then gl.readPixels. The canvas alpha is
// the orb's real premultiplied alpha — independent of the page backdrop.
window.__orbEdgeStats = () => {
  if (!renderer || !edgeRT || !maskScene) return null;
  renderer.setRenderTarget(null);
  renderer.render(maskScene, maskCam);   // fresh frame in the drawing buffer
  const gl = renderer.getContext();
  const w = gl.drawingBufferWidth, h = gl.drawingBufferHeight;
  const px = new Uint8Array(w * h * 4);
  gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, px);
  const B = 2;
  let maxBorderAlpha = 0, maxBorderRgb = 0, maxAlpha = 0, lit = 0;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const i = (y * w + x) * 4;
      const a = px[i + 3];
      const rgb = Math.max(px[i], px[i + 1], px[i + 2]);
      if (a > maxAlpha) maxAlpha = a;
      if (a > 8) lit++;
      if (x < B || x >= w - B || y < B || y >= h - B) {
        if (a > maxBorderAlpha) maxBorderAlpha = a;
        if (rgb > maxBorderRgb) maxBorderRgb = rgb;
      }
    }
  }
  return { w, h, maxBorderAlpha, maxBorderRgb, maxAlpha, litPixels: lit,
           blurOn: !!(maskMat && maskMat.uniforms.uBlur.value > 0.001) };
};


// W2.1 trace probe: what the renderer RECEIVED + what it APPLIED (weights and
// the actual uniforms driving the GL) in one snapshot, so a screenshot can be
// correlated with the exact numbers behind it.
window.__orbTrace = () => ({
  t: Math.round(performance.now()),
  applied: {
    state: orbState.orbState, mode: orbState.mode,
    private: !!orbState.private, paused: !!orbState.paused,
    jobsActive: orbState.jobsActive, shapeHint: orbState.shapeHint,
    taskKind: orbState.taskKind, provider: orbState.provider || null,
    model: orbState.model || null,
    tint: '0x' + getStateTint(orbState.orbState).toString(16),
  },
  weights: {
    layer: { ...layerWeights },
    sage: sage ? Object.assign({}, sage.w) : null,
    sagePrivateRing: sage ? sage.privateW : null,
    answer: AM ? { full: AM.wFull, quiet: AM.wQuiet, ampS: AM.ampS } : null,
    dataRings: DR ? { w: DR.w } : null,
    latticeOpacity: lattice ? lattice.material.opacity : null,
    haloOpacity: halo ? halo.material.opacity : null,
  },
  uniforms: core ? {
    uBright: core.material.uniforms.uBright.value,
    uAmp: core.material.uniforms.uAmp.value,
    uColor: core.material.uniforms.color.value.getHexString(),
    coreScale: core.scale.x,
    polyAlpha: sage ? sage.polyMat.uniforms.uAlpha.value : null,
    nodeAlpha: sage ? sage.nodeMat.uniforms.uAlpha.value : null,
    nebulaOpacity: sage ? sage.nebulaMat.uniforms.uOpacity.value : null,
    speedAlpha: sage ? sage.speedMat.uniforms.uAlpha.value : null,
    ringAlpha: sage ? sage.ringFrontMat.uniforms.uAlpha.value : null,
    drop: sage ? sage.polyMat.uniforms.uDrop.value : null,
  } : null,
  amp: { speak: speakAmp, pitch: speakPitch, mic: orbState.amplitude },
  jobs: orbJobs,                 // {job, status, kind, parent} — parallel-minds styling
  jobKind: activeJobKind(),
  jobFan: JD ? !!JD.fan : false,
  jobGroups: JD ? JD.groups : 0,
  jobSpokes: JD ? (JD.spokes.geometry.drawRange.count || 0) : 0,
  theme: { requested: cfg.theme, personaTier: cfg.personaTier,
           glyph: PAL.glyph_color, haze: PAL.haze_lime, privateRing: PAL.private_ring },
  poseLocked: poseLock,
  rx: TRACE_RX.slice(-50),
  stats: window.__orbStats ? window.__orbStats() : null,
});
// AMENDMENT 2: the RENDERED state sequence from module load — starting -> idle
// -> <event>, whichever path changed it (IPC, boot timer, demo). Asserted
// end-to-end by test/orb-trace.cjs over CDP.
window.__orbStateHistory = () => STATE_HISTORY.slice();
window.__orbStats = () => { // Phase-7 perf probe: true RENDERED frames + scene draw budget
  const r = renderer;
  if (!r) return { frame: -1 };
  const i = r.info.render;
  // NOTE: frame increments per render() call and we render TWICE per animation
  // frame (scene->RT, mask->canvas): real FPS = delta(frame) / (2 * seconds).
  return { frame: i.frame, calls: sceneStats.calls, tris: sceneStats.tris,
           dpr: r.getPixelRatio(), w: canvas.width, h: canvas.height, gl: glName(),
           gov: { on: GOV.on, dpr: GOV_LADDER[GOV.idx],
                  ceiling: GOV_LADDER[GOV.ceiling], ema: Math.round(GOV.ema),
                  acted: GOV.acted, slow: GOV.slow, fast: GOV.fast } };
};
function glName() {
  try {
    const gl = renderer.getContext();
    const dbg = gl.getExtension('WEBGL_debug_renderer_info');
    return String(dbg ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER) || '');
  } catch (e) { return 'unknown'; }
}
const demoSizeSlider = document.getElementById('sizeSlider');
if (demoSizeSlider) demoSizeSlider.addEventListener('input', (e) => { window.orbDemoSize = parseInt(e.target.value, 10); });
const demoAmpSlider = document.getElementById('ampSlider');
if (demoAmpSlider) demoAmpSlider.addEventListener('input', (e) => { window.orbDemoAmp = parseFloat(e.target.value); });

// Velocity feed from main during roam glides: unit dir + bell-scaled px lag
if (window.raphael && window.raphael.onGlide) {
  window.raphael.onGlide((g) => {
    if (g && g.on) {
      const wpp = 3.32 / Math.max(cfg.sizePx || 280, 100); // world units per screen px (view half-height 1.66)
      glideTX = (g.vx || 0) * (g.px || 0) * wpp;
      glideTY = (g.vy || 0) * (g.px || 0) * wpp;
      glideTB = Math.min(1, (g.px || 0) / 24);
    } else {
      glideTX = 0; glideTY = 0; glideTB = 0;
    }
  });
}

window.addEventListener('load', initScene);

// NATURAL BOOT STORY (user request): the orb starts in 'starting', plays the
// full staged generation (outer cage -> inner cage -> sun grows -> finishing
// spin, sagecore genT), then eases into idle BY ITSELF — no external state
// changes. S.starting === S.idle values, so the hand-off is pop-free.
setTimeout(() => {
  if (orbState.orbState === 'starting') {
    orbState.orbState = 'idle'; // boot 'idle' text flash removed (user request)
  }
}, 5400); // after the finishing spin window (ends at genT 4600ms)

if (window.raphael) {
  window.raphael.onOrbState((s) => {
    traceRx('orb_state', s);
    // PROTOCOL §8: `shape_hint` on the frame is authoritative; null means the
    // frame carried none and the per-state default applies instead. NB the merge
    // below also overwrites `shapeHint` with the SERVER's value (usually
    // 'circle'), which is why the effective shape is recomputed right after.
    if ('shapeHint' in s) orbState.serverShapeHint = s.shapeHint || null;
    orbState = { ...orbState, ...s };
    orbState.serverShapeHint = ('shapeHint' in s) ? (s.shapeHint || null) : orbState.serverShapeHint;
    applyLatticeShape();
    // state-name text REMOVED (user: "text flashes when switching states") —
    // only explicit subtitles (spoken narration) are ever shown.
    if (s.subtitle) updateSubtitle(s.subtitle);
  });
  window.raphael.onPalette((p) => {
    // Wave 5: a persona.tier switch re-skins without restarting the orb.
    traceRx('palette', { theme: p && p.theme, tier: p && p.personaTier });
    PAL = resolvePalette(p);
    applyPalette();
  });
  window.raphael.onAnswer((a) => { traceRx('answer', a); updateAnswer(a); });
  window.raphael.onReport((r) => { traceRx('report', r); updateReport(r); });
  window.raphael.onJobs((j) => { orbJobs = Array.isArray(j) ? j : []; traceRx('jobs', { n: orbJobs.length }); });
  window.raphael.onConfirm((c) => {
    traceRx('confirm', c);
    cc.pending = c || null;
    if (c) renderConfirmCard(c);
    updateConfirmCard();
  });
  window.raphael.onNotice((n) => {
    traceRx('notice', n);          // recorded, but orbState is never touched
    updateNotice(n);
  });
  window.raphael.onSubtitle((t) => {
    traceRx('subtitle', t);
    if (t && t.text) updateSubtitle(t.text);
  });
  window.raphael.onSpeak((ev) => {
    traceRx('speak', ev);
    if (!ev) return;
    // BUGS-WAVE2 Bug C (no pulse while she spoke): the old guard was
    //   if (ev.seq <= lastSpeakSeq) return;
    // and `lastSpeakSeq` survived across utterances, so a FRESH utterance that
    // restarts seq at 0 was dropped wholesale (0 <= 8, 1 <= 8, ...) — the orb
    // stopped pulsing after the first answer.
    //
    // The transport is an ORDERED WebSocket (PROTOCOL §1), so an out-of-order
    // or replayed speak frame cannot exist; the guard therefore only ever
    // dropped legitimate frames. Processing is idempotent (we just assign the
    // amplitude), so nothing is dropped any more — `lastSpeakSeq` is kept as a
    // high-water mark for diagnostics only.
    if (ev.seq !== undefined && ev.seq > lastSpeakSeq) lastSpeakSeq = ev.seq;
    if (ev.event === 'end') {
      speakAmp = 0;
      speakPitch = null;
      lastSpeakSeq = -1;
      return;
    }
    speakAmp = ev.amplitude !== undefined ? ev.amplitude : 0;
    speakPitch = ev.pitch_hz !== undefined ? ev.pitch_hz : null;
  });
}

// ---------------------------------------------------------------------------
// W2.3 interaction (TODO §3e) — typed input + right-click menu.
//
// The window is click-through by default so the orb never steals input from
// whatever is underneath, but main forwards mouse events, so the renderer can
// SEE the pointer. It stops being click-through only while the cursor is over
// the orb itself (and while the text box is open). That is what makes a
// double-click and a right-click possible without turning a 280px transparent
// square into a click trap.
// ---------------------------------------------------------------------------
const HIT_R = 0.40;               // hit radius, as a fraction of the window size
const typedEl = document.getElementById('typed');
const typedInput = document.getElementById('typedInput');
let pointerInside = false;
let typedOpen = false;
// Wave 5: job_event table (PROTOCOL §5 `kind`/`parent`) — styling only.
let orbJobs = [];

function pointerOverOrb(ev) {
  const w = window.innerWidth, h = window.innerHeight;
  const dx = ev.clientX - w / 2, dy = ev.clientY - h / 2;
  return Math.hypot(dx, dy) <= HIT_R * Math.min(w, h);
}

function setMouseThrough(through) {
  try {
    if (window.raphael && window.raphael.setMouseThrough) window.raphael.setMouseThrough(!!through);
  } catch (e) { /* no preload */ }
}

function setPointerInside(v) {
  if (v === pointerInside || typedOpen) return;
  pointerInside = v;
  setMouseThrough(!v);
}

// Last mousemove as the listener actually SAW it — proves whether a synthetic
// event carried its coordinates or arrived as 0/undefined (that ambiguity made
// the hit-test check pass in isolation and fail in the full pipeline).
const lastMove = { x: null, y: null, dist: null, inside: null, seen: 0 };
window.addEventListener('mousemove', (ev) => {
  const w = window.innerWidth, h = window.innerHeight;
  const dx = ev.clientX - w / 2, dy = ev.clientY - h / 2;
  lastMove.x = ev.clientX;
  lastMove.y = ev.clientY;
  lastMove.dist = Math.hypot(dx, dy);
  lastMove.inside = pointerOverOrb(ev);
  lastMove.seen++;
  setPointerInside(lastMove.inside);
});

window.addEventListener('contextmenu', (ev) => {
  if (!pointerOverOrb(ev)) return;   // outside the orb: let the host app decide
  ev.preventDefault();
  try {
    if (window.raphael && window.raphael.sendOrbInput) window.raphael.sendOrbInput({ kind: 'menu' });
    if (window.raphael && window.raphael.openContextMenu) window.raphael.openContextMenu();
  } catch (e) { /* no preload */ }
});

function openTyped() {
  if (typedOpen || !typedEl) return;
  typedOpen = true;
  pointerInside = true;
  typedEl.classList.add('show');
  setMouseThrough(false);           // the box must take clicks and keys
  try { if (window.raphael && window.raphael.focusWindow) window.raphael.focusWindow(); } catch (e) {}
  typedInput.value = '';
  setTimeout(() => { try { typedInput.focus(); } catch (e) {} }, 30);
}

function closeTyped() {
  if (!typedOpen) return;
  typedOpen = false;
  typedEl.classList.remove('show');
  setMouseThrough(!pointerInside);  // hand the policy back to the cursor
}

async function submitTyped() {
  const text = (typedInput && typedInput.value || '').trim();
  if (!text) { closeTyped(); return; }
  let sent = false;
  try {
    // PROTOCOL §3: `command` { text, source: 'orb' } — role ui may send it
    if (window.raphael && window.raphael.sendCommand) sent = !!(await window.raphael.sendCommand(text));
    if (window.raphael && window.raphael.sendOrbInput) window.raphael.sendOrbInput({ kind: 'submit_text', value: text });
  } catch (e) { sent = false; }
  closeTyped();
  return sent;
}

window.addEventListener('dblclick', (ev) => {
  if (!pointerOverOrb(ev)) return;
  ev.preventDefault();
  openTyped();
});

if (typedInput) {
  typedInput.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter') { ev.preventDefault(); submitTyped(); }
    else if (ev.key === 'Escape') { ev.preventDefault(); closeTyped(); }
    ev.stopPropagation();
  });
}
window.addEventListener('blur', () => { if (typedOpen) closeTyped(); });

// Test hooks (CDP) — production never calls these directly.
window.__orbTyped = {
  open: openTyped, close: closeTyped, submit: submitTyped,
  isOpen: () => typedOpen, value: () => (typedInput ? typedInput.value : null),
  set: (v) => { if (typedInput) typedInput.value = v; },
};
window.__orbInteraction = () => ({ pointerInside, typedOpen, hitR: HIT_R, lastMove: { ...lastMove } });
// Direct probe of the SAME decision the mousemove listener makes, so a failure
// can be told apart from a synthetic-event dispatch quirk.
window.__orbPointer = (x, y) => {
  const w = window.innerWidth, h = window.innerHeight;
  const inside = pointerOverOrb({ clientX: x, clientY: y });
  const before = pointerInside;
  setPointerInside(inside);
  return { x, y, w, h, hitR: HIT_R * Math.min(w, h),
           dist: Math.hypot(x - w / 2, y - h / 2),
           inside, before, pointerInside, typedOpen };
};

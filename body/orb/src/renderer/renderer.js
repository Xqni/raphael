import * as THREE from 'three';
import { vertexShader, sphereVert } from './shaders/vertex.glsl.js';
import { fragmentShader, glowShader } from './shaders/fragment.glsl.js';
import { blurVert, blurFrag } from './shaders/blur.glsl.js';
import { initSageCore, updateSageCore, lockSageCore } from './sagecore.js';
import { initAnswerMode, updateAnswerMode, lockAnswerMode } from './answermode.js';
import { initDataRings, updateDataRings, lockDataRings } from './datarings.js';
import { initJobDots, updateJobDots, lockJobDots } from './jobdots.js';
import { resolvePalette } from './palette.js';

// Configuration injected via preload
const cfg = window.orbConfig || {
  sizePx: 280, contentPx: 200, opacity: 0.95, fpsCap: 60, quality: 'auto',
  backingDiscAlpha: 0.0, reducedMotion: false,
  theme: 'raphael', vibrance: 1.15, motionBlur: 'auto', startupSpinTauMs: 1400,
};

// §5 theme hook + §3.7 vibrance: resolved ONCE at page load (a design token,
// not a runtime state) — see docs/orb/THEMES.md. MUST come after `cfg`.
const PAL = resolvePalette(cfg);
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
const subtitleEl = document.getElementById('subtitle');
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

/**
 * Effective lattice shape (PROTOCOL §8 + ORB_REBUILD §3).
 * Each state owns a signature shape; the server's `shape_hint` wins only while
 * a foreground task is running (task_kind !== 'none'), which is exactly the
 * "morph by task kind" case from config orb.shape_map. This keeps the per-state
 * signature visible even though brain-core currently hardcodes `shape_hint:
 * 'circle'` on every frame (docs/requests/orb__to__brain-core__…).
 */
function effectiveShape() {
  const taskOwned = !!orbState.taskKind && orbState.taskKind !== 'none';
  if (taskOwned && orbState.serverShapeHint) return orbState.serverShapeHint;
  return STATE_SHAPE[orbState.orbState] || orbState.serverShapeHint || 'circle';
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
const BASE_VERTEX_COUNT = 60;
const OCTAGRAM_VERTEX_COUNT = 48;

function circlePoints(n) {
  const pts = [];
  for (let i = 0; i < n; i++) {
    const a = (i / n) * Math.PI * 2;
    pts.push(Math.cos(a), Math.sin(a), 0);
  }
  return new Float32Array(pts);
}
function polygonPoints(nSides, n, radius = 1) {
  const pts = [];
  for (let i = 0; i < n; i++) {
    const t = i / n;
    const a = t * Math.PI * 2;
    const s = Math.floor(t * nSides) % nSides;
    const sa = (s / nSides) * Math.PI * 2;
    const na = ((s + 1) / nSides) * Math.PI * 2;
    const edgeT = (t * nSides) % 1;
    const x = radius * (Math.cos(sa) * (1 - edgeT) + Math.cos(na) * edgeT);
    const y = radius * (Math.sin(sa) * (1 - edgeT) + Math.sin(na) * edgeT);
    pts.push(x, y, 0);
  }
  return new Float32Array(pts);
}
function octagramPoints(n) {
  const pts = [];
  const r1 = 1.0, r2 = 0.4;
  for (let i = 0; i < n; i++) {
    const t = i / n;
    const a = t * Math.PI * 2 * 4; // 8 points
    const r = i % 2 === 0 ? r1 : r2;
    pts.push(r * Math.cos(a), r * Math.sin(a), 0);
  }
  return new Float32Array(pts);
}

const LATTICE_DEPTH = 0.20; // world units of z the lattice gains (see below)
function makeMorphTarget(name) {
  let pts;
  if (name === 'octagram') pts = octagramPoints(OCTAGRAM_VERTEX_COUNT);
  else if (name === 'triangle') pts = polygonPoints(3, BASE_VERTEX_COUNT);
  else if (name === 'square') pts = polygonPoints(4, BASE_VERTEX_COUNT);
  else if (name === 'pentagon') pts = polygonPoints(5, BASE_VERTEX_COUNT);
  else if (name === 'hexagon') pts = polygonPoints(6, BASE_VERTEX_COUNT);
  else pts = circlePoints(BASE_VERTEX_COUNT);
  // USER FEEDBACK (2026-10-06) "nothing should feel 2d": the morph lattice was
  // a perfectly flat card in the XY plane, so revolving it read as paper.
  // Bend it into a shallow two-wave lens — same silhouette, real depth.
  const n = pts.length / 3;
  for (let i = 0; i < n; i++) {
    pts[i * 3 + 2] = Math.sin((i / n) * Math.PI * 2 * 2) * LATTICE_DEPTH;
  }
  return pts;
}

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
  });
  core = new THREE.Mesh(new THREE.SphereGeometry(0.52, 48, 32), coreMat);
  const glowMat = new THREE.ShaderMaterial({
    vertexShader,
    fragmentShader: glowShader,
    uniforms: coreU,
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
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
  latGeo.setAttribute('position', new THREE.BufferAttribute(makeMorphTarget('circle'), 3));
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
  const starMat = new THREE.PointsMaterial({ color: 0x58c4f2, size: 0.02, transparent: true, opacity: 0.5 });
  starsMesh = new THREE.Points(starGeo, starMat);
  scene.add(starsMesh);

  sage = initSageCore(THREE, group, scene, PAL); // Sage Core layers (spec §2.1)
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
  const to = makeMorphTarget(targetName);
  const posAttr = lattice.geometry.getAttribute('position');
  const fromArr = new Float32Array(posAttr.count * 3);
  for (let i = 0; i < fromArr.length; i++) fromArr[i] = posAttr.array[i];
  morphFrom = fromArr;
  morphTo = to;
  morphStart = performance.now();
  morphActive = true;
}

function updateMorph(now) {
  if (!morphActive || !morphFrom || !morphTo) return;
  const elapsed = now - morphStart;
  const t = Math.min(1, elapsed / MORPH_DURATION);
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
      if (ev.shapeHint && ev.shapeHint !== orbState.shapeHint) {
        orbState.shapeHint = ev.shapeHint;
        orbState.serverShapeHint = ev.shapeHint;
        startMorphTo(ev.shapeHint);
      }
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
  if (s === 'starting') return 0xfff4d6;
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
    // PROTOCOL §8: the SERVER's shape_hint is authoritative — the per-state
    // default only applies when the frame carried none (and `acting` has no
    // default of its own: it is owned by the task-kind map, config orb.shape_map).
    const want = effectiveShape();
    if (want !== orbState.shapeHint) {
      orbState.shapeHint = want;
      if (!poseLock) startMorphTo(want);
    }
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
  const mode = orbState.mode;
  updateSageCore(sage, { t, dt, state: orbState.orbState, mode, lock: poseLock, shape: orbState.shapeHint, amp: reactiveAmp, coreU: core.material.uniforms, ballScale, core, tint: getStateTint(orbState.orbState), glide: { x: GLX, y: GLY, blur: GLB } });
  if (AM) updateAnswerMode(AM, { t, dt, state: orbState.orbState, mode, lock: poseLock, amp: reactiveAmp, glide: { x: GLX, y: GLY } });
  if (DR) updateDataRings(DR, { t, dt, state: orbState.orbState, mode, lock: poseLock, amp: reactiveAmp, glide: { x: GLX, y: GLY } });
  if (JD) updateJobDots(JD, { t, dt, jobs: orbState.jobsActive, lock: poseLock });
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

function updateSubtitle(text) {
  if (!subtitleEl) return; // demo page has no subtitle element
  const isPrivate = orbState.private || orbState.mode === 'private' || orbState.orbState === 'private_overlay';
  if (isPrivate || !text) {
    subtitleEl.classList.remove('show');
    subtitleEl.classList.add('hide');
    return;
  }
  subtitleEl.textContent = text;
  subtitleEl.classList.remove('hide');
  subtitleEl.classList.add('show');
  if (subtitleTimer) clearTimeout(subtitleTimer);
  subtitleTimer = setTimeout(() => {
    subtitleEl.classList.remove('show');
    subtitleEl.classList.add('hide');
  }, 1200);
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
  const want = effectiveShape();
  orbState.shapeHint = want;
  // snap the lattice morph instead of animating it
  if (lattice) {
    const posAttr = lattice.geometry.getAttribute('position');
    const to = makeMorphTarget(want);
    const n = Math.min(posAttr.array.length, to.length);
    for (let i = 0; i < n; i++) posAttr.array[i] = to[i];
    posAttr.needsUpdate = true;
    morphActive = false; morphFrom = null; morphTo = null;
  }
  // clear every accumulated transform so all scenes share one pose
  rays.rotation.set(Math.PI / 4, 0, 0);
  rings[0].rotation.set(0, 0, 0);
  rings[1].rotation.set(0, 0, 0);
  lattice.rotation.set(0, 0, 0);
  group.rotation.set(0, 0, 0);
  const la = st === 'listening'
    ? (typeof orbState.amplitude === 'number' ? orbState.amplitude : 0)
    : (st === 'speaking' ? speakAmp : 0);
  if (sage) lockSageCore(sage, st, mode, { tint: getStateTint(st), amp: la, shape: orbState.shapeHint });
  if (AM) lockAnswerMode(AM, st, { amp: la });
  if (DR) lockDataRings(DR, st, { amp: la });
  if (JD) lockJobDots(JD, orbState.jobsActive);
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
  poseLocked: poseLock,
  rx: TRACE_RX.slice(-50),
  stats: window.__orbStats ? window.__orbStats() : null,
});
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
    const prevState = orbState.orbState;
    const prevShape = orbState.shapeHint;
    // PROTOCOL §8: `shape_hint` on the frame is authoritative; null means the
    // frame carried none and the per-state default applies instead.
    if ('shapeHint' in s) orbState.serverShapeHint = s.shapeHint || null;
    orbState = { ...orbState, ...s };
    orbState.serverShapeHint = ('shapeHint' in s) ? (s.shapeHint || null) : orbState.serverShapeHint;
    const want = effectiveShape();
    if (want !== prevShape) {
      orbState.shapeHint = want;
      // when the STATE also changed, animate()'s state-change block owns the
      // morph — morphing here too would restart the 600 ms ramp from scratch.
      if (!poseLock && orbState.orbState === prevState) startMorphTo(want);
    }
    // state-name text REMOVED (user: "text flashes when switching states") —
    // only explicit subtitles (spoken narration) are ever shown.
    if (s.subtitle) updateSubtitle(s.subtitle);
  });
  window.raphael.onSubtitle((t) => {
    traceRx('subtitle', t);
    if (t && t.text) updateSubtitle(t.text);
  });
  window.raphael.onSpeak((ev) => {
    traceRx('speak', ev);
    if (ev && ev.seq !== undefined && ev.seq <= lastSpeakSeq) return;
    if (ev && ev.seq !== undefined) lastSpeakSeq = ev.seq;
    if (ev && ev.event === 'end') {
      speakAmp = 0;
      speakPitch = null;
      return;
    }
    speakAmp = ev.amplitude || 0;
    speakPitch = ev.pitch_hz || null;
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

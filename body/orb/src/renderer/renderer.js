import * as THREE from 'three';
import { vertexShader, sphereVert } from './shaders/vertex.glsl.js';
import { fragmentShader, glowShader } from './shaders/fragment.glsl.js';
import { initSageCore, updateSageCore } from './sagecore.js';

// Configuration injected via preload
const cfg = window.orbConfig || { sizePx:180, opacity:0.95, fpsCap:60, quality:'auto', backingDiscAlpha:0.0, reducedMotion:false };
let sizePx = cfg.sizePx;
let fpsCap = cfg.fpsCap;
let quality = cfg.quality;
let backingDiscAlpha = cfg.backing_disc_alpha || cfg.backingDiscAlpha || 0.0;
let lastFrame = 0;
let frameCount = 0;
let lastFpsUpdate = performance.now();
const fpsEl = document.getElementById('fps'); // null on production page (index.html)
let frameInterval = 1000 / fpsCap;


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
  taskKind: 'none',
};
let speakAmp = 0;
let speakPitch = null;
let lastSpeakSeq = -1;
let subtitleTimer = null;

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

// Layer weight targets per state. latticeOpacity = 0 for Sage-Core states:
// the white polyhedron IS the wireframe now (cyan morph lattice reserved for
// acting/thinking phases).
const STATE_LAYER_TARGETS = {
  idle: { coreScale:1, haloOpacity:0.25, latticeOpacity:0 },
  listening: { coreScale:1.1, haloOpacity:0.3, latticeOpacity:0 },
  thinking: { coreScale:1.2, haloOpacity:0.35, latticeOpacity:0.45 },
  acting: { coreScale:1.3, haloOpacity:0.4, latticeOpacity:0.5 },
  speaking: { coreScale:1.2, haloOpacity:0.35, latticeOpacity:0.45 },
  error: { coreScale:0.9, haloOpacity:0.2, latticeOpacity:0 },
  reconnecting: { coreScale:1, haloOpacity:0.2, latticeOpacity:0 },
  offline: { coreScale:0.8, haloOpacity:0.1, latticeOpacity:0 },
  private_overlay: { coreScale:0.9, haloOpacity:0.2, latticeOpacity:0 },
  confirm: { coreScale:1, haloOpacity:0.3, latticeOpacity:0 },
  starting: { coreScale:1, haloOpacity:0.25, latticeOpacity:0 },
};
let layerWeights = { coreScale:1, haloOpacity:0.25, latticeOpacity:0.35 };


// Scene
let renderer, scene, camera, clock;
let group, core, lattice, halo, rings = [], rays, starsMesh, sage;

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

function makeMorphTarget(name) {
  if (name === 'octagram') return octagramPoints(OCTAGRAM_VERTEX_COUNT);
  if (name === 'triangle') return polygonPoints(3, BASE_VERTEX_COUNT);
  if (name === 'square') return polygonPoints(4, BASE_VERTEX_COUNT);
  if (name === 'pentagon') return polygonPoints(5, BASE_VERTEX_COUNT);
  if (name === 'hexagon') return polygonPoints(6, BASE_VERTEX_COUNT);
  return circlePoints(BASE_VERTEX_COUNT);
}

function easeInOutCubic(x) {
  return x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2;
}

function initScene() {
  renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, premultipliedAlpha: true });
  // Quality tier handling
  if (quality === 'low') renderer.setPixelRatio(0.5);
  else if (quality === 'medium') renderer.setPixelRatio(1);
  else if (quality === 'high') renderer.setPixelRatio(2);
  else renderer.setPixelRatio(window.devicePixelRatio); // auto
  renderer.setClearColor(0x000000, 0);
  renderer.setSize(sizePx, sizePx);

  scene = new THREE.Scene();
  camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
  camera.position.z = 4;

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

  sage = initSageCore(THREE, group, scene); // Sage Core layers (spec §2.1)
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

function getStateTint(s) {
  if (s === 'error') return 0xff0000;
  if (s === 'confirm') return 0xffa500;
  if (s === 'private_overlay' || orbState.private || orbState.mode === 'private') return 0x9aa5b1;
  if (s === 'reconnecting' || s === 'offline' || s === 'starting') return 0x58c4f2;
  if (s === 'acting') return 0xffd700;
  if (s === 'speaking') return 0xfff9d2;
  return 0xffffff;
}

function animate(now) {
  requestAnimationFrame(animate);
  if (DEMO) {
    runDemo(now);
  }
  const t = clock.getElapsedTime();
  const pitchNorm = speakPitch ? Math.max(0.8, Math.min(1.2, speakPitch / 220)) : 1;
  const breathBase = 2 * pitchNorm;
  const breath = 1 + 0.08 * Math.sin(t * breathBase);
  const pulse = 1 + speakAmp * 0.25;
  // Damping weights based on current orb state
  const target = STATE_LAYER_TARGETS[orbState.orbState] || STATE_LAYER_TARGETS.idle;
  const dt = now - lastFrame;
  layerWeights.coreScale = damp(layerWeights.coreScale, target.coreScale, MORPH_DURATION, dt);
  layerWeights.haloOpacity = damp(layerWeights.haloOpacity, target.haloOpacity, MORPH_DURATION, dt);
  layerWeights.latticeOpacity = damp(layerWeights.latticeOpacity, target.latticeOpacity, MORPH_DURATION, dt);
  const ballScale = breath * pulse * layerWeights.coreScale;
  core.scale.setScalar(ballScale);
  halo.scale.setScalar(breath * (1 + speakAmp * 0.15));
  halo.material.opacity = 0.25 * layerWeights.haloOpacity;
  lattice.material.opacity = 0.35 * layerWeights.latticeOpacity;
  updateSageCore(sage, { t, dt, state: orbState.orbState, amp: speakAmp, coreU: core.material.uniforms, ballScale });
  rays.rotation.z += 0.01;
  rings[0].rotation.z += 0.008;
  rings[1].rotation.z -= 0.006;
  lattice.rotation.y += 0.004;
  group.rotation.y += 0.003 * GROUP_SPIN;
  group.rotation.x = Math.sin(t * 0.045) * 0.05; // gentle bounded sway on x (not one flat plane)

  const stateTint = getStateTint(orbState.orbState);
  core.material.uniforms.color.value.setHex(stateTint); // ShaderMaterial: color lives in uniforms, not .color

  // Apply demo controls if present
  if (window.orbDemoSize && sizePx !== window.orbDemoSize) {
    sizePx = window.orbDemoSize;
    renderer.setSize(sizePx, sizePx);
  }
  if (window.orbDemoAmp !== undefined) {
    speakAmp = parseFloat(window.orbDemoAmp);
  }

  // Adjust frame interval based on state (active vs idle)
  const activeStates = ['listening','thinking','acting','speaking','error','private_overlay','reconnecting','offline','starting','confirm'];
  const isActive = activeStates.includes(orbState.orbState);
  const targetFps = isActive ? fpsCap : Math.max(30, Math.round(fpsCap/2));
  frameInterval = 1000 / targetFps;
  // Pause rendering when window is hidden
  if (document.hidden) return;
  if (now - lastFrame < frameInterval) return;
  lastFrame = now;
  updateMorph(now);
  renderer.render(scene, camera);

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
const demoStateSel = document.getElementById('stateSelect');
if (demoStateSel) {
  for (const key of Object.keys(STATE_LAYER_TARGETS)) {
    const opt = document.createElement('option');
    opt.value = key;
    opt.textContent = key;
    demoStateSel.appendChild(opt);
  }
  demoStateSel.addEventListener('change', () => {
    orbState.orbState = demoStateSel.value;
    updateSubtitle(demoStateSel.value);
  });
}
const demoSizeSlider = document.getElementById('sizeSlider');
if (demoSizeSlider) demoSizeSlider.addEventListener('input', (e) => { window.orbDemoSize = parseInt(e.target.value, 10); });
const demoAmpSlider = document.getElementById('ampSlider');
if (demoAmpSlider) demoAmpSlider.addEventListener('input', (e) => { window.orbDemoAmp = parseFloat(e.target.value); });

window.addEventListener('load', initScene);

if (window.raphael) {
  window.raphael.onOrbState((s) => {
    const prevShape = orbState.shapeHint;
    orbState = { ...orbState, ...s };
    if (s.shapeHint && s.shapeHint !== prevShape) {
      startMorphTo(s.shapeHint);
    }
    updateSubtitle(s.subtitle || s.orbState);
  });
  window.raphael.onSubtitle((t) => {
    if (t && t.text) updateSubtitle(t.text);
  });
  window.raphael.onSpeak((ev) => {
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

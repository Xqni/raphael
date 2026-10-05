import * as THREE from 'three';

const canvas = document.getElementById('webgl');
const subtitleEl = document.getElementById('subtitle');
const params = new URLSearchParams(window.location.search);
const DEMO = params.get('demo') === '1';

const sizePx = 180;
const fpsCap = 60;
let lastFrame = 0;
const frameInterval = 1000 / fpsCap;

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
let morphActive = false;
let morphStart = 0;
let morphFrom = null;
let morphTo = null;

// Scene
let renderer, scene, camera, clock;
let group, core, lattice, halo, rings = [], rays, starsMesh;

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
  renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  renderer.setPixelRatio(window.devicePixelRatio);
  renderer.setSize(sizePx, sizePx);
  renderer.setClearColor(0x000000, 0);

  scene = new THREE.Scene();
  camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
  camera.position.z = 4;

  clock = new THREE.Clock();

  group = new THREE.Group();
  scene.add(group);

  const coreGeo = new THREE.SphereGeometry(0.8, 32, 32);
  const coreMat = new THREE.MeshBasicMaterial({ color: 0xffffff });
  core = new THREE.Mesh(coreGeo, coreMat);
  group.add(core);

  const haloGeo = new THREE.RingGeometry(1.0, 1.15, 64);
  const haloMat = new THREE.MeshBasicMaterial({ color: 0xffda7a, side: THREE.DoubleSide, transparent: true, opacity: 0.25 });
  halo = new THREE.Mesh(haloGeo, haloMat);
  group.add(halo);

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
  core.scale.setScalar(breath * pulse);
  halo.scale.setScalar(breath * (1 + speakAmp * 0.15));
  rays.rotation.z += 0.01;
  rings[0].rotation.z += 0.008;
  rings[1].rotation.z -= 0.006;
  lattice.rotation.y += 0.004;
  group.rotation.y += 0.003;

  const stateTint = getStateTint(orbState.orbState);
  core.material.color.setHex(stateTint);

  if (now - lastFrame < frameInterval) return;
  lastFrame = now;
  updateMorph(now);
  renderer.render(scene, camera);
}

function updateSubtitle(text) {
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

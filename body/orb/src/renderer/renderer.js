import * as THREE from 'three';

const canvas = document.getElementById('webgl');
const subtitleEl = document.getElementById('subtitle');
const params = new URLSearchParams(window.location.search);
const DEMO = params.get('demo') === '1';

// Config surface
const sizePx = 180;
const fpsCap = 60;
let lastFrame = 0;
const frameInterval = 1000 / fpsCap;

// State
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
let speakPitch = null; // optional
let subtitleTimer = null;

// Three.js scene
let renderer, scene, camera, clock;
let group, core, lattice, rings = [], stars = [], halo, rays;

// Shape morph targets (icosahedral base points mapped conceptually)
const SHAPES = {
  circle: 'circle',
  triangle: 'triangle',
  square: 'square',
  pentagon: 'pentagon',
  hexagon: 'hexagon',
  octagram: 'octagram',
};

// Demo sequence
const demoSeq = [
  { t: 0, state: 'idle' },
  { t: 1000, state: 'listening' },
  { t: 2000, state: 'thinking' },
  { t: 3000, state: 'acting', shapeHint: 'octagram', taskKind: 'llm', jobsActive: 2 },
  { t: 4500, state: 'speaking', speak: { amplitude: 0.8, pitch_hz: 220 } },
  { t: 5500, state: 'speaking', speak: { amplitude: 0.4, pitch_hz: 180 } },
  { t: 6500, state: 'acting', shapeHint: 'square', taskKind: 'files', jobsActive: 1 },
  { t: 7500, state: 'idle', jobsActive: 0, shapeHint: 'circle' },
  { t: 8500, state: 'reconnecting' },
  { t: 9500, state: 'offline' },
  { t: 10500, state: 'error' },
  { t: 11500, state: 'starting' },
  { t: 12500, state: 'idle' },
];

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

  // core
  const coreGeo = new THREE.SphereGeometry(0.8, 32, 32);
  const coreMat = new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 1 });
  core = new THREE.Mesh(coreGeo, coreMat);
  group.add(core);

  // halo
  const haloGeo = new THREE.RingGeometry(1.0, 1.15, 64);
  const haloMat = new THREE.MeshBasicMaterial({ color: 0xffda7a, side: THREE.DoubleSide, transparent: true, opacity: 0.25 });
  halo = new THREE.Mesh(haloGeo, haloMat);
  group.add(halo);

  // simple rings
  for (let i = 0; i < 2; i++) {
    const geo = new THREE.RingGeometry(1.2 + i * 0.15, 1.25 + i * 0.15, 64, 1);
    const mat = new THREE.MeshBasicMaterial({ color: 0xffd700, side: THREE.DoubleSide, transparent: true, opacity: 0.5 });
    const m = new THREE.Mesh(geo, mat);
    group.add(m);
    rings.push(m);
  }

  // lattice (wireframe)
  const latGeo = new THREE.IcosahedronGeometry(1.05, 1);
  const latMat = new THREE.MeshBasicMaterial({ color: 0x58c4f2, wireframe: true, transparent: true, opacity: 0.35 });
  lattice = new THREE.Mesh(latGeo, latMat);
  group.add(lattice);

  // rays
  const rayGeo = new THREE.RingGeometry(0.9, 1.3, 8, 1);
  const rayMat = new THREE.MeshBasicMaterial({ color: 0xffb32c, side: THREE.DoubleSide, transparent: true, opacity: 0.2 });
  rays = new THREE.Mesh(rayGeo, rayMat);
  rays.rotation.x = Math.PI / 4;
  group.add(rays);

  // stars
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
  const starsMesh = new THREE.Points(starGeo, starMat);
  scene.add(starsMesh);
  stars.push(starsMesh);

  animate(0);
}

function animate(now) {
  requestAnimationFrame(animate);
  if (DEMO) {
    runDemo(now);
  }
  if (now - lastFrame < frameInterval) return;
  lastFrame = now;
  const t = clock.getElapsedTime();
  // breathing
  const breath = 1 + 0.08 * Math.sin(t * 2);
  core.scale.setScalar(breath * (1 + speakAmp * 0.25));
  halo.scale.setScalar(breath * (1 + speakAmp * 0.15));
  rays.rotation.z += 0.01;
  rings[0].rotation.z += 0.008;
  rings[1].rotation.z -= 0.006;
  lattice.rotation.y += 0.004;
  group.rotation.y += 0.003;
  renderer.render(scene, camera);
}

function runDemo(now) {
  for (let i = demoSeq.length - 1; i >= 0; i--) {
    if (now >= demoSeq[i].t) {
      const ev = demoSeq[i];
      if (ev.state !== orbState.orbState) {
        orbState.orbState = ev.state;
        updateSubtitle(`${ev.state}`);
      }
      if (ev.shapeHint) orbState.shapeHint = ev.shapeHint;
      if (ev.taskKind) orbState.taskKind = ev.taskKind;
      if (ev.jobsActive !== undefined) orbState.jobsActive = ev.jobsActive;
      if (ev.speak) {
        speakAmp = ev.speak.amplitude || 0;
        speakPitch = ev.speak.pitch_hz || null;
      } else if (ev.state !== 'speaking') {
        speakAmp = 0;
        speakPitch = null;
      }
      break;
    }
  }
}

function updateSubtitle(text) {
  if (!text) {
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

// IPC
if (window.raphael) {
  window.raphael.onOrbState((s) => {
    orbState = s;
    updateSubtitle(s.subtitle || s.orbState);
  });
  window.raphael.onSubtitle((t) => {
    if (t && t.text) updateSubtitle(t.text);
  });
  window.raphael.onSpeak((ev) => {
    speakAmp = ev.amplitude || 0;
    speakPitch = ev.pitch_hz || null;
  });
}

function onDrag() {
  // electron handles move; renderer no-op
}

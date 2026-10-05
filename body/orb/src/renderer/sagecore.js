// ============================================================================
// SAGE CORE — default orb look (ORB_REBUILD_TASK spec §2.1, layers 1-5 + 7).
// Layer 6 (the core itself) lives in renderer.js + shaders/fragment.glsl.js.
// Anime rendering rules (task appendix item 11): flat unlit additive color,
// uniform hairlines, head-on composition, layered 2D glow — never CGI-3D.
// Zero per-frame allocation: all geometry/materials/textures created once.
// ============================================================================
import { nebulaVert, nebulaFrag } from './shaders/nebula.glsl.js';
import {
  speedVert, speedFrag, polyVert, polyFrag,
  nodeVert, nodeFrag, ringVert, ringFrag,
  sparkVert, sparkFrag,
} from './shaders/sage.glsl.js';

const TAU = 400; // blend time constant (ms) — inside the spec's 300-600ms window

// Per-state visual targets for the Sage layers.
// nebula, speed(lines), poly, node, ring, spark, spin(rad/ms-ish), bright(core)
const S = {
  idle:            { nebula: 0.55, speed: 0.85, poly: 1.00, node: 1.00, ring: 0.75, spark: 0.70, spin: 0.00005, bright: 1.00 },
  listening:       { nebula: 0.80, speed: 1.35, poly: 1.10, node: 1.60, ring: 1.20, spark: 1.00, spin: 0.00007, bright: 1.45 },
  thinking:        { nebula: 0.65, speed: 1.00, poly: 1.60, node: 1.80, ring: 0.95, spark: 1.20, spin: 0.00040, bright: 1.15 },
  acting:          { nebula: 0.50, speed: 1.05, poly: 1.25, node: 1.35, ring: 0.90, spark: 0.80, spin: 0.00012, bright: 1.10 },
  speaking:        { nebula: 0.60, speed: 1.20, poly: 1.00, node: 1.20, ring: 1.00, spark: 0.90, spin: 0.00007, bright: 1.05 },
  confirm:         { nebula: 0.40, speed: 0.75, poly: 0.95, node: 1.10, ring: 0.70, spark: 0.50, spin: 0.00006, bright: 1.15 },
  error:           { nebula: 0.35, speed: 0.50, poly: 0.80, node: 0.80, ring: 0.50, spark: 0.30, spin: 0.00003, bright: 1.10 },
  starting:        { nebula: 0.30, speed: 0.40, poly: 0.60, node: 0.70, ring: 0.40, spark: 0.30, spin: 0.00002, bright: 0.70 },
  reconnecting:    { nebula: 0.30, speed: 0.50, poly: 0.70, node: 0.80, ring: 0.50, spark: 0.35, spin: 0.00002, bright: 0.75 },
  offline:         { nebula: 0.12, speed: 0.00, poly: 0.40, node: 0.40, ring: 0.20, spark: 0.10, spin: 0.000005, bright: 0.45 },
  private_overlay: { nebula: 0.50, speed: 0.85, poly: 1.00, node: 1.00, ring: 0.75, spark: 0.60, spin: 0.00005, bright: 1.00 },
};
const KEYS = Object.keys(S.idle);
const FALLBACK = S.idle;

function damp(cur, tgt, tau, dt) {
  const a = 1 - Math.exp(-dt / tau);
  return cur + (tgt - cur) * a;
}
function h(n) { return (Math.sin(n * 127.1) * 43758.5453) % 1; } // stable hash -1..1
function h01(n) { return Math.abs(h(n)); }

// --- Pane textures: drawn ONCE at startup (spec §5) -------------------------
function makePaneTexture(THREE, kind) {
  const c = document.createElement('canvas');
  c.width = c.height = 64;
  const x = c.getContext('2d');
  x.clearRect(0, 0, 64, 64);
  if (kind === 'soft') x.filter = 'blur(3px)'; // depth-of-field variant
  if (kind === 'cube') {
    // isometric cube outline — thin bright lines, faint fill
    x.beginPath();
    x.moveTo(32, 6); x.lineTo(56, 20); x.lineTo(56, 46);
    x.lineTo(32, 60); x.lineTo(8, 46); x.lineTo(8, 20); x.closePath();
    x.fillStyle = 'rgba(150,205,255,0.12)';
    x.fill();
    x.strokeStyle = 'rgba(226,244,255,0.95)';
    x.lineWidth = 3;
    x.stroke();
    x.beginPath();
    x.moveTo(32, 6); x.lineTo(32, 32); x.lineTo(56, 46);
    x.moveTo(32, 32); x.lineTo(8, 46);
    x.stroke();
  } else {
    x.strokeStyle = 'rgba(226,244,255,0.95)';
    x.lineWidth = 3;
    x.strokeRect(7, 7, 50, 50);
    x.fillStyle = 'rgba(150,205,255,0.13)';
    x.fillRect(7, 7, 50, 50);
    x.filter = 'none';
    x.fillStyle = 'rgba(226,244,255,0.85)'; // little data tick
    x.fillRect(15, 46, 14, 4);
  }
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

// --- Init -------------------------------------------------------------------
export function initSageCore(THREE, group, scene) {
  const L = { panes: [], ampS: 0 };
  L.w = Object.assign({}, S.idle);

  // 1) Nebula haze — scene-level (background canvas, unaffected by group spin)
  L.nebulaMat = new THREE.ShaderMaterial({
    vertexShader: nebulaVert,
    fragmentShader: nebulaFrag,
    uniforms: {
      uTime: { value: 0 }, uOpacity: { value: S.idle.nebula },
      cLime: { value: new THREE.Color(0xb8e02a) },
      cTeal: { value: new THREE.Color(0x2dd4bf) },
      cBlue: { value: new THREE.Color(0x3b82f6) },
      cMagenta: { value: new THREE.Color(0xc026d3) },
    },
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
  });
  const nebula = new THREE.Mesh(new THREE.PlaneGeometry(4.8, 4.8), L.nebulaMat);
  nebula.position.z = -0.9;
  scene.add(nebula);

  // 2) Floating data panes — scene-level, slow parallax drift (spec §2.1.2)
  const texSharp = makePaneTexture(THREE, 'sharp');
  const texSoft = makePaneTexture(THREE, 'soft');
  const texCube = makePaneTexture(THREE, 'cube');
  const paneGeo = new THREE.PlaneGeometry(1, 1);
  const N_PANES = 30;
  for (let i = 0; i < N_PANES; i++) {
    const near = ((i * 7) % 10) / 9;                 // 0 far .. 1 near
    const isCube = i % 5 === 0;
    const soft = !isCube && near < 0.34;             // far ones blurred (DoF)
    const mat = new THREE.MeshBasicMaterial({
      map: isCube ? texCube : (soft ? texSoft : texSharp),
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
      opacity: 0.10 + near * 0.30, color: 0xdff2ff,
    });
    const m = new THREE.Mesh(paneGeo, mat);
    const s = 0.09 + near * 0.20;
    m.scale.set(s, s, 1);
    const ang = (i / N_PANES) * Math.PI * 2 + i * 0.618 * Math.PI * 2;
    const rad = 0.55 + h01(i + 3) * 0.75;            // max ~1.30 (+half size < edge)
    const z = -0.35 + ((i * 13) % 9) / 8 * 0.75;
    m.position.set(Math.cos(ang) * rad, Math.sin(ang) * rad, z);
    m.rotation.z = (i % 4) * Math.PI * 4;            // axis-aligned squares
    scene.add(m);
    L.panes.push({
      m, mat, baseOp: mat.opacity, ang, rad, near,
      speed: (0.008 + h01(i + 11) * 0.014) * (0.4 + near * 1.2), // parallax
      phase: i * 1.7,
    });
  }

  // 3) Radial hairlines / speed lines (spec §2.1.3) — 3D: fibonacci-sphere
  // directions so rays burst off the center in EVERY direction (user review:
  // flat-plane rays rotated like a 2D image; some rays now pass behind the ball)
  const RAYS = 110;
  const rp = new Float32Array(RAYS * 6);
  const rs = new Float32Array(RAYS * 2);
  const ga = Math.PI * (3 - Math.sqrt(5));
  for (let i = 0; i < RAYS; i++) {
    const dy = 1 - (i / (RAYS - 1)) * 2;               // -1..1
    const ringR = Math.sqrt(Math.max(0, 1 - dy * dy));
    const th = ga * i;
    const dx = Math.cos(th) * ringR;
    const dz = Math.sin(th) * ringR;
    const r0 = 0.54 + h01(i + 5) * 0.16;               // start just off the ball
    const len = Math.min(0.30 + h01(i + 9) * 0.55, 1.45 - r0);
    rp[i * 6 + 0] = dx * r0;      rp[i * 6 + 1] = dy * r0;      rp[i * 6 + 2] = dz * r0;
    rp[i * 6 + 3] = dx * (r0 + len); rp[i * 6 + 4] = dy * (r0 + len); rp[i * 6 + 5] = dz * (r0 + len);
    rs[i * 2] = rs[i * 2 + 1] = h01(i + 21);
  }
  const speedGeo = new THREE.BufferGeometry();
  speedGeo.setAttribute('position', new THREE.BufferAttribute(rp, 3));
  speedGeo.setAttribute('aSeed', new THREE.BufferAttribute(rs, 1));
  L.speedMat = new THREE.ShaderMaterial({
    vertexShader: speedVert, fragmentShader: speedFrag,
    uniforms: { uTime: { value: 0 }, uAlpha: { value: 1 }, uLength: { value: 1 } },
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
  });
  L.speed = new THREE.LineSegments(speedGeo, L.speedMat);
  group.add(L.speed);

  // 4) Wireframe polyhedron + node dots + short spokes (spec §2.1.4)
  const icosa = new THREE.IcosahedronGeometry(1.15, 1);
  const edges = new THREE.EdgesGeometry(icosa);
  const ePos = edges.attributes.position.array;
  const eCount = ePos.length / 6;
  const uniq = [];
  const seen = new Set();
  const ip = icosa.attributes.position.array;
  for (let i = 0; i < ip.length; i += 3) {
    const k = ip[i].toFixed(3) + ',' + ip[i + 1].toFixed(3) + ',' + ip[i + 2].toFixed(3);
    if (!seen.has(k)) { seen.add(k); uniq.push([ip[i], ip[i + 1], ip[i + 2]]); }
  }
  const SPOKES = 14;
  const lp = new Float32Array(ePos.length + SPOKES * 6);
  lp.set(ePos);
  const aT = new Float32Array((ePos.length / 3) + SPOKES * 2);
  const aId = new Float32Array(aT.length);
  const aSp = new Float32Array(aT.length);
  for (let e = 0; e < eCount; e++) {
    aT[e * 2] = 0; aT[e * 2 + 1] = 1;
    aId[e * 2] = aId[e * 2 + 1] = e;
  }
  let w = ePos.length / 3;
  for (let s = 0; s < SPOKES; s++) {
    const v = uniq[(s * 3) % uniq.length];
    lp[w * 3 + 0] = v[0]; lp[w * 3 + 1] = v[1]; lp[w * 3 + 2] = v[2]; w++;
    lp[w * 3 + 0] = v[0] * 1.13; lp[w * 3 + 1] = v[1] * 1.13; lp[w * 3 + 2] = v[2] * 1.13; w++;
    aT[w - 2] = 0; aT[w - 1] = 1;
    aId[w - 2] = aId[w - 1] = 2000 + s;
    aSp[w - 2] = aSp[w - 1] = 1;
  }
  const polyGeo = new THREE.BufferGeometry();
  polyGeo.setAttribute('position', new THREE.BufferAttribute(lp, 3));
  polyGeo.setAttribute('aEdgeT', new THREE.BufferAttribute(aT, 1));
  polyGeo.setAttribute('aEdgeId', new THREE.BufferAttribute(aId, 1));
  polyGeo.setAttribute('aSpoke', new THREE.BufferAttribute(aSp, 1));
  L.polyMat = new THREE.ShaderMaterial({
    vertexShader: polyVert, fragmentShader: polyFrag,
    uniforms: { uTime: { value: 0 }, uAlpha: { value: 1 }, uPulse: { value: 1 } },
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
  });
  L.poly = new THREE.LineSegments(polyGeo, L.polyMat);
  L.poly.rotation.x = 0.30;               // subtle depth, still head-on/graphic
  group.add(L.poly);

  // Inner cage: the SAME polyhedron at smaller scale hugging the core ball
  // (user prescription: revolving polygon at smaller scale around the sphere).
  L.cage = new THREE.LineSegments(polyGeo, L.polyMat);
  L.cage.scale.setScalar(0.56);           // 1.15 * 0.56 = 0.64 > ball 0.52
  L.cage.rotation.x = 0.30;
  group.add(L.cage);

  // Randomized spin directions per object on BOTH axes (user: not one single
  // direction) — deterministic hashes so each object tumbles its own way.
  const sgn = (n) => (h01(n) > 0.5 ? 1 : -1);
  L.dir = {
    polyX: sgn(7) * (0.5 + h01(11) * 0.5),
    polyY: sgn(13) * (0.7 + h01(17) * 0.6),
    cageX: sgn(19) * (0.6 + h01(23) * 0.6),
    cageY: sgn(29) * (0.9 + h01(31) * 0.8),
    speedX: sgn(37) * (0.4 + h01(41) * 0.4),
    speedY: sgn(43) * (0.5 + h01(47) * 0.5),
    ringB: sgn(53),
    ringF: sgn(59),
  };

  const np = new Float32Array(uniq.length * 3);
  for (let i = 0; i < uniq.length; i++) {
    np[i * 3] = uniq[i][0]; np[i * 3 + 1] = uniq[i][1]; np[i * 3 + 2] = uniq[i][2];
  }
  const nodeGeo = new THREE.BufferGeometry();
  nodeGeo.setAttribute('position', new THREE.BufferAttribute(np, 3));
  L.nodeMat = new THREE.ShaderMaterial({
    vertexShader: nodeVert, fragmentShader: nodeFrag,
    uniforms: {
      uTime: { value: 0 }, uAlpha: { value: 1 },
      uBoost: { value: 1 }, uSize: { value: 7.5 },
    },
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
  });
  L.nodes = new THREE.Points(nodeGeo, L.nodeMat);
  L.nodes.rotation.x = 0.30;
  group.add(L.nodes);

  // 5) Orbit rings — tilted ellipse split into a dim back half + bright front
  //    arc so it reads as passing BEHIND and IN FRONT of the core (spec §2.1.5)
  const ringBackMat = new THREE.ShaderMaterial({
    vertexShader: ringVert, fragmentShader: ringFrag,
    uniforms: { uTime: { value: 0 }, uAlpha: { value: 0.35 }, uSeed: { value: 0.37 }, uTint: { value: new THREE.Color(0xffffff) } },
    side: THREE.DoubleSide, transparent: true, depthWrite: false,
    blending: THREE.AdditiveBlending,
  });
  const ringFrontMat = ringBackMat.clone();
  ringFrontMat.uniforms.uSeed.value = 0.81;
  ringFrontMat.uniforms.uAlpha.value = 0.8;
  const backGeo = new THREE.RingGeometry(1.24, 1.264, 72, 1, Math.PI, Math.PI);
  const frontGeo = new THREE.RingGeometry(1.24, 1.274, 72, 1, 0.04, Math.PI - 0.08);
  L.ringBack = new THREE.Mesh(backGeo, ringBackMat);
  L.ringFront = new THREE.Mesh(frontGeo, ringFrontMat);
  const tilt = { x: 1.02, y: -0.10 };     // tilted until it crosses the core
  L.ringBack.rotation.set(tilt.x, tilt.y, 0);
  L.ringFront.rotation.set(tilt.x, tilt.y, 0);
  L.ringBack.position.z = -0.24;
  L.ringFront.position.z = 0.24;
  group.add(L.ringBack);
  group.add(L.ringFront);
  L.ringBackMat = ringBackMat;
  L.ringFrontMat = ringFrontMat;

  // Private Mode: thin teal outer ring (spec §3) — only lit in private_overlay
  L.privateMat = new THREE.ShaderMaterial({
    vertexShader: ringVert, fragmentShader: ringFrag,
    uniforms: { uTime: { value: 0 }, uAlpha: { value: 0 }, uSeed: { value: 0.63 },
                uTint: { value: new THREE.Color(0x2dd4bf) } },
    side: THREE.DoubleSide, transparent: true, depthWrite: false,
    blending: THREE.AdditiveBlending,
  });
  L.privateRing = new THREE.Mesh(new THREE.RingGeometry(1.4, 1.425, 96), L.privateMat);
  L.privateRing.rotation.set(0.12, 0.06, 0);
  group.add(L.privateRing);
  L.privateW = 0;

  // 7) Sparkle dust (spec §2.1.7)
  const N_SPARK = 40;
  const sp = new Float32Array(N_SPARK * 3);
  const ss = new Float32Array(N_SPARK);
  for (let i = 0; i < N_SPARK; i++) {
    const a = h01(i + 31) * Math.PI * 2;
    const r = 0.70 + h01(i + 41) * 0.75;
    const z = (h01(i + 51) - 0.5) * 1.2;
    sp[i * 3] = Math.cos(a) * r; sp[i * 3 + 1] = Math.sin(a) * r; sp[i * 3 + 2] = z;
    ss[i] = h01(i + 61);
  }
  const sparkGeo = new THREE.BufferGeometry();
  sparkGeo.setAttribute('position', new THREE.BufferAttribute(sp, 3));
  sparkGeo.setAttribute('aSeed', new THREE.BufferAttribute(ss, 1));
  L.sparkMat = new THREE.ShaderMaterial({
    vertexShader: sparkVert, fragmentShader: sparkFrag,
    uniforms: { uTime: { value: 0 }, uAlpha: { value: 0.7 }, uSize: { value: 6 } },
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
  });
  L.spark = new THREE.Points(sparkGeo, L.sparkMat);
  group.add(L.spark);

  return L;
}

// --- Per-frame update -------------------------------------------------------
// ctx = { t (s), dt (ms), state, amp (0..1), coreU (core material uniforms) }
export function updateSageCore(L, ctx) {
  const t = ctx.t, dt = Math.min(Math.max(ctx.dt, 1), 100), state = ctx.state;
  const tgt = S[state] || FALLBACK;

  // amplitude smoothing: ~30ms attack, ~150ms release (spec §6)
  const ampTgt = ctx.amp || 0;
  L.ampS = damp(L.ampS, ampTgt, ampTgt > L.ampS ? 30 : 150, dt);

  // damped state blending (300-600ms, no pops)
  for (let i = 0; i < KEYS.length; i++) {
    const k = KEYS[i];
    L.w[k] = damp(L.w[k], tgt[k], TAU, dt);
  }
  const w = L.w;
  const listening = state === 'listening' ? 1 : 0;

  // 1) nebula
  L.nebulaMat.uniforms.uTime.value = t;
  L.nebulaMat.uniforms.uOpacity.value = w.nebula;

  // 3) speed lines — listening: rays lengthen (ripple handled by shimmer)
  L.speedMat.uniforms.uTime.value = t;
  L.speedMat.uniforms.uAlpha.value = w.speed;
  L.speedMat.uniforms.uLength.value = 1 + listening * L.ampS * 0.55;

  // 4) polyhedron + nodes — slow spin, edge pulses; listening: nodes brighten
  L.polyMat.uniforms.uTime.value = t;
  L.polyMat.uniforms.uAlpha.value = w.poly * 0.9;
  L.polyMat.uniforms.uPulse.value = w.poly;
  // Outer cage follows the breathing to keep the gap ~constant (user), but is
  // CAPPED so neither layer ever grows too big (max radius ~1.32 world units).
  const outerS = Math.min(1.12, 1 + 0.45 * ((ctx.ballScale || 1) - 1));
  L.poly.scale.setScalar(outerS);
  if (L.nodes) L.nodes.scale.setScalar(outerS);
  L.poly.rotation.y += w.spin * dt * L.dir.polyY;
  L.poly.rotation.x += w.spin * dt * 0.5 * L.dir.polyX;
  if (L.cage) {
    L.cage.rotation.y += w.spin * dt * L.dir.cageY * 1.7;
    L.cage.rotation.x += w.spin * dt * 0.7 * L.dir.cageX;
    if (ctx.ballScale) L.cage.scale.setScalar(0.56 * ctx.ballScale); // cage breathes WITH the ball
  }
  L.speed.rotation.y += w.spin * dt * 0.4 * L.dir.speedY;
  L.speed.rotation.x += w.spin * dt * 0.25 * L.dir.speedX;
  L.nodeMat.uniforms.uTime.value = t;
  L.nodeMat.uniforms.uAlpha.value = w.node;
  L.nodeMat.uniforms.uBoost.value = 1 + listening * L.ampS * 0.8;
  L.nodes.rotation.y = L.poly.rotation.y; // node dots track the lattice exactly
  L.nodes.rotation.x = L.poly.rotation.x;

  // 5) rings — counter-rotating slowly, amp scales ring slightly when listening
  L.ringBackMat.uniforms.uTime.value = t;
  L.ringBackMat.uniforms.uAlpha.value = w.ring * 0.45;
  L.ringFrontMat.uniforms.uTime.value = t;
  L.ringFrontMat.uniforms.uAlpha.value = w.ring * 0.9;
  const ringScale = 1 + listening * L.ampS * 0.05;
  L.ringBack.scale.setScalar(ringScale);
  L.ringFront.scale.setScalar(ringScale);
  L.ringBack.rotation.z += 0.0004 * dt * L.dir.ringB;
  L.ringFront.rotation.z += 0.0003 * dt * L.dir.ringF;
  // Private teal ring fades in only for private_overlay
  L.privateW = damp(L.privateW, state === 'private_overlay' ? 1 : 0, TAU, dt);
  L.privateMat.uniforms.uTime.value = t;
  L.privateMat.uniforms.uAlpha.value = L.privateW * 0.9;
  L.privateRing.rotation.z += 0.0005 * dt * L.dir.ringF;

  // 7) sparkles
  L.sparkMat.uniforms.uTime.value = t;
  L.sparkMat.uniforms.uAlpha.value = w.spark;

  // 2) panes — slow drift with depth parallax + occasional flicker (prealloc'd)
  for (let i = 0; i < L.panes.length; i++) {
    const p = L.panes[i];
    const a = p.ang + t * p.speed;
    p.m.position.x = Math.cos(a) * p.rad;
    p.m.position.y = Math.sin(a) * p.rad + Math.sin(t * 0.3 + p.phase) * 0.03;
    let op = p.baseOp * (0.85 + 0.15 * Math.sin(t * (0.5 + i * 0.03) + p.phase));
    if (Math.sin(t * 0.9 + p.phase * 2.7) > 0.992) op *= 0.35; // rare flicker
    p.mat.opacity = op * (0.4 + w.nebula * 0.9);
  }

  // 6) core brightness/amp + state FX (warning pulse / reconnect flicker)
  let fx = 1;
  if (state === 'error' || state === 'confirm') {
    fx = 0.8 + 0.35 * (0.5 + 0.5 * Math.sin(t * 3.4));      // slow warning pulse
  } else if (state === 'reconnecting') {
    fx = 0.55 + 0.45 * (0.5 + 0.5 * Math.sin(t * 11.0) * Math.sin(t * 4.7)); // dim flicker
  }
  const cu = ctx.coreU;
  if (cu && cu.uBright && cu.uAmp) {
    cu.uBright.value = damp(cu.uBright.value, w.bright * fx, TAU, dt);
    cu.uAmp.value = L.ampS;
  }
}

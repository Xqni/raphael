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
// `paused` and `offline` are deliberately BOTH "dead grey" (ORB_REBUILD §3) but
// are told apart by structure: paused is a MODE overlay (steel ring, lattice
// still lit, 10% spin) while offline is a state with everything switched off.
const S = {
  idle:            { nebula: 0.55, speed: 0.70, poly: 1.15, node: 1.30, ring: 0.80, spark: 0.70, spin: 0.00013, bright: 1.00, cage: 1.00 },
  listening:       { nebula: 0.80, speed: 1.35, poly: 1.55, node: 2.10, ring: 1.45, spark: 1.00, spin: 0.00017, bright: 1.45, cage: 1.00 },
  thinking:        { nebula: 0.65, speed: 1.00, poly: 1.60, node: 1.80, ring: 0.95, spark: 1.20, spin: 0.00040, bright: 1.15, cage: 0.15 },
  acting:          { nebula: 0.50, speed: 1.05, poly: 1.25, node: 1.35, ring: 0.90, spark: 0.80, spin: 0.00014, bright: 1.10, cage: 1.00 },
  speaking:        { nebula: 0.60, speed: 1.20, poly: 1.00, node: 1.20, ring: 1.00, spark: 0.30, spin: 0.00016, bright: 1.05, cage: 1.00 },
  confirm:         { nebula: 0.40, speed: 0.75, poly: 0.95, node: 1.10, ring: 0.70, spark: 0.50, spin: 0.00013, bright: 1.15, cage: 1.00 },
  error:           { nebula: 0.35, speed: 0.50, poly: 0.80, node: 0.80, ring: 0.50, spark: 0.30, spin: 0.00012, bright: 1.45, cage: 0.60 },
  starting:        { nebula: 0.35, speed: 0.50, poly: 0.70, node: 0.70, ring: 0.40, spark: 0.35, spin: 0.00006, bright: 0.72, cage: 1.00 },
  reconnecting:    { nebula: 0.45, speed: 0.55, poly: 0.85, node: 0.90, ring: 0.55, spark: 0.45, spin: 0.00008, bright: 0.75, cage: 0.80 },
  offline:         { nebula: 0.00, speed: 0.00, poly: 0.30, node: 0.30, ring: 0.00, spark: 0.00, spin: 0.000006, bright: 0.30, cage: 0.25 },
  paused:          { nebula: 0.16, speed: 0.00, poly: 0.75, node: 0.70, ring: 0.40, spark: 0.10, spin: 0.000014, bright: 0.60, cage: 0.50 },
  private_overlay: { nebula: 0.55, speed: 0.70, poly: 1.15, node: 1.30, ring: 0.80, spark: 0.70, spin: 0.00013, bright: 1.00, cage: 1.00 },
};
const KEYS = Object.keys(S.idle);
const FALLBACK = S.idle;

function damp(cur, tgt, tau, dt) {
  const a = 1 - Math.exp(-dt / tau);
  return cur + (tgt - cur) * a;
}
function h(n) { return (Math.sin(n * 127.1) * 43758.5453) % 1; } // stable hash -1..1
function h01(n) { return Math.abs(h(n)); }

// ---------------------------------------------------------------------------
// Per-state CAGE SHAPE (user, 2026-10-06): "make the cages change shapes for
// different states with color changes as well ... keep things 3d".
//
// The icosphere TOPOLOGY is preserved — every vertex is projected onto the
// target solid along its own direction, so edges, spokes and node dots all stay
// attached while the silhouette becomes a cube / prism / octahedron / ball.
// Positions lerp over 600 ms with an ease-in-out (never snapped), and because
// the deformation is radial, the cage still reads as a solid 3D object from
// every angle — no flat card anywhere.
// ---------------------------------------------------------------------------
const CAGE_MORPH_MS = 600;

/** Radius of a regular n-gon (circumradius 1) at polar angle `theta`. */
function nGonScale(theta, n) {
  const seg = (Math.PI * 2) / n;
  const a = ((theta % seg) + seg) % seg - seg / 2;
  return Math.cos(Math.PI / n) / Math.cos(a);
}

/**
 * src/out are Float32Array vertex sets of the SAME topology. `shape` is one of
 * the PROTOCOL §8 / config orb.shape_map values; anything unknown is the ball.
 */
export function projectShape(src, shape, out) {
  for (let i = 0; i < src.length; i += 3) {
    const x = src[i], y = src[i + 1], z = src[i + 2];
    const len = Math.hypot(x, y, z) || 1;
    const dx = x / len, dy = y / len, dz = z / len;
    let px = dx, py = dy, pz = dz;
    const th = Math.atan2(dy, dx);
    if (shape === 'square') {                 // -> cube (square cross-section)
      const s = nGonScale(th, 4); px = dx * s; py = dy * s;
    } else if (shape === 'triangle') {        // -> triangular prism
      const s = nGonScale(th, 3); px = dx * s; py = dy * s; pz = dz * 0.78;
    } else if (shape === 'pentagon') {        // -> pentagonal prism
      const s = nGonScale(th, 5); px = dx * s; py = dy * s; pz = dz * 0.88;
    } else if (shape === 'hexagon') {         // -> hexagonal prism
      const s = nGonScale(th, 6); px = dx * s; py = dy * s; pz = dz * 0.78;
    } else if (shape === 'octagram') {        // -> octahedron: sharp, spiky
      const m = Math.abs(dx) + Math.abs(dy) + Math.abs(dz) || 1e-6;
      px = dx / m; py = dy / m; pz = dz / m;
    }
    // 'circle' (and anything unknown) falls through as the plain sphere
    out[i] = px * len; out[i + 1] = py * len; out[i + 2] = pz * len;
  }
}

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
export function initSageCore(THREE, group, scene, pal) {
  pal = pal || { haze_lime: '#B8E02A', haze_teal: '#2DD4BF', haze_blue: '#3B82F6', haze_magenta: '#C026D3', ring_color: '#FFFFFF', accent: '#2DD4BF' };
  const L = { panes: [], ampS: 0 };
  L.w = Object.assign({}, S.idle);

  // 1) Nebula haze — scene-level (background canvas, unaffected by group spin)
  L.nebulaMat = new THREE.ShaderMaterial({
    vertexShader: nebulaVert,
    fragmentShader: nebulaFrag,
    uniforms: {
      uTime: { value: 0 }, uOpacity: { value: S.idle.nebula },
      cLime: { value: new THREE.Color(pal.haze_lime) },      // §5 tokens + §3.7 vibrance
      cTeal: { value: new THREE.Color(pal.haze_teal) },
      cBlue: { value: new THREE.Color(pal.haze_blue) },
      cMagenta: { value: new THREE.Color(pal.haze_magenta) },
    },
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
  });
  const nebula = new THREE.Mesh(new THREE.PlaneGeometry(4.8, 4.8), L.nebulaMat);
  L.nebula = nebula;
  nebula.position.z = -0.9;
  scene.add(nebula);

  // 2) Floating data panes — scene-level, slow parallax drift (spec §2.1.2)
  const texSharp = makePaneTexture(THREE, 'sharp');
  const texSoft = makePaneTexture(THREE, 'soft');
  const texCube = makePaneTexture(THREE, 'cube');
  const paneGeo = new THREE.PlaneGeometry(1, 1);
  const N_PANES = 18;   // §3.6: fewer, larger panes (was 30 small ones)
  for (let i = 0; i < N_PANES; i++) {
    const near = ((i * 7) % 10) / 9;                 // 0 far .. 1 near
    const isCube = i % 4 === 0;
    const soft = !isCube && near < 0.30;             // far ones blurred (DoF)
    const mat = new THREE.MeshBasicMaterial({
      map: isCube ? texCube : (soft ? texSoft : texSharp),
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
      opacity: 0.12 + near * 0.32, color: 0xdff2ff,
    });
    const m = new THREE.Mesh(paneGeo, mat);
    const s = 0.13 + near * 0.30;   // §3.6: larger
    m.scale.set(s, s, 1);
    const ang = (i / N_PANES) * Math.PI * 2 + i * 0.618 * Math.PI * 2;
    const rad = 0.50 + h01(i + 3) * 0.80;            // max ~1.30 (+half size < edge)
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
    const len = Math.min(0.30 + h01(i + 9) * 0.55, 1.32 - r0); // tips inside mask-safe zone (user: rays cut)
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
  const SPOKES = 10;   // §3.3: fewer stray spokes (wireframe reads cleaner)
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
    uniforms: { uTime: { value: 0 }, uAlpha: { value: 1 }, uPulse: { value: 1 }, uTint: { value: new THREE.Color(0xffffff) }, uDrop: { value: 0 } },
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
  });
  L.poly = new THREE.LineSegments(polyGeo, L.polyMat);
  L.poly.rotation.x = 0.30;               // subtle depth, still head-on/graphic
  group.add(L.poly);

  // Inner cage: the SAME polyhedron at smaller scale hugging the core ball
  // (user prescription: revolving polygon at smaller scale around the sphere).
  L.cageMat = L.polyMat.clone();   // own material: per-state cage weight (§3.3)
  L.cage = new THREE.LineSegments(polyGeo, L.cageMat);
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
      uBoost: { value: 1 }, uSize: { value: 8.5 },   // §3.6: slightly heavier node weight
      uTint: { value: new THREE.Color(0xffffff) },
    },
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
  });
  L.nodes = new THREE.Points(nodeGeo, L.nodeMat);
  L.nodes.rotation.x = 0.30;
  group.add(L.nodes);

  // per-state cage-shape morph state (see projectShape above). The outer cage,
  // the inner cage and the node dots all ride these buffers, so they deform as
  // one object instead of drifting apart.
  L.polyGeo = polyGeo;
  L.nodeGeo = nodeGeo;
  L.polyBase = new Float32Array(lp);              // pristine icosphere
  L.nodeBase = new Float32Array(np);
  L.cageFrom = new Float32Array(lp.length);       // preallocated: no per-frame alloc
  L.cageTo = new Float32Array(lp.length);
  L.nodeFrom = new Float32Array(np.length);
  L.nodeTo = new Float32Array(np.length);
  L.cageShape = 'circle';
  L.cageMs = CAGE_MORPH_MS;
  L.cageActive = false;

  // 5) Orbit rings — tilted ellipse split into a dim back half + bright front
  //    arc so it reads as passing BEHIND and IN FRONT of the core (spec §2.1.5)
  const ringBackMat = new THREE.ShaderMaterial({
    vertexShader: ringVert, fragmentShader: ringFrag,
    uniforms: { uTime: { value: 0 }, uAlpha: { value: 0.35 }, uSeed: { value: 0.37 }, uTint: { value: new THREE.Color(pal.ring_color) } }, // §5 token
    side: THREE.DoubleSide, transparent: true, depthWrite: false,
    blending: THREE.AdditiveBlending,
  });
  const ringFrontMat = ringBackMat.clone();
  ringFrontMat.uniforms.uSeed.value = 0.81;
  ringFrontMat.uniforms.uAlpha.value = 0.8;
  // §3.6 "slightly thicker line weights": these are real geometry (unlike the
  // GL_LINES wireframe, whose width WebGL clamps to 1 device px), so the
  // tilted orbit ring is the one line weight we can actually turn up.
  const backGeo = new THREE.RingGeometry(1.238, 1.278, 72, 1, Math.PI, Math.PI);
  const frontGeo = new THREE.RingGeometry(1.236, 1.298, 72, 1, 0.04, Math.PI - 0.08);
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

  // MODE overlays (INTERFACES §e: private/paused are `mode`, NOT states, so
  // they must render on top of ANY base state):
  //   private -> thin TEAL outer ring (ORB_REBUILD §3 "always clear cloud is off")
  //   paused  -> dashed STEEL outer ring (same design language, unmistakable
  //              colour+shape difference from private and from offline)
  L.privateMat = new THREE.ShaderMaterial({
    vertexShader: ringVert, fragmentShader: ringFrag,
    uniforms: { uTime: { value: 0 }, uAlpha: { value: 0 }, uSeed: { value: 0.63 },
                uTint: { value: new THREE.Color(pal.private_ring || pal.accent) } }, // semantic teal (never themed)
    side: THREE.DoubleSide, transparent: true, depthWrite: false,
    blending: THREE.AdditiveBlending,
  });
  // ... a DOUBLE hairline so a 1.6px line is still legible at 280px window
  // size over a LIGHT wallpaper (single line = ~1.3/255 mean, too subtle).
  L.privateRing = new THREE.Mesh(new THREE.RingGeometry(1.262, 1.302, 96), L.privateMat);
  L.privateRing.rotation.set(0.12, 0.06, 0);
  group.add(L.privateRing);
  L.privateW = 0;
  L.privateMat2 = L.privateMat.clone();
  L.privateMat2.uniforms.uSeed.value = 0.41;
  L.privateRing2 = new THREE.Mesh(new THREE.RingGeometry(1.335, 1.372, 96), L.privateMat2);
  L.privateRing2.rotation.set(0.12, 0.06, 0);
  group.add(L.privateRing2);

  L.pausedMat = new THREE.ShaderMaterial({
    vertexShader: ringVert, fragmentShader: ringFrag,
    uniforms: { uTime: { value: 0 }, uAlpha: { value: 0 }, uSeed: { value: 0.19 },
                uTint: { value: new THREE.Color(0x9fb6d8) } },
    side: THREE.DoubleSide, transparent: true, depthWrite: false,
    blending: THREE.AdditiveBlending,
  });
  L.pausedRing = new THREE.Mesh(new THREE.RingGeometry(1.33, 1.372, 96), L.pausedMat);
  L.pausedRing.rotation.set(-0.16, 0.10, 0);
  group.add(L.pausedRing);
  L.pausedW = 0;
  L.genT = 0;          // boot generation sequence plays on load (state starts 'starting')
  L.prevState = 'starting';
  L.tintCur = new THREE.Color(0xffffff); // damped state tint for cages/nodes
  L.tintTgt = new THREE.Color(0xffffff);

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

/** Re-apply palette tokens live (Wave 5, tier switch without a restart). */
export function applySagePalette(L, pal) {
  if (!L || !pal || !L.nebulaMat) return;
  const u = L.nebulaMat.uniforms;
  u.cLime.value.set(pal.haze_lime);
  u.cTeal.value.set(pal.haze_teal);
  u.cBlue.value.set(pal.haze_blue);
  u.cMagenta.value.set(pal.haze_magenta);
  L.ringBackMat.uniforms.uTint.value.set(pal.ring_color);
  L.ringFrontMat.uniforms.uTint.value.set(pal.ring_color);
  const pr = pal.private_ring || pal.accent;   // semantic teal — same in every tier
  L.privateMat.uniforms.uTint.value.set(pr);
  L.privateMat2.uniforms.uTint.value.set(pr);
}

// --- Pose lock (test hook, W2.1) --------------------------------------------
// The orb animates continuously (a full polyhedron turn takes ~40 s), so two
// screenshots of the SAME state taken seconds apart differ by 5-8/255 purely
// from rotation — that noise is larger than several real state differences and
// makes any pixel-diff gate meaningless. Locking puts every layer back on a
// canonical pose and pins the weights to their targets, so a captured frame is
// a pure function of (state, mode, amplitude). Harness-only: called via
// window.__orbLockPose() from CDP; never used by the production path.
export function lockSageCore(L, state, mode, opts = {}) {
  const tgt = (mode === 'paused') ? S.paused : (S[state] || S.idle);
  L.w = Object.assign({}, tgt);
  L.prevState = state;
  L.genT = state === 'starting' ? (opts.genMs === undefined ? 2000 : opts.genMs) : 99999;
  L.privateW = (mode === 'private' || state === 'private_overlay') ? 1 : 0;
  L.pausedW = (mode === 'paused') ? 1 : 0;
  L.ampS = opts.amp || 0;
  if (opts.tint !== undefined) { L.tintTgt.setHex(opts.tint); L.tintCur.setHex(opts.tint); }
  // canonical t=0 pose for every accumulated transform
  L.nebula.rotation.z = 0;
  L.speed.rotation.set(0, 0, 0);
  L.poly.rotation.set(0.30, 0, 0);
  L.nodes.rotation.set(0.30, 0, 0);
  if (L.cage) L.cage.rotation.set(0.30, 0, 0);
  L.ringBack.rotation.set(1.02, -0.10, 0);
  L.ringFront.rotation.set(1.02, -0.10, 0);
  L.privateRing.rotation.set(0.12, 0.06, 0);
  L.privateRing2.rotation.set(0.12, 0.06, 0);
  L.pausedRing.rotation.set(-0.16, 0.10, 0);
  L.polyMat.uniforms.uDrop.value = state === 'reconnecting' ? 0.42 : 0;
  return L;
}

// --- Per-frame update -------------------------------------------------------
// ctx = { t (s), dt (ms), state, amp (0..1), coreU (core material uniforms) }
export function updateSageCore(L, ctx) {
  const t = ctx.t, dt = Math.min(Math.max(ctx.dt, 1), 100), state = ctx.state;
  // ctx.lock (test pose-lock): damping still runs so uniforms converge to
  // their targets, but every accumulated transform is frozen.
  const spinDt = ctx.lock ? 0 : dt;
  // MODE override (INTERFACES §e): `paused` is not a state — it fully takes
  // over the base look (spec §3: desaturated grey, ~10% spin, no rays).
  // `private` is a pure overlay: the base state keeps rendering untouched.
  const tgt = (ctx.mode === 'paused') ? S.paused : (S[state] || FALLBACK);

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

  // --- STARTING build sequence (§1): the wireframe builds edge-by-edge from
  // the core outward with an EASE-IN-OUT on build PROGRESS (no hard stop),
  // while the physical spin-down (renderer.js stepSpin) decays underneath it —
  // the two overlap instead of fighting. The build clock only advances while
  // unlocked and only while `starting`; core brightness follows genSun, so the
  // sun ramps smoothly instead of popping on.
  if (state !== L.prevState) {
    if (state === 'starting') L.genT = 0;
    L.prevState = state;
  }
  if (!ctx.lock && L.genT >= 0 && state === 'starting') L.genT = Math.min(L.genT + dt, 9000);
  const gt = (state === 'starting' && L.genT >= 0) ? L.genT : 99999;
  const easeInOut3 = (x) => {
    const c = Math.min(Math.max(x, 0), 1);
    return c < 0.5 ? 4 * c * c * c : 1 - Math.pow(-2 * c + 2, 3) / 2;
  };
  const genOuter = easeInOut3(gt / 1400);
  const genInner = easeInOut3((gt - 900) / 1200);
  const genSun = easeInOut3((gt - 1700) / 900);
  const errOn = state === 'error' ? 1 : 0; // error: white cages, CRANKED glow

  // --- glide lag: solar-system inertia (sun leads; layers trail by factor) ---
  const gx = ctx.glide ? ctx.glide.x : 0;
  const gy = ctx.glide ? ctx.glide.y : 0;
  const gb = ctx.glide ? ctx.glide.blur : 0;
  L.nebula.position.x = -gx * 0.5;                       // background barely lags
  L.nebula.position.y = -gy * 0.5;
  L.speed.position.set(-gx * 1.6, -gy * 1.6, 0);         // rays trail + stretch (blur streak)
  L.poly.position.set(-gx * 1.15, -gy * 1.15, 0);        // outer cage
  L.nodes.position.copy(L.poly.position);
  if (L.cage) L.cage.position.copy(L.poly.position);     // inner cage rides with it
  L.ringBack.position.set(-gx * 1.4, -gy * 1.4, -0.24);
  L.ringFront.position.set(-gx * 1.4, -gy * 1.4, 0.24);
  L.privateRing.position.set(-gx * 1.45, -gy * 1.45, 0);
  L.privateRing2.position.set(-gx * 1.45, -gy * 1.45, 0);
  L.pausedRing.position.set(-gx * 1.45, -gy * 1.45, 0);
  L.spark.position.set(-gx * 2.0, -gy * 2.0, 0);         // sparkles lag the most // absolute speed boost: VISIBLE finishing spin

  // 1) nebula
  L.nebulaMat.uniforms.uTime.value = t;
  L.nebulaMat.uniforms.uOpacity.value = w.nebula;
  L.nebula.rotation.z += 0.00015 * spinDt; // slow swirl so the haze is visibly alive

  // 3) speed lines — listening: rays lengthen (ripple handled by shimmer)
  L.speedMat.uniforms.uTime.value = t;
  L.speedMat.uniforms.uAlpha.value = w.speed;
  L.speedMat.uniforms.uLength.value = 1 + listening * L.ampS * 0.55 + gb * 2.0; // rays stretch hard while gliding (blur bump v2)

  // 4) polyhedron + nodes — slow spin, edge pulses; listening: nodes brighten
  L.polyMat.uniforms.uTime.value = t;
  L.polyMat.uniforms.uAlpha.value = w.poly * (0.9 + errOn * 0.7); // error: crank the WHITE line glow
  L.polyMat.uniforms.uPulse.value = w.poly * (1 + errOn * 1.2);   // hotter traveling light pulses
  // reconnecting (spec §3): flickering fraction of wireframe edges goes missing
  const dropTgt = state === 'reconnecting'
    ? 0.3 + 0.18 * (0.5 + 0.5 * Math.sin(t * 7.3))
    : 0;
  L.polyMat.uniforms.uDrop.value = damp(L.polyMat.uniforms.uDrop.value || 0, dropTgt, TAU, dt);
  // inner cage rides the same look but has its own weight (§3.3: fewer lines
  // while thinking — it is the doubled-up cage that reads as "tangled yarn")
  L.cageMat.uniforms.uTime.value = t;
  L.cageMat.uniforms.uPulse.value = w.poly * (1 + errOn * 1.2);
  L.cageMat.uniforms.uDrop.value = L.polyMat.uniforms.uDrop.value;
  L.cageMat.uniforms.uAlpha.value = w.poly * w.cage * (0.9 + errOn * 0.7);
  L.cageMat.uniforms.uTint.value = L.polyMat.uniforms.uTint.value;

  // --- per-state cage SHAPE: project onto the target solid, then lerp ------
  if (ctx.shape && ctx.shape !== L.cageShape) {
    L.cageShape = ctx.shape;
    L.cageFrom.set(L.polyGeo.attributes.position.array);
    L.nodeFrom.set(L.nodeGeo.attributes.position.array);
    projectShape(L.polyBase, ctx.shape, L.cageTo);
    projectShape(L.nodeBase, ctx.shape, L.nodeTo);
    L.cageMs = ctx.lock ? CAGE_MORPH_MS : 0;   // pose-lock snaps to the target
    L.cageActive = true;
  }
  if (L.cageActive) {
    L.cageMs += ctx.lock ? CAGE_MORPH_MS : dt;
    const k = easeInOut3(Math.min(1, L.cageMs / CAGE_MORPH_MS));
    const pa = L.polyGeo.attributes.position;
    for (let i = 0; i < pa.array.length; i++) {
      pa.array[i] = L.cageFrom[i] + (L.cageTo[i] - L.cageFrom[i]) * k;
    }
    pa.needsUpdate = true;
    const na = L.nodeGeo.attributes.position;
    for (let i = 0; i < na.array.length; i++) {
      na.array[i] = L.nodeFrom[i] + (L.nodeTo[i] - L.nodeFrom[i]) * k;
    }
    na.needsUpdate = true;
    if (k >= 1) L.cageActive = false;
  }
  // state tint damped onto the cages + node dots (error = red cages/nodes)
  if (ctx.tint !== undefined) {
    L.tintTgt.setHex(state === 'error' ? 0xffffff : ctx.tint); // error: WHITE cages (red sun behind for contrast)
    L.tintCur.lerp(L.tintTgt, 1 - Math.exp(-dt / TAU));
    L.polyMat.uniforms.uTint.value.copy(L.tintCur);
    L.nodeMat.uniforms.uTint.value.copy(L.tintCur);
  }
  // Outer cage follows the breathing to keep the gap ~constant (user), but is
  // CAPPED so neither layer ever grows too big (max radius ~1.32 world units).
  const outerS = Math.min(1.12, 1 + 0.45 * ((ctx.ballScale || 1) - 1));
  L.poly.scale.setScalar(outerS * genOuter);
  if (L.nodes) L.nodes.scale.setScalar(outerS * genOuter);
  L.poly.rotation.y += w.spin * spinDt * L.dir.polyY;
  L.poly.rotation.x += w.spin * spinDt * 0.5 * L.dir.polyX;
  if (L.cage) {
    L.cage.rotation.y += w.spin * spinDt * L.dir.cageY * 1.7;
    L.cage.rotation.x += w.spin * spinDt * 0.7 * L.dir.cageX;
    if (ctx.ballScale) L.cage.scale.setScalar(0.56 * ctx.ballScale * genInner); // breathes WITH the ball + gen reveal
  }
  L.speed.rotation.y += w.spin * spinDt * 0.4 * L.dir.speedY;
  L.speed.rotation.x += w.spin * spinDt * 0.25 * L.dir.speedX;
  L.nodeMat.uniforms.uTime.value = t;
  L.nodeMat.uniforms.uAlpha.value = w.node;
  L.nodeMat.uniforms.uBoost.value = 1 + listening * L.ampS * 0.8;
  L.nodeMat.uniforms.uSize.value = 8.5 + errOn * 5 + (state === 'thinking' ? 2.0 : 0); // §3.3 thinking: bright node dots
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
  L.ringBack.rotation.z += 0.0004 * spinDt * L.dir.ringB;
  L.ringFront.rotation.z += 0.0003 * spinDt * L.dir.ringF;
  // MODE overlays follow `mode`, not `state` (INTERFACES §e) — the base state
  // keeps rendering underneath, so cloud-availability is always visible.
  const isPrivate = ctx.mode === 'private' || state === 'private_overlay';
  const isPaused = ctx.mode === 'paused';
  L.privateW = damp(L.privateW, isPrivate ? 1 : 0, TAU, dt);
  L.privateMat.uniforms.uTime.value = t;
  L.privateMat.uniforms.uAlpha.value = L.privateW * 0.9;
  L.privateMat2.uniforms.uTime.value = t;
  L.privateMat2.uniforms.uAlpha.value = L.privateW * 0.7;
  L.privateRing.visible = L.privateW > 0.003;
  L.privateRing2.visible = L.privateW > 0.003;
  L.privateRing.rotation.z += 0.0005 * spinDt * L.dir.ringF;
  L.privateRing2.rotation.z -= 0.0004 * spinDt * L.dir.ringB;
  L.pausedW = damp(L.pausedW, isPaused ? 1 : 0, TAU, dt);
  L.pausedMat.uniforms.uTime.value = t;
  L.pausedMat.uniforms.uAlpha.value = L.pausedW * 0.85;
  L.pausedRing.visible = L.pausedW > 0.003;
  L.pausedRing.rotation.z -= 0.0004 * spinDt * L.dir.ringB;

  // 7) sparkles
  L.sparkMat.uniforms.uTime.value = t;
  L.sparkMat.uniforms.uAlpha.value = w.spark;

  // 2) panes — slow drift with depth parallax + occasional flicker (prealloc'd)
  for (let i = 0; i < L.panes.length; i++) {
    const p = L.panes[i];
    const a = p.ang + t * p.speed;
    p.m.position.x = Math.cos(a) * p.rad - gx * 2.2;     // panes: heaviest trail (particles lag behind)
    p.m.position.y = Math.sin(a) * p.rad + Math.sin(t * 0.3 + p.phase) * 0.03 - gy * 2.2;
    let op = p.baseOp * (0.85 + 0.15 * Math.sin(t * (0.5 + i * 0.03) + p.phase));
    if (Math.sin(t * 0.9 + p.phase * 2.7) > 0.992) op *= 0.35; // rare flicker
    p.mat.opacity = op * (0.12 + w.nebula * 1.4);
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
    cu.uBright.value = damp(cu.uBright.value, w.bright * fx * Math.max(genSun, 0.001), TAU, dt);
    cu.uAmp.value = L.ampS;
    if (ctx.core && genSun < 1) {
      ctx.core.scale.setScalar((ctx.ballScale || 1) * (0.01 + 0.99 * genSun)); // sun GROWS from zero (stage 3)
    }
  }
}

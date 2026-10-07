// DATA RINGS - the prismatic thinking overlay (ORB_REBUILD_TASK spec §2.3).
// "Several concentric rings made of short segments/dashes in a prismatic
// spectrum, plus small tick rectangles and tiny colored LED-like dots, each
// ring rotating at its own speed and direction, with gaps. A thin ring of
// fine glyph-like micro-text bars is optional. They overlay the Sage Core
// wireframe." -> THINKING state (subtle under ACTING), hidden elsewhere.
// Everything procedural, built once, zero per-frame allocation.
import { polyVert, polyFrag } from './shaders/sage.glsl.js';

const DR_TAU = 400; // state blend (ms)
const DR_STATES = { thinking: 1.0, acting: 0.18 };

function damp(cur, tgt, tau, dt) {
  const a = 1 - Math.exp(-dt / tau);
  return cur + (tgt - cur) * a;
}

// Line-set builder on the shared SAGE line shader (depth glow + traveling
// pulse + uTint) — same pattern proven in Answer Mode.
function mkLine(THREE, root, segs, tintHex, pulse) {
  const n = segs.length / 6;
  const pos = new Float32Array(segs);
  const aT = new Float32Array(n * 2);
  const aId = new Float32Array(n * 2);
  const aSp = new Float32Array(n * 2);
  for (let e = 0; e < n; e++) {
    aT[e * 2] = 0; aT[e * 2 + 1] = 1;
    aId[e * 2] = aId[e * 2 + 1] = e;
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  geo.setAttribute('aEdgeT', new THREE.BufferAttribute(aT, 1));
  geo.setAttribute('aEdgeId', new THREE.BufferAttribute(aId, 1));
  geo.setAttribute('aSpoke', new THREE.BufferAttribute(aSp, 1));
  const mat = new THREE.ShaderMaterial({
    vertexShader: polyVert,
    fragmentShader: polyFrag,
    uniforms: {
      uTime: { value: 0 }, uAlpha: { value: 0 },
      uPulse: { value: pulse }, uTint: { value: new THREE.Color(tintHex) },
    },
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
  });
  const ls = new THREE.LineSegments(geo, mat);
  root.add(ls);
  return { ls, mat };
}

export function initDataRings(THREE, group) {
  const DR = { w: 0, root: new THREE.Group(), rings: [], barsDir: -0.00012 };
  group.add(DR.root);

  const N_RINGS = 6;
  for (let i = 0; i < N_RINGS; i++) {
    const hue = i / N_RINGS;                       // prismatic sweep
    const color = new THREE.Color().setHSL(hue, 0.95, 0.6);
    const r = 0.86 + i * 0.105;                    // 0.86 .. 1.385 (edge-safe)
    const segs = [];

    // dashes along the circle with deterministic gaps
    const DASH = 36;
    for (let d = 0; d < DASH; d++) {
      if (((d * 7 + i * 3) % 10) < 3) continue;     // ~30% skipped = gaps
      const a0 = (d / DASH) * Math.PI * 2;
      const a1 = a0 + ((Math.PI * 2) / DASH) * 0.55;
      segs.push(Math.cos(a0) * r, Math.sin(a0) * r, 0,
                Math.cos(a1) * r, Math.sin(a1) * r, 0);
    }
    // small tick rectangles (radial stubs) — sized for the 200-content zoom
    for (let k = 0; k < 12; k++) {
      const a = (k / 12) * Math.PI * 2 + 0.13;
      segs.push(Math.cos(a) * (r - 0.05), Math.sin(a) * (r - 0.05), 0,
                Math.cos(a) * (r + 0.05), Math.sin(a) * (r + 0.05), 0);
    }
    // tiny LED-like dots (small squares, ring hue) — visible at content=200
    for (let k = 0; k < 6; k++) {
      const a = (k / 6) * Math.PI * 2 + 0.42;
      const cx = Math.cos(a) * (r + 0.075), cy = Math.sin(a) * (r + 0.075);
      const s = 0.03;
      segs.push(cx - s, cy - s, 0, cx + s, cy - s, 0,
                cx + s, cy - s, 0, cx + s, cy + s, 0,
                cx + s, cy + s, 0, cx - s, cy + s, 0,
                cx - s, cy + s, 0, cx - s, cy - s, 0);
    }
    const line = mkLine(THREE, DR.root, segs, color.getHex(), 1.3);
    DR.rings.push({
      ls: line.ls, mat: line.mat,
      dir: (i % 2 ? -1 : 1) * (0.00016 + i * 0.00007), // own speed + direction
      base: 0.85 - i * 0.05,
    });
  }

  // optional thin ring of fine glyph-like micro-text bars (varied lengths)
  const bars = [];
  const BAR = 48;
  for (let b = 0; b < BAR; b++) {
    if (((b * 5 + 1) % 7) < 2) continue;
    const a = (b / BAR) * Math.PI * 2;
    const rr = 1.45;
    const halfLen = 0.017 + (((b * 13) % 5) / 5) * 0.028;
    const tx = -Math.sin(a), ty = Math.cos(a);   // tangent dir
    const rx = Math.cos(a), ry = Math.sin(a);    // radial dir
    const w2 = 0.015;
    const p0x = Math.cos(a) * rr - tx * halfLen, p0y = Math.sin(a) * rr - ty * halfLen;
    const p1x = Math.cos(a) * rr + tx * halfLen, p1y = Math.sin(a) * rr + ty * halfLen;
    bars.push(p0x - rx * w2, p0y - ry * w2, 0, p1x - rx * w2, p1y - ry * w2, 0,
              p1x - rx * w2, p1y - ry * w2, 0, p1x + rx * w2, p1y + ry * w2, 0,
              p1x + rx * w2, p1y + ry * w2, 0, p0x + rx * w2, p0y + ry * w2, 0,
              p0x + rx * w2, p0y + ry * w2, 0, p0x - rx * w2, p0y - ry * w2, 0);
  }
  DR.bars = mkLine(THREE, DR.root, bars, 0xbfd4ff, 0.8);
  return DR;
}

// --- Pose lock (test hook, W2.1) --------------------------------------------
export function lockDataRings(DR, state, opts = {}) {
  DR.w = DR_STATES[state] || 0;
  for (const R of DR.rings) R.ls.rotation.set(0, 0, 0);
  DR.bars.ls.rotation.set(0, 0, 0);
  DR.root.visible = DR.w > 0.005;
  return DR;
}

// ctx = { t (s), dt (ms), state, amp, glide: {x, y}, lock }
export function updateDataRings(DR, ctx) {
  const t = ctx.t, dt = Math.min(Math.max(ctx.dt, 1), 100), state = ctx.state;
  const spinDt = ctx.lock ? 0 : dt; // pose-lock: damping runs, transforms don't
  DR.w = damp(DR.w, DR_STATES[state] || 0, DR_TAU, dt);
  const gx = ctx.glide ? ctx.glide.x : 0;
  const gy = ctx.glide ? ctx.glide.y : 0;
  DR.root.position.set(-gx * 1.25, -gy * 1.25, 0);
  DR.root.visible = DR.w > 0.005;
  if (!DR.root.visible) return;

  const boost = 1 + (ctx.amp || 0) * 0.4;         // thinking brightness breathes
  for (const R of DR.rings) {
    R.ls.rotation.z += R.dir * (0.5 + 0.5 * DR.w) * spinDt; // own speed + direction
    R.mat.uniforms.uTime.value = t;
    R.mat.uniforms.uAlpha.value = R.base * DR.w * boost;
  }
  DR.bars.ls.rotation.z += DR.barsDir * spinDt;
  DR.bars.mat.uniforms.uTime.value = t;
  DR.bars.mat.uniforms.uAlpha.value = 0.8 * DR.w * boost;
}

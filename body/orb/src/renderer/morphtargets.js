// Lattice morph targets — PURE math, no THREE, no DOM.
//
// Extracted from renderer.js (Wave 4) so the invariants that the pose-locked
// screenshots could NOT catch are enforced by a plain Node test:
//
//   * every shape must produce EXACTLY the same vertex count. BUGS-WAVE2 Bug C
//     was an octagram target of 144 floats against 180 for everything else;
//     updateMorph lerps only Math.min(from, to), so indices 144-179 were never
//     written again and the lattice wedged after any interrupted octagram
//     morph. A locked screenshot always looked correct (see docs/status/orb.md
//     Wave-3 handoff) — this file exists so a plain `npm test` catches it.
//
// Importable from Node (src/renderer/package.json declares "type":"module")
// and from the browser alike.
export const BASE_VERTEX_COUNT = 60;
export const LATTICE_DEPTH = 0.20;   // world units of z (keeps the lattice off-plane)

export function circlePoints(n) {
  const pts = [];
  for (let i = 0; i < n; i++) {
    const a = (i / n) * Math.PI * 2;
    pts.push(Math.cos(a), Math.sin(a), 0);
  }
  return new Float32Array(pts);
}

export function polygonPoints(nSides, n, radius = 1) {
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

export function octagramPoints(n) {
  // Sample ALONG the star outline so the count always equals `n` — the old
  // version emitted one point per star vertex (48), which is what wedged the
  // morph. 8 outer + 8 inner vertices = V segments.
  const pts = [];
  const r1 = 1.0, r2 = 0.4;
  const V = 16;
  for (let i = 0; i < n; i++) {
    const t = (i / n) * V;
    const k = Math.floor(t);
    const f = t - k;
    const k0 = k % V, k1 = (k + 1) % V;
    const a0 = (k0 / V) * Math.PI * 2, a1 = (k1 / V) * Math.PI * 2;
    const r0 = k0 % 2 === 0 ? r1 : r2;
    const rB = k1 % 2 === 0 ? r1 : r2;
    const x0 = Math.cos(a0) * r0, y0 = Math.sin(a0) * r0;
    const x1 = Math.cos(a1) * rB, y1 = Math.sin(a1) * rB;
    pts.push(x0 + (x1 - x0) * f, y0 + (y1 - y0) * f, 0);
  }
  return new Float32Array(pts);
}

/** PROTOCOL §8 / config orb.shape_map values, plus 'circle' = the plain ball. */
export const MORPH_SHAPES = ['circle', 'triangle', 'square', 'pentagon', 'hexagon', 'octagram'];

export function makeMorphTarget(name) {
  let pts;
  if (name === 'octagram') pts = octagramPoints(BASE_VERTEX_COUNT);
  else if (name === 'triangle') pts = polygonPoints(3, BASE_VERTEX_COUNT);
  else if (name === 'square') pts = polygonPoints(4, BASE_VERTEX_COUNT);
  else if (name === 'pentagon') pts = polygonPoints(5, BASE_VERTEX_COUNT);
  else if (name === 'hexagon') pts = polygonPoints(6, BASE_VERTEX_COUNT);
  else pts = circlePoints(BASE_VERTEX_COUNT);
  // "nothing should feel 2d": bend the flat card into a shallow two-wave lens.
  const n = pts.length / 3;
  for (let i = 0; i < n; i++) {
    pts[i * 3 + 2] = Math.sin((i / n) * Math.PI * 2 * 2) * LATTICE_DEPTH;
  }
  return pts;
}

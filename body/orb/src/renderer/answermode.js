// ============================================================================
// ANSWER MODE - the gold magic-circle look (ORB_REBUILD_TASK spec §2.2).
// Full while SPEAKING; quiet version (diamond frame + one slow glyph ring)
// while ACTING. Everything procedural, textures drawn ONCE at startup,
// zero per-frame allocation (uniforms + transforms only).
// Anime rules (appendix item 11): flat additive glow, symbolic, crisp.
// ============================================================================
import { polyVert, polyFrag } from './shaders/sage.glsl.js';
import { glyphVert, glyphFrag, streakVert, streakFrag } from './shaders/answer.glsl.js';

const AM_TAU = 400; // state blend (ms)
const AM_STATES = {
  speaking: { full: 1, quiet: 0 },
  acting: { full: 0, quiet: 1 },
};

function damp(cur, tgt, tau, dt) {
  const a = 1 - Math.exp(-dt / tau);
  return cur + (tgt - cur) * a;
}
function mulberry32(a) {
  return function () {
    a |= 0; a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// --- rune atlas: INVENTED angular script (seeded strokes + quarter arcs on a
// grid). Drawn ONCE. 24 cells x 3 rows, 64px cells.
function makeGlyphAtlas(THREE) {
  const COLS = 40, ROWS = 3, CELL = 48;
  const c = document.createElement('canvas');
  c.width = COLS * CELL;
  c.height = ROWS * CELL;
  const g = c.getContext('2d');
  g.clearRect(0, 0, c.width, c.height);
  g.strokeStyle = 'rgba(255,255,255,1)';
  g.lineWidth = 5;
  g.lineCap = 'square';
  g.lineJoin = 'miter';
  const rnd = mulberry32(0x52415048); // "RAPH"
  for (let row = 0; row < ROWS; row++) {
    for (let col = 0; col < COLS; col++) {
      // WIDE-SHORT drawing box (52x24) — glyphs must lie along the ring
      // (user: runes were "standing up"; a wide long-axis reads laid-down)
      // re-proportioned for 40 cells/ring: box ~26x32 matches the visible
      // glyph aspect on the tube (arc ~8.5px wide x tube-height ~13px)
      const ox = col * CELL + 11, oy = row * CELL + 8;
      const stepX = (CELL - 22) / 2;   // 13
      const stepY = (CELL - 16) / 2;   // 16
      const P = (ix, iy) => [ox + ix * stepX, oy + iy * stepY];
      const strokes = 2 + Math.floor(rnd() * 3);
      for (let s = 0; s < strokes; s++) {
        if (rnd() < 0.42) {
          // quarter arc (arcane curve), stretched across the width
          const cx = Math.floor(rnd() * 3), cy = Math.floor(rnd() * 2);
          const a0 = Math.floor(rnd() * 4) * (Math.PI / 2);
          const dir = rnd() < 0.5 ? 1 : -1;
          g.beginPath();
          g.ellipse(ox + cx * (stepX / 2), oy + cy * stepY, stepX * 0.4, stepY * 0.8, 0, a0, a0 + dir * Math.PI / 2);
          g.stroke();
        } else {
          // straight segment, HORIZONTAL-biased (long axis along the ring)
          let ax = Math.floor(rnd() * 3), ay = Math.floor(rnd() * 2);
          let bx, by;
          if (rnd() < 0.68) { by = ay; bx = (ax + 1 + Math.floor(rnd() * 2)) % 3; }
          else { bx = ax; by = Math.floor(rnd() * 2); }
          if (ax === bx && ay === by) bx = (bx + 1) % 3;
          const a = P(ax, ay), b = P(bx, by);
          g.beginPath(); g.moveTo(a[0], a[1]); g.lineTo(b[0], b[1]); g.stroke();
        }
      }
      if (rnd() < 0.35) { // HORIZONTAL accent tick (not vertical!)
        const a = P(0, 0), b = P(2, 0);
        g.beginPath(); g.moveTo(a[0], a[1]); g.lineTo(b[0], b[1]); g.stroke();
      }
    }
  }
  const tex = new THREE.CanvasTexture(c);
  tex.minFilter = THREE.LinearFilter;
  tex.magFilter = THREE.LinearFilter;
  tex.generateMipmaps = false;
  return tex;
}

function makeBokehTexture(THREE, hex) {
  const c = document.createElement('canvas');
  c.width = c.height = 128;
  const g = c.getContext('2d');
  const grd = g.createRadialGradient(64, 64, 0, 64, 64, 64);
  grd.addColorStop(0, hex + 'cc');
  grd.addColorStop(0.5, hex + '44');
  grd.addColorStop(1, hex + '00');
  g.fillStyle = grd;
  g.fillRect(0, 0, 128, 128);
  const t = new THREE.CanvasTexture(c);
  t.minFilter = THREE.LinearFilter;
  t.generateMipmaps = false;
  return t;
}

function makePetalTexture(THREE) {
  const c = document.createElement('canvas');
  c.width = c.height = 64;
  const g = c.getContext('2d');
  g.strokeStyle = 'rgba(255,255,255,0.95)';
  g.lineWidth = 5;
  g.beginPath();
  g.moveTo(12, 40);
  g.bezierCurveTo(12, 10, 52, 10, 52, 32);
  g.bezierCurveTo(52, 54, 20, 58, 12, 40);
  g.stroke();
  const t = new THREE.CanvasTexture(c);
  t.minFilter = THREE.LinearFilter;
  t.generateMipmaps = false;
  return t;
}

// --- LineSegments builder reusing the SAGE line shaders (polyVert/polyFrag:
// depth-brightness + traveling edge pulse + uTint) — gold-tinted here.
function mkLineSet(THREE, AM, segs, tint, pulse) {
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
      uPulse: { value: pulse }, uTint: { value: new THREE.Color(tint) },
    },
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
  });
  const ls = new THREE.LineSegments(geo, mat);
  AM.root.add(ls);
  return { ls, mat };
}

export function initAnswerMode(THREE, group, pal) {
  const glyph0 = (pal && pal.glyph_color) || '#FFB000';
  const AM = { wFull: 0, wQuiet: 0, ampS: 0, root: new THREE.Group() };
  group.add(AM.root);

  const atlas = makeGlyphAtlas(THREE);

  // --- 1) GLYPH RINGS x3 — TILTED BANDS on precessing pivots (user: flat
  // coplanar rings looked weird; bands must WRAP the sun/cage in 3D — tilt
  // makes them pass in front of AND behind the core, depth-tested).
  // Radii inside the edge-mask safe zone (world r < ~1.39).
  const GOLD_TINTS = [glyph0, 0xff9a1f, 0xffe08a]; // spec §2.2 palette, ring0 = theme token
  const ringDefs = [
    { r: 0.79, tube: 0.085, row: 0, op: 0.85, dir: 0.00042, tx: 1.05, ty: 0.0 }, // wraps across the sun's face
    { r: 1.03, tube: 0.085, row: 1, op: 0.70, dir: -0.00031, tx: 0.50, ty: 0.30 },
    { r: 1.23, tube: 0.07, row: 2, op: 0.55, dir: 0.00024, tx: 0.85, ty: -0.25 },
  ];
  AM.rings = [];
  for (const d of ringDefs) {
    const glyphMat = new THREE.ShaderMaterial({
      vertexShader: glyphVert, fragmentShader: glyphFrag,
      uniforms: {
        uAtlas: { value: atlas },
        // §3.4 saturated gold palette: #FFB000 / #FF9A1F / highlight #FFE08A
        uAlpha: { value: 0 },
        uTint: { value: new THREE.Color(GOLD_TINTS[d.row % GOLD_TINTS.length]) },
        uCellX: { value: 40 }, uRow: { value: d.row }, uRows: { value: 3 },
      },
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    });
    // the RING itself: a real torus tube the runes WRAP around — the tube is
    // TRANSPARENT (user: only the glyphs visible); glow comes from the shader's
    // stroke halo, not from any solid annulus.
    const glyph = new THREE.Mesh(new THREE.TorusGeometry(d.r, d.tube, 24, 128), glyphMat);
    const band = new THREE.Group();      // the tilted band plane
    band.rotation.set(d.tx, d.ty, 0);
    band.add(glyph);
    const pivot = new THREE.Group();     // precession axis (orbital motion)
    pivot.add(band);
    AM.root.add(pivot);
    AM.rings.push({ pivot, band, glyphMat, dir: d.dir, base: d.op, tx: d.tx, ty: d.ty });
  }

  // --- 2) DIAMOND FRAME: 3 nested diamonds + mirrored right-angle circuit
  // traces + vertex glyph-clusters (tiny circles + spokes) + center squares.
  const segs = [];
  for (const r of [0.55, 0.72, 0.88]) {
    const v = [[0, r], [r, 0], [0, -r], [-r, 0]];
    for (let i = 0; i < 4; i++) {
      const a = v[i], b = v[(i + 1) % 4];
      segs.push(a[0], a[1], 0, b[0], b[1], 0);
    }
  }
  const rnd = mulberry32(0x444941); // circuit seed
  for (let c = 0; c < 7; c++) {
    let x = 0.12 + rnd() * 0.22, y = 0.12 + rnd() * 0.22;
    const pts = [[x, y]];
    const hops = 3 + Math.floor(rnd() * 3);
    for (let hh = 0; hh < hops; hh++) {
      if (rnd() < 0.5) x += 0.07 + rnd() * 0.11;
      else y += 0.07 + rnd() * 0.11;
      if (x > 0.97 || y > 0.97) break;
      pts.push([x, y]);
    }
    for (let s = 0; s < pts.length - 1; s++) {
      const [x0, y0] = pts[s], [x1, y1] = pts[s + 1];
      const mir = [
        [x0, y0, x1, y1], [-x0, y0, -x1, y1],
        [x0, -y0, x1, -y1], [-x0, -y0, -x1, -y1],
      ];
      for (const m of mir) segs.push(m[0], m[1], 0, m[2], m[3], 0);
    }
  }
  for (const [vx, vy] of [[0, 0.88], [0.88, 0], [0, -0.88], [-0.88, 0]]) {
    const SEG = 10, rr = 0.05;
    for (let i = 0; i < SEG; i++) {
      const a0 = (i / SEG) * Math.PI * 2, a1 = ((i + 1) / SEG) * Math.PI * 2;
      segs.push(vx + Math.cos(a0) * rr, vy + Math.sin(a0) * rr, 0,
                vx + Math.cos(a1) * rr, vy + Math.sin(a1) * rr, 0);
    }
    segs.push(vx, vy, 0, vx * 1.07, vy * 1.07, 0); // glyph marker dot spoke
  }
  AM.diamond = mkLineSet(THREE, AM, segs, 0xffb000, 1.2);

  const cSegs = [];
  for (const rot of [-0.32, 0.32]) {
    const s = 0.30;
    const v = [[-s, -s], [s, -s], [s, s], [-s, s]];
    for (let i = 0; i < 4; i++) {
      const a = v[i], b = v[(i + 1) % 4];
      cSegs.push(a[0], a[1], 0.01, b[0], b[1], 0.01);
    }
  }
  AM.centerOutline = mkLineSet(THREE, AM, cSegs, 0xffe08a, 0.9);
  AM.centerFill = [];
  for (const rot of [-0.32, 0.32]) {
    const fill = new THREE.Mesh(new THREE.PlaneGeometry(0.58, 0.58),
      new THREE.MeshBasicMaterial({
        color: 0xffb000, transparent: true, opacity: 0,
        side: THREE.DoubleSide, depthWrite: false, blending: THREE.AdditiveBlending,
      }));
    fill.rotation.z = rot;
    fill.position.z = 0.008;
    AM.root.add(fill);
    AM.centerFill.push(fill.material);
  }

  // --- 3) DODECAGON: bright 12-sided ring around the core + bloom underlay
  const dSegs = [];
  const R1 = 0.66, R0 = 0.58, NN = 12;
  const pt = (r, i) => [Math.cos((i / NN) * Math.PI * 2) * r, Math.sin((i / NN) * Math.PI * 2) * r];
  for (let i = 0; i < NN; i++) {
    const o0 = pt(R1, i), o1 = pt(R1, i + 1), i0 = pt(R0, i), i1 = pt(R0, i + 1);
    dSegs.push(o0[0], o0[1], 0, o1[0], o1[1], 0);
    dSegs.push(i0[0], i0[1], 0, i1[0], i1[1], 0);
  }
  AM.dodec = mkLineSet(THREE, AM, dSegs, 0xfff0c8, 1.8);
  // (dodecGlow annulus REMOVED — user: it read as "a golden disc rotating
  // around the sun"; the pale 12-gon LINE ring stays per spec §2.2.3)

  // --- 4) GOLD RADIAL STREAKS (denser than Sage's white rays; amp-reactive)
  const SR = 140;
  const sp = new Float32Array(SR * 6);
  const ss = new Float32Array(SR * 2);
  const ga = Math.PI * (3 - Math.sqrt(5));
  for (let i = 0; i < SR; i++) {
    const dy = 1 - (i / (SR - 1)) * 2;
    const rr = Math.sqrt(Math.max(0, 1 - dy * dy));
    const th = ga * i;
    const dx = Math.cos(th) * rr, dz = Math.sin(th) * rr;
    const r0 = 0.74 + ((i * 13) % 7) / 7 * 0.1; // just outside the dodecagon
    const len = 0.15 + ((i * 29) % 11) / 11 * 0.34; // tips reach ~1.33 = inside the mask-safe zone (user: rays cut)
    sp[i * 6 + 0] = dx * r0; sp[i * 6 + 1] = dy * r0; sp[i * 6 + 2] = dz * r0;
    sp[i * 6 + 3] = dx * (r0 + len); sp[i * 6 + 4] = dy * (r0 + len); sp[i * 6 + 5] = dz * (r0 + len);
    ss[i * 2] = ss[i * 2 + 1] = ((i * 37) % 100) / 100;
  }
  const stGeo = new THREE.BufferGeometry();
  stGeo.setAttribute('position', new THREE.BufferAttribute(sp, 3));
  stGeo.setAttribute('aSeed', new THREE.BufferAttribute(ss, 1));
  AM.streakMat = new THREE.ShaderMaterial({
    vertexShader: streakVert, fragmentShader: streakFrag,
    uniforms: {
      uTime: { value: 0 }, uAlpha: { value: 0 },
      uTint: { value: new THREE.Color(0xffb000) },
    },
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
  });
  AM.streaks = new THREE.LineSegments(stGeo, AM.streakMat);
  AM.root.add(AM.streaks);

  // --- 5) THIN CONCENTRIC CIRCLES + TICK MARKS + DOTS
  const tSegs = [];
  const addCircle = (r, seed) => {
    const N2 = 72;
    for (let i = 0; i < N2; i++) {
      const a0 = (i / N2) * Math.PI * 2, a1 = ((i + 1) / N2) * Math.PI * 2;
      tSegs.push(Math.cos(a0) * r, Math.sin(a0) * r, 0, Math.cos(a1) * r, Math.sin(a1) * r, 0);
    }
  };
  addCircle(0.68); addCircle(0.93); addCircle(1.14);
  for (let i = 0; i < 36; i++) { // ticks on the 1.14 circle
    const a = (i / 36) * Math.PI * 2;
    const l = i % 3 === 0 ? 0.05 : 0.025;
    tSegs.push(Math.cos(a) * 1.14, Math.sin(a) * 1.14, 0,
               Math.cos(a) * (1.14 + l), Math.sin(a) * (1.14 + l), 0);
  }
  for (let i = 0; i < 12; i++) { // small dots on the 0.93 circle
    const a = (i / 12) * Math.PI * 2;
    const cx = Math.cos(a) * 0.93, cy = Math.sin(a) * 0.93;
    for (let k = 0; k < 6; k++) {
      const b0 = (k / 6) * Math.PI * 2, b1 = ((k + 1) / 6) * Math.PI * 2;
      tSegs.push(cx + Math.cos(b0) * 0.014, cy + Math.sin(b0) * 0.014, 0,
                 cx + Math.cos(b1) * 0.014, cy + Math.sin(b1) * 0.014, 0);
    }
  }
  AM.ticks = mkLineSet(THREE, AM, tSegs, 0xff9a1f, 0.5); // deep-orange, spec §2.2

  // --- 6) DRIFTING PETAL/FEATHER FLAKES (texture once)
  const petalTex = makePetalTexture(THREE);
  AM.flakes = [];
  for (let i = 0; i < 8; i++) {
    const m = new THREE.Mesh(new THREE.PlaneGeometry(1, 1),
      new THREE.MeshBasicMaterial({
        map: petalTex, transparent: true, opacity: 0,
        side: THREE.DoubleSide, depthWrite: false, blending: THREE.AdditiveBlending,
        color: 0xfff2d0,
      }));
    const s = 0.05 + ((i * 17) % 7) / 7 * 0.04;
    m.scale.set(s, s, 1);
    AM.root.add(m);
    AM.flakes.push({
      m, mat: m.material,
      rad: 0.5 + ((i * 23) % 9) / 9 * 0.75,
      ang: (i / 8) * Math.PI * 2,
      ang0: (i / 8) * Math.PI * 2,
      z: ((i * 11) % 7) / 7 * 0.5 - 0.25,
      spd: 0.00006 + ((i * 19) % 5) / 5 * 0.00008,
      ph: i * 1.3,
      rot: 0.0006 + ((i * 7) % 4) / 4 * 0.0009,
    });
  }

  // --- 7) SOFT BOKEH HAZE (teal / green / gold) — CA lives in the edge mask
  const bokehDefs = [
    ['#2dd4bf', 0.85, 0.055], ['#9ae06b', 0.7, 0.05],
    ['#ffd700', 0.9, 0.06], ['#2dd4bf', 0.55, 0.045],
  ];
  AM.bokeh = [];
  bokehDefs.forEach((d, i) => {
    const mat = new THREE.MeshBasicMaterial({
      map: makeBokehTexture(THREE, d[0]), transparent: true, opacity: 0,
      depthWrite: false, blending: THREE.AdditiveBlending,
    });
    const m = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), mat);
    m.scale.set(d[1], d[1], 1);
    AM.root.add(m);
    AM.bokeh.push({
      m, mat, base: d[2],
      rad: 0.55 + i * 0.24, ang: i * 1.7, ang0: i * 1.7, z: -0.3 + i * 0.18,
      spd: 0.00004 + i * 0.00001, ph: i * 2.1,
    });
  });

  return AM;
}

// --- Pose lock (test hook, W2.1) — canonical weights + canonical transforms ---
export function lockAnswerMode(AM, state, opts = {}) {
  const tgt = AM_STATES[state] || { full: 0, quiet: 0 };
  AM.wFull = tgt.full;
  AM.wQuiet = tgt.quiet;
  AM.ampS = opts.amp || 0;
  for (const R of AM.rings) { R.pivot.rotation.set(0, 0, 0); R.band.rotation.set(R.tx, R.ty, 0); }
  for (const fk of AM.flakes) { fk.ang = fk.ang0; fk.m.rotation.z = 0; }
  for (const bk of AM.bokeh) { bk.ang = bk.ang0; }
  AM.root.visible = Math.max(AM.wFull, AM.wQuiet) > 0.005;
  return AM;
}

/** Re-apply palette tokens live. Ring 0 carries the theme's glyph colour;
 *  rings 1-2 keep the ORB_REBUILD §2.2 golds in every tier. */
export function applyAnswerPalette(AM, pal) {
  if (!AM || !pal || !AM.rings || !AM.rings[0]) return;
  AM.rings[0].glyphMat.uniforms.uTint.value.set(pal.glyph_color);
}

// --- per-frame update -------------------------------------------------------
// ctx = { t (s), dt (ms), state, amp, glide: {x, y} }
export function updateAnswerMode(AM, ctx) {
  const t = ctx.t, dt = Math.min(Math.max(ctx.dt, 1), 100), state = ctx.state;
  const spinDt = ctx.lock ? 0 : dt; // pose-lock: damping runs, transforms don't
  const tgt = AM_STATES[state] || { full: 0, quiet: 0 };
  AM.wFull = damp(AM.wFull, tgt.full, AM_TAU, dt);
  AM.wQuiet = damp(AM.wQuiet, tgt.quiet, AM_TAU, dt);
  const F = AM.wFull, Q = AM.wQuiet;
  const on = Math.max(F, Q);

  // amplitude smoothing (fast attack / slow release, spec §6)
  const aT = ctx.amp || 0;
  AM.ampS = damp(AM.ampS, aT, aT > AM.ampS ? 30 : 150, dt);

  // glide lag (solar inertia like the Sage layers)
  const gx = ctx.glide ? ctx.glide.x : 0;
  const gy = ctx.glide ? ctx.glide.y : 0;
  AM.root.position.set(-gx * 1.2, -gy * 1.2, 0);
  AM.root.visible = on > 0.005;
  if (!AM.root.visible) return;

  // glyph rings: speaking = all 3 (counter-rotate); acting = ring0 only, slow
  for (let i = 0; i < AM.rings.length; i++) {
    const R = AM.rings[i];
    const a = (i === 0) ? F + Q * 0.4 : F;
    R.pivot.rotation.y += R.dir * 0.55 * spinDt;                // orbital precession = band WRAPS the sphere
    R.band.rotation.z += R.dir * (0.35 + 0.65 * F) * spinDt;    // glyphs travel along the tilted band
    R.glyphMat.uniforms.uAlpha.value = a * 1.1; // glyphs only (glow = shader stroke-halo)
  }

  // diamond frame + center squares: full in speaking, quiet signature in acting
  const dA = Math.max(F, Q * 0.5);
  AM.diamond.mat.uniforms.uTime.value = t;
  AM.diamond.mat.uniforms.uAlpha.value = dA * 0.95;
  AM.centerOutline.mat.uniforms.uTime.value = t;
  AM.centerOutline.mat.uniforms.uAlpha.value = dA * 0.85;
  for (const fm of AM.centerFill) fm.opacity = dA * 0.16;

  // dodecagon core ring
  const dodecA = F + Q * 0.25;
  AM.dodec.mat.uniforms.uTime.value = t;
  AM.dodec.mat.uniforms.uAlpha.value = dodecA;

  // gold streaks: length + brightness react to amplitude (spec §2.2.4/§3)
  AM.streakMat.uniforms.uTime.value = t;
  AM.streakMat.uniforms.uAlpha.value = F * (0.55 + AM.ampS * 0.75) + Q * 0.12;
  const stScale = 1 + AM.ampS * 0.45 * F;
  AM.streaks.scale.set(stScale, stScale, stScale);

  // ticks
  AM.ticks.mat.uniforms.uTime.value = t;
  AM.ticks.mat.uniforms.uAlpha.value = Math.max(F * 0.65, Q * 0.3);

  // flakes: slow drift + twinkle
  for (const fk of AM.flakes) {
    fk.ang += fk.spd * spinDt;
    fk.m.position.set(Math.cos(fk.ang) * fk.rad, Math.sin(fk.ang) * fk.rad * 0.85,
                      fk.z + Math.sin(t * 0.001 + fk.ph) * 0.1);
    fk.m.rotation.z += fk.rot * spinDt;
    fk.mat.opacity = on * 0.7 * (0.55 + 0.45 * Math.sin(t * 0.9 + fk.ph));
  }

  // bokeh haze
  for (const bk of AM.bokeh) {
    bk.ang += bk.spd * spinDt;
    bk.m.position.set(Math.cos(bk.ang) * bk.rad, Math.sin(bk.ang) * bk.rad * 0.9, bk.z);
    bk.mat.opacity = on * bk.base;
  }
}

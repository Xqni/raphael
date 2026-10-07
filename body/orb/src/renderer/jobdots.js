// JOBS DOTS — `jobs_active` -> orbiting dots (docs/PROTOCOL §8: cap display at
// 9). One small glowing bead per active job on an outer ring, count fading in
// and out so nothing pops. Built once; per-frame work is transforms only.
//
// Rendered OUTSIDE every other layer (radius 1.35 world = ~90% of
// content_px), so it reads as a constellation around the orb rather than as
// more of the wireframe.
const MAX_DOTS = 9;
const RING_R = 1.35;   // §3.6: outermost layer stays inside ~90% of content_px
const DOT_R = 0.085;   // core bead — legible at 160 px too (spec §3.6)
const HALO_R = 0.185;  // soft glow so a job-count change is a real pixel delta

export function initJobDots(THREE, group, pal) {
  const accent = (pal && pal.accent) || 0x9ff0ff;
  const halo = (pal && pal.haze_teal) || 0x2dd4bf;
  const J = { root: new THREE.Group(), dots: [], count: 0, vis: 0, jobs: 0 };
  const geo = new THREE.CircleGeometry(DOT_R, 16);
  const haloGeo = new THREE.CircleGeometry(HALO_R, 20);
  for (let i = 0; i < MAX_DOTS; i++) {
    const mat = new THREE.MeshBasicMaterial({
      color: accent, transparent: true, opacity: 0,
      depthWrite: false, blending: THREE.AdditiveBlending,
    });
    const haloMat = new THREE.MeshBasicMaterial({
      color: halo, transparent: true, opacity: 0,
      depthWrite: false, blending: THREE.AdditiveBlending,
    });
    const m = new THREE.Mesh(geo, mat);
    // NB: NOT called `halo` — that would shadow (and hit the TDZ of) the
    // palette token above; this broke initScene entirely when §5 landed.
    const haloMesh = new THREE.Mesh(haloGeo, haloMat);
    const a = (i / MAX_DOTS) * Math.PI * 2 - Math.PI / 2;
    const x = Math.cos(a) * RING_R, y = Math.sin(a) * RING_R;
    m.position.set(x, y, 0.05);
    haloMesh.position.set(x, y, 0.045);
    m.visible = false;
    haloMesh.visible = false;
    J.root.add(haloMesh);
    J.root.add(m);
    J.dots.push({ m, mat, halo: haloMesh, haloMat, a, phase: i * 0.7 });
  }
  group.add(J.root);
  return J;
}

export function updateJobDots(J, ctx) {
  const dt = Math.min(Math.max(ctx.dt, 1), 100);
  const want = Math.min(MAX_DOTS, Math.max(0, ctx.jobs | 0));
  J.jobs = want;
  // 220ms in / out: visible without popping (spec: no pops or flashes)
  const target = want > 0 ? 1 : 0;
  const a = 1 - Math.exp(-dt / 220);
  J.vis += (target - J.vis) * a;
  const t = ctx.t;
  const spin = ctx.lock ? 0 : dt;
  for (let i = 0; i < J.dots.length; i++) {
    const d = J.dots[i];
    const lit = i < want ? 1 : 0;
    const on = J.vis > 0.01 && lit === 1;
    d.m.visible = on;
    d.halo.visible = on;
    if (!on) continue;
    const ang = d.a + (ctx.lock ? 0 : t * 0.35);
    const x = Math.cos(ang) * RING_R, y = Math.sin(ang) * RING_R;
    d.m.position.set(x, y, 0.05);
    d.halo.position.set(x, y, 0.045);
    // twinkle so the beads read as alive, never as a static decal
    const tw = 0.7 + 0.3 * Math.sin(t * 3.1 + d.phase);
    d.mat.opacity = J.vis * 0.95 * tw;
    d.haloMat.opacity = J.vis * 0.30 * tw;
    const s = (0.9 + 0.2 * Math.sin(t * 4.2 + d.phase)) * (0.5 + 0.5 * J.vis);
    d.m.scale.set(s, s, 1);
    d.halo.scale.set(s, s, 1);
  }
  return J;
}

/** Pose lock (test hook): canonical position + full opacity. */
export function lockJobDots(J, jobs) {
  const want = Math.min(MAX_DOTS, Math.max(0, jobs | 0));
  J.jobs = want;
  J.vis = want > 0 ? 1 : 0;
  for (let i = 0; i < J.dots.length; i++) {
    const d = J.dots[i];
    const on = i < want;
    d.m.visible = on;
    d.halo.visible = on;
    const ang = d.a;
    const x = Math.cos(ang) * RING_R, y = Math.sin(ang) * RING_R;
    d.m.position.set(x, y, 0.05);
    d.halo.position.set(x, y, 0.045);
    d.mat.opacity = on ? 0.95 : 0;
    d.haloMat.opacity = on ? 0.30 : 0;
    d.m.scale.set(1, 1, 1);
    d.halo.scale.set(1, 1, 1);
  }
  return J;
}

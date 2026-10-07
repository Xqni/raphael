// JOBS DOTS — `jobs_active` -> orbiting beads (docs/PROTOCOL §8: cap display at
// 9), plus the Wave-5 PARALLEL-MINDS read on `job_event.parent`.
//
// Wave 5 (PROTOCOL §5, additive 2026-10-07): `job_event` now carries an
// optional `parent` (parallel-minds fan-out tag) and `kind`
// (chat|analysis|simulation|act). These are STYLING hints — they are never
// turned into an orb_state (§e untouched).
//
//   no parent info  -> one bead per job on a single tilted ring (unchanged)
//   parent present  -> FAN: each parent gets a wedge, its children sit on an
//                      inner ring inside the wedge, and a spoke links parent
//                      to child, so "N children of one mind" reads at a glance
//                      and two different parents read as two clusters.
//
// USER FEEDBACK (2026-10-06): beads must not be flat 2D discs — they are
// shaded SPHERES on a tilted orbit plane. Keep it that way.
const MAX_DOTS = 9;
const MAX_PARENTS = 4;
const RING_R = 1.35;    // outer ring: parent beads / flat layout (§3.6: <=90% of content_px)
const CHILD_R = 1.16;   // inner ring: children of a fan
const DOT_R = 0.085;
const HALO_R = 0.175;

// Sphere shading without a light: brightness follows how much of the normal
// faces the camera, so the silhouette darkens and the middle lights up.
const beadVert = `
  varying vec3 vN;
  varying vec3 vV;
  void main() {
    vN = normalize(normalMatrix * normal);
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    vV = normalize(-mv.xyz);
    gl_Position = projectionMatrix * mv;
  }
`;
const beadFrag = `
  precision mediump float;
  uniform vec3 uColor;
  uniform float uAlpha;
  varying vec3 vN;
  varying vec3 vV;
  void main() {
    float f = clamp(dot(normalize(vN), normalize(vV)), 0.0, 1.0);
    float shade = 0.30 + 0.90 * pow(f, 0.75);          // limb darkening = a ball
    vec3 c = mix(uColor, vec3(1.0), pow(f, 3.0) * 0.65); // hot centre
    float a = clamp(shade * uAlpha, 0.0, 1.0);
    gl_FragColor = vec4(c * a, a);                      // premultiplied
  }
`;

export function initJobDots(THREE, group, pal) {
  const accent = (pal && pal.accent) || 0x9ff0ff;
  const halo = (pal && pal.haze_teal) || 0x2dd4bf;
  const J = {
    root: new THREE.Group(), dots: [], parents: [], spokes: null,
    vis: 0, jobs: 0, fan: false, groups: 0,
  };
  // tilt the orbit plane: without it every bead sits in the screen plane and
  // the ring looks like a flat 2D circle instead of an orbit in depth
  J.root.rotation.set(0.10, 0.06, 0);

  const geo = new THREE.SphereGeometry(DOT_R, 16, 12);
  const haloGeo = new THREE.CircleGeometry(HALO_R, 20);
  const mkBead = (color, scale) => {
    const mat = new THREE.ShaderMaterial({
      uniforms: { uColor: { value: new THREE.Color(color) }, uAlpha: { value: 0 } },
      vertexShader: beadVert, fragmentShader: beadFrag,
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    });
    const m = new THREE.Mesh(geo, mat);
    m.scale.setScalar(scale);
    m.visible = false;
    return m;
  };

  for (let i = 0; i < MAX_DOTS; i++) {
    const mat = new THREE.ShaderMaterial({
      uniforms: { uColor: { value: new THREE.Color(accent) }, uAlpha: { value: 0 } },
      vertexShader: beadVert, fragmentShader: beadFrag,
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    });
    const haloMat = new THREE.MeshBasicMaterial({
      color: halo, transparent: true, opacity: 0,
      depthWrite: false, blending: THREE.AdditiveBlending,
    });
    const m = new THREE.Mesh(geo, mat);
    // NB: not called `halo` — that would shadow (and hit the TDZ of) the
    // palette token above; this broke initScene entirely when §5 landed.
    const haloMesh = new THREE.Mesh(haloGeo, haloMat);
    J.root.add(haloMesh);
    J.root.add(m);
    J.dots.push({
      m, mat, halo: haloMesh, haloMat, a: 0, radius: RING_R,
      phase: i * 0.7, visible: false,
    });
  }

  // parent markers (slightly larger, on the OUTER ring)
  for (let i = 0; i < MAX_PARENTS; i++) {
    const p = mkBead(0xffffff, 1.45);
    J.root.add(p);
    J.parents.push({ m: p, mat: p.material, a: 0, visible: false, phase: i * 1.9 });
  }

  // fan-out spokes: parent -> child (one LineSegments, drawRange per frame)
  const spokeGeo = new THREE.BufferGeometry();
  spokeGeo.setAttribute('position',
    new THREE.BufferAttribute(new Float32Array(MAX_DOTS * 2 * 3), 3));
  const spokeMat = new THREE.LineBasicMaterial({
    color: accent, transparent: true, opacity: 0,
    depthWrite: false, blending: THREE.AdditiveBlending,
  });
  J.spokes = new THREE.LineSegments(spokeGeo, spokeMat);
  J.spokes.visible = false;
  J.root.add(J.spokes);

  group.add(J.root);
  return J;
}

/**
 * Work out where every bead goes. Pure-ish (no DOM), so the fan layout can be
 * reasoned about and re-used by the pose lock.
 * @returns {{fan:boolean, groups:number}}
 */
function computeLayout(J, jobList, jobsActive) {
  // ORB_REBUILD §5: "Do not allocate per frame." The layout only depends on
  // (jobList identity, jobs_active) — the renderer REPLACES orbJobs on every
  // job_event rather than mutating it, so an identity compare is enough to skip
  // all of the Map/array work below on every frame but one.
  if (jobList === J._lastList && jobsActive === J._lastN && J._lastResult) {
    return J._lastResult;
  }
  // `orb_state.jobs_active` is AUTHORITATIVE for the COUNT (PROTOCOL §8);
  // job_event only supplies the fan-out STRUCTURE. Deriving the count from the
  // job table instead left stale beads on screen after jobs finished whenever
  // the table outlived the state.
  const n = Math.min(MAX_DOTS, Math.max(0, jobsActive | 0));
  J.jobs = n;
  const list = (Array.isArray(jobList) && jobList.length) ? jobList.slice(0, n) : null;

  // No parent information -> the original single evenly-spaced ring.
  const hasParent = !!list && list.some((j) => j && j.parent);
  if (!hasParent) {
    J.fan = false;
    J.groups = 0;
    for (let i = 0; i < J.dots.length; i++) {
      const d = J.dots[i];
      d.a = (i / Math.max(n, 1)) * Math.PI * 2 - Math.PI / 2;
      d.radius = RING_R;
      d.slot = i < n ? 'child' : null;
      d.group = 0;
    }
    for (const p of J.parents) p.slot = null;
    return finish(J, jobList, jobsActive, { fan: false, groups: 0 });
  }

  // Fan: group siblings by their `parent` tag, one wedge per parent.
  const groups = [];
  const index = new Map();
  for (let i = 0; i < n; i++) {
    const key = (list[i] && list[i].parent) || '__root';
    if (!index.has(key)) { index.set(key, groups.length); groups.push([]); }
    groups[index.get(key)].push(i);
  }
  const G = Math.min(groups.length, MAX_PARENTS);
  const wedge = (Math.PI * 2) / G;
  J.fan = true;
  J.groups = G;

  // clear
  for (const d of J.dots) d.slot = null;
  for (const p of J.parents) p.slot = null;

  let childIdx = 0;
  for (let g = 0; g < G; g++) {
    const members = groups[g];
    const centre = g * wedge + wedge / 2 - Math.PI / 2;
    const parent = J.parents[g];
    if (parent) { parent.slot = 'parent'; parent.a = centre; parent.visible = true; }
    // children spread across the wedge, kept inside it so clusters never merge
    const c = members.length;
    for (let k = 0; k < c; k++) {
      const i = members[k];
      const d = J.dots[childIdx < MAX_DOTS ? childIdx : -1];
      if (!d) break;
      const frac = c === 1 ? 0.5 : (k + 0.5) / c;
      d.a = centre + (frac - 0.5) * wedge * 0.78;
      d.radius = CHILD_R;
      d.slot = 'child';
      d.group = g;
      childIdx++;
    }
  }
  for (let i = childIdx; i < J.dots.length; i++) {
    J.dots[i].slot = null;
    J.dots[i].group = 0;
  }
  return finish(J, jobList, jobsActive, { fan: true, groups: G });
}

/** Record the memo so the next frame is a pure reference compare. */
function finish(J, jobList, jobsActive, result) {
  J._lastList = jobList;
  J._lastN = jobsActive;
  J._lastResult = result;
  return result;
}

/** Re-apply palette tokens live (beads + fan spokes). */
export function applyJobPalette(J, pal) {
  if (!J || !pal) return;
  for (const d of J.dots) {
    d.mat.uniforms.uColor.value.set(pal.accent);
    d.haloMat.color.set(pal.haze_teal);
  }
  J.spokes.material.color.set(pal.accent);
}

export function updateJobDots(J, ctx) {
  const dt = Math.min(Math.max(ctx.dt, 1), 100);
  const layout = computeLayout(J, ctx.jobList, ctx.jobs | 0);
  const target = J.jobs > 0 ? 1 : 0;
  const a = 1 - Math.exp(-dt / 220);       // 220ms in/out: visible without popping
  J.vis += (target - J.vis) * a;
  const t = ctx.t;
  const spin = ctx.lock ? 0 : t * 0.35;

  const sp = J.spokes.geometry.getAttribute('position');
  let spokeCount = 0;

  for (let i = 0; i < J.dots.length; i++) {
    const d = J.dots[i];
    const on = d.slot !== null && J.vis > 0.01;
    d.m.visible = on;
    d.halo.visible = on;
    if (!on) continue;
    const ang = d.a + spin;
    const x = Math.cos(ang) * d.radius, y = Math.sin(ang) * d.radius;
    d.m.position.set(x, y, 0.05);
    d.halo.position.set(x, y, 0.045);
    const tw = 0.7 + 0.3 * Math.sin(t * 3.1 + d.phase);
    d.mat.uniforms.uAlpha.value = J.vis * 0.95 * tw;
    d.haloMat.opacity = J.vis * 0.30 * tw;
    const s = (0.9 + 0.2 * Math.sin(t * 4.2 + d.phase)) * (0.5 + 0.5 * J.vis);
    d.m.scale.set(s, s, s);
    d.halo.scale.set(s, s, 1);

    // spoke: parent centre -> this child (fan-out read)
    if (layout.fan && d.slot === 'child') {
      const parent = J.parents[d.group];
      if (parent && parent.slot) {
        const pa = parent.a + spin;
        const o = spokeCount * 6;
        sp.array[o + 0] = Math.cos(pa) * RING_R;
        sp.array[o + 1] = Math.sin(pa) * RING_R;
        sp.array[o + 2] = 0.05;
        sp.array[o + 3] = x;
        sp.array[o + 4] = y;
        sp.array[o + 5] = 0.05;
        spokeCount++;
      }
    }
  }

  // parent markers
  for (const p of J.parents) {
    const on = p.slot && J.vis > 0.01;
    p.m.visible = !!on;
    if (!on) continue;
    const ang = p.a + spin;
    p.m.position.set(Math.cos(ang) * RING_R, Math.sin(ang) * RING_R, 0.05);
    const tw = 0.75 + 0.25 * Math.sin(t * 2.4 + p.phase);
    p.mat.uniforms.uAlpha.value = J.vis * 0.95 * tw;
  }

  // spokes
  sp.needsUpdate = true;
  J.spokes.geometry.setDrawRange(0, spokeCount * 2);
  J.spokes.visible = spokeCount > 0;
  J.spokes.material.opacity = J.vis * 0.5;
  J.fan = layout.fan;
  return J;
}

/** Pose lock (test hook): canonical positions + full opacity. */
export function lockJobDots(J, jobs, jobList) {
  computeLayout(J, jobList, jobs);
  J.vis = J.jobs > 0 ? 1 : 0;
  const sp = J.spokes.geometry.getAttribute('position');
  let spokeCount = 0;
  for (let i = 0; i < J.dots.length; i++) {
    const d = J.dots[i];
    const on = d.slot !== null;
    d.m.visible = on;
    d.halo.visible = on;
    if (!on) continue;
    const x = Math.cos(d.a) * d.radius, y = Math.sin(d.a) * d.radius;
    d.m.position.set(x, y, 0.05);
    d.halo.position.set(x, y, 0.045);
    d.mat.uniforms.uAlpha.value = 0.95;
    d.haloMat.opacity = 0.30;
    d.m.scale.set(1, 1, 1);
    d.halo.scale.set(1, 1, 1);
    if (d.slot === 'child') {
      const parent = J.parents[d.group];
      if (parent && parent.slot) {
        const o = spokeCount * 6;
        sp.array[o + 0] = Math.cos(parent.a) * RING_R;
        sp.array[o + 1] = Math.sin(parent.a) * RING_R;
        sp.array[o + 2] = 0.05;
        sp.array[o + 3] = x; sp.array[o + 4] = y; sp.array[o + 5] = 0.05;
        spokeCount++;
      }
    }
  }
  for (const p of J.parents) {
    const on = !!p.slot;
    p.m.visible = on;
    if (on) p.m.position.set(Math.cos(p.a) * RING_R, Math.sin(p.a) * RING_R, 0.05);
    p.mat.uniforms.uAlpha.value = on ? 0.95 : 0;
  }
  sp.needsUpdate = true;
  J.spokes.geometry.setDrawRange(0, spokeCount * 2);
  J.spokes.visible = spokeCount > 0;
  J.spokes.material.opacity = 0.5;
  return J;
}

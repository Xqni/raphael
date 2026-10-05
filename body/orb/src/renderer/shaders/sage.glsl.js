// Sage Core shared shaders (spec §2.1.3/4/5/7) — ALL flat, unlit, additive:
// anime overlay art, not CGI (ORB_REBUILD_TASK appendix item 11).

// --- Radial hairlines / speed lines (LineSegments) -------------------------
export const speedVert = `
  attribute float aSeed;      // per-ray seed: varied brightness/shimmer
  varying float vSeed;
  void main() {
    vSeed = aSeed;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;
export const speedFrag = `
  precision mediump float;
  varying float vSeed;
  uniform float uTime;
  uniform float uAlpha;
  uniform float uLength;      // 0..1+ ripple factor (listening lengthens)
  void main() {
    float shimmer = 0.7 + 0.3 * sin(uTime * (1.2 + vSeed * 2.4) + vSeed * 40.0);
    float b = (0.25 + 0.75 * fract(vSeed * 7.31)) * shimmer * uAlpha * uLength;
    gl_FragColor = vec4(vec3(1.0) * b, b);   // white hairlines, premultiplied
  }
`;

// --- Wireframe polyhedron edges (LineSegments) -----------------------------
export const polyVert = `
  attribute float aEdgeT;     // 0..1 position along own edge
  attribute float aEdgeId;    // edge identity for hash
  attribute float aSpoke;     // 1.0 on short extra spokes
  varying float vEdgeT;
  varying float vEdgeId;
  varying float vSpoke;
  varying float vDepth;
  void main() {
    vEdgeT = aEdgeT; vEdgeId = aEdgeId; vSpoke = aSpoke;
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    vDepth = -mv.z;
    gl_Position = projectionMatrix * mv;
  }
`;
export const polyFrag = `
  precision mediump float;
  varying float vEdgeT;
  varying float vEdgeId;
  varying float vSpoke;
  varying float vDepth;
  uniform float uTime;
  uniform float uAlpha;
  uniform float uPulse;       // edge light-pulse intensity
  uniform vec3 uTint;         // state color (error = RED cages)
  uniform float uDrop;        // reconnecting: fraction of edges missing
  float h(float n) { return fract(sin(n) * 43758.5453); }
  void main() {
    // reconnecting (spec §3): some wireframe edges go missing (flicker)
    if (uDrop > 0.001 && h(vEdgeId * 3.1) < uDrop) discard;
    // depth-based brightness (near = brighter) — subtle, still graphic
    float depthB = clamp(1.35 - (vDepth - 2.4) * 0.45, 0.35, 1.0);
    // light traveling along the edge
    float pp = fract(uTime * 0.3 + h(vEdgeId));
    float pulse = exp(-pow((vEdgeT - pp) * 7.0, 2.0)) * uPulse;
    float spokeDim = mix(1.0, 0.55, vSpoke);
    float b = depthB * (0.55 + pulse) * uAlpha * spokeDim;
    gl_FragColor = vec4(uTint * b, b);        // state-tinted lines (uniform hairline)
  }
`;

// --- Node dots at vertices (Points, round via gl_PointCoord) ---------------
export const nodeFrag = `
  precision mediump float;
  varying float vDepth;
  uniform float uTime;
  uniform float uAlpha;
  uniform float uBoost;       // listening: node brightness reacts to amplitude
  uniform vec3 uTint;         // state color (error = RED nodes)
  float h(float n) { return fract(sin(n) * 43758.5453); }
  void main() {
    vec2 d = gl_PointCoord - 0.5;
    float disc = smoothstep(0.5, 0.12, length(d));
    float depthB = clamp(1.35 - (vDepth - 2.4) * 0.45, 0.4, 1.0);
    float tw = 0.85 + 0.15 * sin(uTime * 2.0 + vDepth * 9.0);
    float b = disc * depthB * tw * uAlpha * uBoost;
    gl_FragColor = vec4(uTint * b, b);
  }
`;
export const nodeVert = `
  uniform float uSize;
  varying float vDepth;
  void main() {
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    vDepth = -mv.z;
    gl_Position = projectionMatrix * mv;
    gl_PointSize = uSize * (3.0 / max(vDepth, 0.1));
  }
`;

// --- Orbit rings: faint gaps + thickness variation via angle (spec §2.1.5) --
export const ringVert = `
  varying vec2 vPos;
  void main() {
    vPos = position.xy;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;
export const ringFrag = `
  precision mediump float;
  varying vec2 vPos;
  uniform float uTime;
  uniform float uAlpha;
  uniform float uSeed;
  uniform vec3 uTint;
  void main() {
    float ang = atan(vPos.y, vPos.x);
    // faint gaps along the loop + thickness/brightness variation
    float gaps = 0.55 + 0.45 * sin(ang * 3.0 + uSeed * 6.28);
    float wiggle = 0.8 + 0.2 * sin(ang * 7.0 - uTime * 0.4 + uSeed);
    float b = gaps * wiggle * uAlpha;
    gl_FragColor = vec4(uTint * b, b);
  }
`;

// --- Sparkle dust (Points) --------------------------------------------------
export const sparkFrag = `
  precision mediump float;
  varying float vSeed;
  uniform float uTime;
  uniform float uAlpha;
  void main() {
    vec2 d = gl_PointCoord - 0.5;
    float disc = smoothstep(0.5, 0.0, length(d));
    float tw = 0.35 + 0.65 * pow(abs(sin(uTime * (0.7 + vSeed) + vSeed * 20.0)), 3.0);
    float b = disc * tw * uAlpha;
    gl_FragColor = vec4(vec3(1.0) * b, b);
  }
`;
export const sparkVert = `
  attribute float aSeed;
  uniform float uSize;
  varying float vSeed;
  void main() {
    vSeed = aSeed;
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    gl_Position = projectionMatrix * mv;
    gl_PointSize = uSize * (3.0 / max(-mv.z, 0.1));
  }
`;

// Thick white REVOLVING BAND (user ref): SOLID crisp white ring body (like
// the sun's solid ball) + a separate corona-style glow falling off outward —
// NOT fogged (user: no gaussian mush). Pairs with ringVert's vPos.
export const bandFrag = `
  precision mediump float;
  varying vec2 vPos;
  uniform float uR0;
  uniform float uR1;
  uniform float uAlpha;
  uniform vec3 uTint;
  void main() {
    float d = length(vPos);
    // solid ring body: near-hard edges (0.005 feather = AA only)
    float body = smoothstep(uR0 - 0.005, uR0 + 0.005, d)
               * (1.0 - smoothstep(uR1 - 0.005, uR1 + 0.005, d));
    // corona glow: bright at the band edge, exponential falloff OUTWARD
    // (and a matching inner halo) — the sun's glow, but for the ring
    float db = max(0.0, max(uR0 - d, d - uR1));
    float sg = max((uR1 - uR0) * 0.55, 0.02);
    float glow = exp(-db / sg) * 0.5;
    float a = clamp(body + glow * (1.0 - body), 0.0, 1.0) * uAlpha;
    gl_FragColor = vec4(uTint * a, a); // premultiplied, additive
  }
`;

// 3D RING (TorusGeometry) shaded like the sun: normal-based lit body +
// shine highlight + rim — real geometry, so it reads as a 3D ring, not a
// flat disc (user: "3d rings that shine like the SUN in the center").
export const bandVert3D = `
  varying vec3 vN;
  varying vec3 vV;
  void main() {
    vN = normalize(normalMatrix * normal);
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    vV = normalize(-mv.xyz);
    gl_Position = projectionMatrix * mv;
  }
`;
export const torusFrag = `
  precision mediump float;
  varying vec3 vN;
  varying vec3 vV;
  uniform float uAlpha;
  void main() {
    vec3 N = normalize(vN);
    vec3 V = normalize(vV);
    float facing = clamp(dot(N, V), 0.0, 1.0);
    vec3 L = normalize(vec3(-0.45, 0.55, 0.72));  // same fixed light as the sun
    float diff = clamp(dot(N, L), 0.0, 1.0);
    float body = 0.38 + 0.78 * pow(diff, 1.25);   // lit tube (sun-style)
    float hot  = pow(diff, 6.0) * 0.6;            // white-hot shine streak
    float rim  = pow(1.0 - facing, 2.6) * 0.5;    // glowing rim = dimension
    float a = clamp(body + hot + rim, 0.0, 1.2) * uAlpha;
    a = min(a, 1.0);
    gl_FragColor = vec4(vec3(1.0) * a, a);        // white, premultiplied
  }
`;

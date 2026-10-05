// ANSWER MODE shaders (spec §2.2) — gold magic-circle speaking look.
// Flat/anime rules apply (ORB_REBUILD_TASK appendix item 11): additive glow,
// symbolic graphic design, no volumetrics. All geometry is generated once;
// per-frame work = uniforms + mesh rotation only.

// Glyph shader for WRAPPED-ON-A-RING runes (user: "wrapped around a ring, not
// in a disc"): samples the atlas via the TORUS's own UVs — width follows the
// ring's circumference, height wraps AROUND THE TUBE (like engraving on a
// bracelet). A facing term shades the tube so it reads round, not flat.
export const glyphVert = `
  varying vec2 vUv;
  varying vec3 vN;
  varying vec3 vV;
  void main() {
    vUv = uv;
    vN = normalize(normalMatrix * normal);
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    vV = normalize(-mv.xyz);
    gl_Position = projectionMatrix * mv;
  }
`;
export const glyphFrag = `
  precision mediump float;
  varying vec2 vUv;
  varying vec3 vN;
  varying vec3 vV;
  uniform sampler2D uAtlas;
  uniform float uAlpha;
  uniform vec3 uTint;
  uniform float uCellX;   // cells along the ring
  uniform float uRow;     // atlas row for this ring (0..2)
  uniform float uRows;    // atlas rows (3)
  void main() {
    float cell = floor(vUv.x * uCellX);            // which rune around the ring
    float fr = fract(vUv.x * uCellX);              // position within the cell
    vec2 uv = vec2((cell + fr) / uCellX, (uRow + vUv.y) / uRows); // height wraps the tube
    float glyph = texture2D(uAtlas, uv).a;
    // stroke halo: soft glow around each rune WITHOUT any tube/disc body
    // (user: transparent torus, only glyphs visible)
    float halo = 0.0;
    halo += texture2D(uAtlas, uv + vec2( 0.006, 0.0)).a;
    halo += texture2D(uAtlas, uv + vec2(-0.006, 0.0)).a;
    halo += texture2D(uAtlas, uv + vec2(0.0,  0.012)).a;
    halo += texture2D(uAtlas, uv + vec2(0.0, -0.012)).a;
    halo *= 0.25;
    float facing = clamp(dot(normalize(vN), normalize(vV)), 0.0, 1.0);
    float shade = 0.62 + 0.38 * facing;            // cylindrical shading = round tube
    float a = (glyph + halo * 0.75) * uAlpha * shade;
    gl_FragColor = vec4(uTint * a, a);
  }
`;

// Gold radial streaks (spec §2.2.4): denser/brighter than Sage Core's white
// rays; length reacts to amplitude via mesh scale (see answermode.js).
export const streakVert = `
  attribute float aSeed;
  varying float vSeed;
  void main() {
    vSeed = aSeed;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;
export const streakFrag = `
  precision mediump float;
  varying float vSeed;
  uniform float uTime;
  uniform float uAlpha;
  uniform vec3 uTint;
  void main() {
    float shimmer = 0.7 + 0.3 * sin(uTime * (1.4 + vSeed * 2.6) + vSeed * 37.0);
    float b = (0.35 + 0.65 * fract(vSeed * 7.31)) * shimmer * uAlpha;
    gl_FragColor = vec4(uTint * b, b);
  }
`;

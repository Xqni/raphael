// ANSWER MODE shaders (spec §2.2) — gold magic-circle speaking look.
// Flat/anime rules apply (ORB_REBUILD_TASK appendix item 11): additive glow,
// symbolic graphic design, no volumetrics. All geometry is generated once;
// per-frame work = uniforms + mesh rotation only.

// Polar glyph-ring: samples the canvas rune atlas (drawn once at startup) in
// ring bands. Rotation happens by rotating the MESH (local coords stay fixed),
// so the shader only maps angle/radius -> atlas cell.
export const glyphVert = `
  varying vec2 vPos;
  void main() {
    vPos = position.xy;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;
export const glyphFrag = `
  precision mediump float;
  varying vec2 vPos;
  uniform sampler2D uAtlas;
  uniform float uR0;
  uniform float uR1;
  uniform float uAlpha;
  uniform vec3 uTint;
  uniform float uCellX;   // columns (e.g. 24)
  uniform float uRow;     // atlas row for this ring (0..2)
  uniform float uRows;    // total rows (3)
  void main() {
    float ang = atan(vPos.y, vPos.x);
    float u01 = (ang / 6.2831853) + 0.5;                       // 0..1 around
    float r01 = clamp((length(vPos) - uR0) / (uR1 - uR0), 0.0, 1.0);
    float cell = floor(u01 * uCellX);
    float cu = fract(u01 * uCellX);
    vec2 uv = vec2((cell + cu) / uCellX, (uRow + (1.0 - r01)) / uRows);
    float a = texture2D(uAtlas, uv).a * uAlpha;
    gl_FragColor = vec4(uTint * a, a);                        // premultiplied
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

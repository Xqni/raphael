// ============================================================================
// CHEAP MOTION BLUR (fidelity pass §2).
//
// One LOW-RESOLUTION post pass that smears the already-rendered scene
// TANGENTIALLY around the window centre — i.e. an angular/rotational blur,
// which is exactly what a spinning overlay needs. There is NO full-resolution
// multi-pass post chain: the existing edge-mask pass reads `tBlur` and mixes it
// with `tScene`, so the frame budget is
//
//     scene -> edgeRT (existing)   +   edgeRT -> blurRT (this, low-res only)
//
// Everything is blended in PREMULTIPLIED alpha: the shader only ever averages
// premultiplied RGBA, so a smear over a transparent region stays transparent
// (rgb and a decay together) — no dark box, halo or ghost outline on white,
// dark or busy wallpapers.
//
// Velocity gating lives in renderer.js: when the orb is calm the pass is not
// executed at all and `uBlur` stays 0, so idle costs exactly what it did
// before.
// ============================================================================

export const blurVert = `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = vec4(position.xy, 0.0, 1.0);
  }
`;

export const blurFrag = `
  precision mediump float;
  varying vec2 vUv;
  uniform sampler2D tScene;   // premultiplied RGBA, full resolution
  uniform float uAngle;       // tangential smear at the rim, radians
  uniform float uRadius;      // radius (0..1) where the smear reaches full size
  uniform float uTaps;        // 2..6 samples along the tangent

  const int MAX_TAPS = 6;

  void main() {
    vec2 d = vUv - 0.5;
    float r = length(d) * 2.0;                 // 0 at centre .. ~1.4 at corner
    float a0 = atan(d.y, d.x);
    // the rim travels further than the middle: scale the smear with radius
    float span = uAngle * smoothstep(0.0, max(uRadius, 0.05), r);
    float denom = max(uTaps - 1.0, 1.0);

    vec4 sum = vec4(0.0);
    float wsum = 0.0;
    for (int i = 0; i < MAX_TAPS; i++) {
      float fi = float(i);
      float k = fi / denom - 0.5;                    // -0.5 .. +0.5 for active taps
      // branchless tap budget: inactive taps keep a constant loop bound
      // (GLSL ES 1.0 wants a constant trip count) but contribute nothing
      float active = step(fi, uTaps - 1.0);
      float w = active * (1.0 - 0.8 * abs(k));
      float a = a0 + span * k;
      vec2 uv = vec2(cos(a), sin(a)) * (r * 0.5) + 0.5;
      sum += texture2D(tScene, uv) * w;
      wsum += w;
    }
    // premultiplied average: rgb and alpha move together, so a smear over a
    // transparent region stays transparent (no dark box / halo / ghost edge)
    gl_FragColor = sum / max(wsum, 1e-4);
  }
`;

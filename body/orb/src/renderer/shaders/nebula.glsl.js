// Sage Core layer 1 — NEBULA HAZE (spec §2.1.1)
// Soft fbm clouds, slow drift, low opacity. Palette: lime #B8E02A, teal #2DD4BF,
// blue #3B82F6, faint magenta #C026D3 only at the edges. Anime compositing:
// flat additive glow with a radial mask that fades to nothing BEFORE the window edge.
export const nebulaVert = `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

export const nebulaFrag = `
  precision mediump float;
  varying vec2 vUv;
  uniform float uTime;
  uniform float uOpacity;
  uniform vec3 cLime;    // #B8E02A
  uniform vec3 cTeal;    // #2DD4BF
  uniform vec3 cBlue;    // #3B82F6
  uniform vec3 cMagenta; // #C026D3

  float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
  float noise(vec2 p) {
    vec2 i = floor(p), f = fract(p);
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash(i), hash(i + vec2(1.0, 0.0)), u.x),
               mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), u.x), u.y);
  }
  float fbm(vec2 p) {
    float v = 0.0, a = 0.5;
    for (int i = 0; i < 4; i++) { v += a * noise(p); p *= 2.03; a *= 0.5; }
    return v;
  }

  void main() {
    vec2 p = (vUv - 0.5) * 2.0;              // unit space -1..1
    float r = length(p);
    float t = uTime * 0.03;                  // slow drift
    float n  = fbm(p * 1.6 + vec2(t, -t * 0.7));
    float n2 = fbm(p * 2.3 - vec2(t * 0.6, t));
    vec3 col = mix(cLime, cTeal, smoothstep(0.35, 0.65, n));
    col = mix(col, cBlue, smoothstep(0.5, 0.8, n2) * 0.7);
    col = mix(col, cMagenta, smoothstep(0.75, 1.0, r) * 0.30 * smoothstep(0.4, 0.7, n2));
    float body = smoothstep(0.9, 0.2, r) * smoothstep(0.2, 0.55, n) * 0.9;
    float edge = smoothstep(1.0, 0.5, r);    // fade to nothing before window edge
    float a = body * edge * uOpacity;
    gl_FragColor = vec4(col * a, a);         // premultiplied, black = transparent
  }
`;

// Core rendering — TWO parts sharing ONE uniforms object (single damping path):
// 1. fragmentShader: the 3D SPHERE ball (SphereGeometry, normal-based anime
//    shading: fixed upper-left light, camera-facing hot center, limb falloff,
//    glowing rim). This is what makes the center read as a real ball, not a
//    flat disc (user review).
// 2. glowShader: additive bloom billboard placed BEHIND the ball (depth-tested
//    so only the halo ring around the silhouette shows) + soft starburst.
// Uniform `color` = state tint (renderer sets it via uniforms.color.setHex).

export const fragmentShader = `
  uniform vec3 color;
  uniform float uBright;
  uniform float uAmp;
  varying vec3 vN;
  varying vec3 vV;

  void main() {
    vec3 N = normalize(vN);
    vec3 V = normalize(vV);
    float facing = clamp(dot(N, V), 0.0, 1.0);
    vec3 L = normalize(vec3(-0.45, 0.55, 0.72));  // fixed light, upper-left
    float diff = clamp(dot(N, L), 0.0, 1.0);

    // anime ball: lit body toward the light, limb falls off, hot camera-center
    float body = 0.26 + 0.85 * pow(diff, 1.35);
    float hot  = pow(facing, 3.0) * 0.6;           // bright heart toward viewer
    float rim  = pow(1.0 - facing, 2.6) * 0.55;    // glowing rim = dimension

    vec3 base = vec3(1.0);
    base = mix(base, vec3(1.0, 0.94, 0.84), (1.0 - facing) * 0.3 + (1.0 - diff) * 0.2);
    base = mix(base, color, 0.55 * (1.0 - facing)); // state tint at the limb
    float limbFade = smoothstep(0.0, 0.3, facing);   // SOFT edge: dissolves into haze at the silhouette
    float a = clamp((body + hot + rim) * limbFade * uBright * (1.0 + uAmp * 0.25), 0.0, 1.0);
    gl_FragColor = vec4(base * a, a);                // premultiplied; soft edge fades out
  }
`;

export const glowShader = `
  uniform vec3 color;
  uniform float uBright;
  uniform float uAmp;
  varying vec3 vPos;

  void main() {
    vec2 p = vPos.xy;
    float r = length(p);
    float ang = atan(p.y, p.x);
    float R = 0.52;                                // must match the ball radius
    float halo = exp(-max(r - R, 0.0) * 3.4) * 0.55;
    float rimhaze = exp(-abs(r - R) * 7.0) * 0.38;   // soft haze band at the ball edge
    float star = pow(abs(cos(ang * 4.0)), 20.0) * exp(-max(r - R, 0.0) * 2.4) * 0.30;
    float a = (halo + rimhaze + star) * uBright * (1.0 + uAmp * 0.4);
    a = clamp(a, 0.0, 1.0);
    float edge = smoothstep(1.28, 0.9, r);         // unit fade before plane edge
    vec3 tinted = mix(vec3(1.0), color, 0.35);
    gl_FragColor = vec4(tinted * a * edge, a * edge); // premultiplied additive
  }
`;

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

    // SUN-LIKE plasma ball (user): envelope = pow(facing, n) gives a smooth,
    // monotonic falloff to zero at the limb — NO hard edge, no rim ring.
    float envelope = pow(facing, 1.6);               // sun falloff: bright heart -> soft haze edge
    float form = 0.35 + 0.7 * pow(diff, 1.25);       // directional shading keeps it a 3D sphere
    float hot = pow(facing, 7.0) * 0.62;             // tight white-hot heart (§3.1: hottest centre)

    vec3 base = vec3(1.0);
    // §3.1: a FAINT WARM tint only at the very centre — it fades out fast so
    // the middle reads white-hot while the rim picks up the state colour.
    base = mix(base, vec3(1.0, 0.92, 0.80), pow(facing, 3.0) * 0.55);
    base = mix(base, color, 0.85 + 0.15 * (1.0 - facing * facing)); // state color dominates the WHOLE sun (error = red core; white states unaffected)
    float a = clamp((envelope * form + hot) * uBright * (1.0 + uAmp * 0.25), 0.0, 1.0);
    gl_FragColor = vec4(base * a, a);                // premultiplied; edge dissolves to zero
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
    // §3.1 BLOOM: two exponentials — a tight halo plus a much wider skirt —
    // so the falloff is smooth and edgeless all the way to the plane border.
    float corona = exp(-r * 3.2) * 0.42;
    float skirt  = exp(-r * 1.15) * 0.16;
    // §3.1 DIFFRACTION: six thin spikes — four at 90 deg plus a horizontal
    // lens-flare pair. Thin (high pow), long (slow exp), subtle.
    float spikes = pow(abs(cos(ang * 4.0)), 44.0) * exp(-r * 1.5) * 0.30;
    float flare  = pow(max(1.0 - abs(sin(ang)), 0.0), 120.0) * exp(-r * 1.9) * 0.12;
    float a = (corona + skirt + spikes + flare) * uBright * (1.0 + uAmp * 0.3);
    a = clamp(a, 0.0, 1.0);
    float edge = smoothstep(1.28, 0.9, r);         // unit fade before plane edge
    vec3 tinted = mix(vec3(1.0), color, 0.8); // corona carries the state color (error = red GLOW)
    gl_FragColor = vec4(tinted * a * edge, a * edge); // premultiplied additive
  }
`;

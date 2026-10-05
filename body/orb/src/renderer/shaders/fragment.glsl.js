export const fragmentShader = `
  uniform vec3 color;
  varying vec3 vPos;
  void main(){
    float dist = length(vPos);
    float alpha = smoothstep(1.0, 0.9, dist);
    gl_FragColor = vec4(color, alpha);
  }
`;

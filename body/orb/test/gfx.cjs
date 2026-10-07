// gfx.cjs — tiny dependency-free raster helpers for the orb lane's evidence
// images (startup curve plot, filmstrips). Only what the harness needs:
// decode -> draw lines/rects/text onto an RGBA buffer -> encode PNG.
const { decode, encode } = require('./png.cjs');

function create(w, h, bg = [0, 0, 0, 255]) {
  const data = Buffer.alloc(w * h * 4);
  for (let i = 0; i < w * h; i++) {
    data[i * 4] = bg[0]; data[i * 4 + 1] = bg[1];
    data[i * 4 + 2] = bg[2]; data[i * 4 + 3] = bg[3];
  }
  return { width: w, height: h, data };
}

function px(img, x, y, c) {
  if (x < 0 || y < 0 || x >= img.width || y >= img.height) return;
  const i = (y * img.width + x) * 4;
  const a = (c[3] === undefined ? 255 : c[3]) / 255;
  img.data[i] = Math.round(c[0] * a + img.data[i] * (1 - a));
  img.data[i + 1] = Math.round(c[1] * a + img.data[i + 1] * (1 - a));
  img.data[i + 2] = Math.round(c[2] * a + img.data[i + 2] * (1 - a));
  img.data[i + 3] = Math.max(img.data[i + 3], Math.round(255 * a));
}

function rect(img, x0, y0, w, h, c) {
  for (let y = y0; y < y0 + h; y++) for (let x = x0; x < x0 + w; x++) px(img, x, y, c);
}

function line(img, x0, y0, x1, y1, c) {
  const dx = Math.abs(x1 - x0), dy = Math.abs(y1 - y0);
  const sx = x0 < x1 ? 1 : -1, sy = y0 < y1 ? 1 : -1;
  let err = dx - dy;
  let x = Math.round(x0), y = Math.round(y0);
  for (;;) {
    px(img, x, y, c);
    if (x === Math.round(x1) && y === Math.round(y1)) break;
    const e2 = 2 * err;
    if (e2 > -dy) { err -= dy; x += sx; }
    if (e2 < dx) { err += dx; y += sy; }
  }
}

/** Polyline through [[x,y], ...] in pixel space. */
function polyline(img, pts, c) {
  for (let i = 1; i < pts.length; i++) line(img, pts[i - 1][0], pts[i - 1][1], pts[i][0], pts[i][1], c);
}

/** Alpha-blit a decoded image (e.g. a screenshot) into another at (x,y). */
function blit(dst, src, x0, y0) {
  for (let y = 0; y < src.height; y++) {
    for (let x = 0; x < src.width; x++) {
      const si = (y * src.width + x) * 4;
      const a = src.data[si + 3] / 255;
      if (a <= 0) continue;
      px(dst, x0 + x, y0 + y, [src.data[si], src.data[si + 1], src.data[si + 2], a]);
    }
  }
}

// --- 5x7 bitmap font --------------------------------------------------------
// Only the glyphs the harness labels need (A-Z, 0-9, a few symbols).
const FONT = {
  '0': ['01110','10001','10011','10101','11001','10001','01110'],
  '1': ['00100','01100','00100','00100','00100','00100','01110'],
  '2': ['01110','10001','00001','00010','00100','01000','11111'],
  '3': ['11111','00010','00100','00010','00001','10001','01110'],
  '4': ['00010','00110','01010','10010','11111','00010','00010'],
  '5': ['11111','10000','11110','00001','00001','10001','01110'],
  '6': ['00110','01000','10000','11110','10001','10001','01110'],
  '7': ['11111','00001','00010','00100','01000','01000','01000'],
  '8': ['01110','10001','10001','01110','10001','10001','01110'],
  '9': ['01110','10001','10001','01111','00001','00010','01100'],
  'A': ['01110','10001','10001','11111','10001','10001','10001'],
  'B': ['11110','10001','10001','11110','10001','10001','11110'],
  'C': ['01110','10001','10000','10000','10000','10001','01110'],
  'D': ['11110','10001','10001','10001','10001','10001','11110'],
  'E': ['11111','10000','10000','11110','10000','10000','11111'],
  'F': ['11111','10000','10000','11110','10000','10000','10000'],
  'G': ['01110','10001','10000','10111','10001','10001','01111'],
  'H': ['10001','10001','10001','11111','10001','10001','10001'],
  'I': ['01110','00100','00100','00100','00100','00100','01110'],
  'J': ['00111','00010','00010','00010','00010','10010','01100'],
  'K': ['10001','10010','10100','11000','10100','10010','10001'],
  'L': ['10000','10000','10000','10000','10000','10000','11111'],
  'M': ['10001','11011','10101','10101','10001','10001','10001'],
  'N': ['10001','11001','10101','10011','10001','10001','10001'],
  'O': ['01110','10001','10001','10001','10001','10001','01110'],
  'P': ['11110','10001','10001','11110','10000','10000','10000'],
  'Q': ['01110','10001','10001','10001','10101','10010','01101'],
  'R': ['11110','10001','10001','11110','10100','10010','10001'],
  'S': ['01111','10000','10000','01110','00001','00001','11110'],
  'T': ['11111','00100','00100','00100','00100','00100','00100'],
  'U': ['10001','10001','10001','10001','10001','10001','01110'],
  'V': ['10001','10001','10001','10001','10001','01010','00100'],
  'W': ['10001','10001','10001','10101','10101','11011','10001'],
  'X': ['10001','10001','01010','00100','01010','10001','10001'],
  'Y': ['10001','10001','01010','00100','00100','00100','00100'],
  'Z': ['11111','00001','00010','00100','01000','10000','11111'],
  '.': ['00000','00000','00000','00000','00000','01100','01100'],
  ',': ['00000','00000','00000','00000','00110','00100','01000'],
  '-': ['00000','00000','00000','11111','00000','00000','00000'],
  '+': ['00000','00100','00100','11111','00100','00100','00000'],
  '/': ['00001','00010','00010','00100','01000','01000','10000'],
  ':': ['00000','01100','01100','00000','01100','01100','00000'],
  '%': ['11001','11010','00010','00100','01000','01011','10011'],
  '(': ['00010','00100','01000','01000','01000','00100','00010'],
  ')': ['01000','00100','00010','00010','00010','00100','01000'],
  ' ': ['00000','00000','00000','00000','00000','00000','00000'],
  '=': ['00000','00000','11111','00000','11111','00000','00000'],
  '_': ['00000','00000','00000','00000','00000','00000','11111'],
  '>': ['01000','00100','00010','00001','00010','00100','01000'],
  '<': ['00010','00100','01000','10000','01000','00100','00010'],
  '*': ['00000','10101','01110','11111','01110','10101','00000'],
};

function text(img, str, x, y, c, scale = 2) {
  let cx = x;
  for (const ch of String(str).toUpperCase()) {
    const g = FONT[ch] || FONT[' '];
    for (let r = 0; r < 7; r++) {
      for (let col = 0; col < 5; col++) {
        if (g[r][col] === '1') rect(img, cx + col * scale, y + r * scale, scale, scale, c);
      }
    }
    cx += 6 * scale;
  }
  return cx;
}

function textWidth(str, scale = 2) { return String(str).length * 6 * scale; }

/**
 * Line chart. series = [{ label, color, values:[...] }], all sampled on the
 * same x axis. Returns nothing; mutates/returns an RGB image.
 */
function chart(img, opts) {
  const { x, y, w, h, series, xmin = 0, xmax, ymin = 0, ymax, title, xlabel } = opts;
  const all = series.flatMap((s) => s.values.filter((v) => Number.isFinite(v)));
  const yMax = ymax !== undefined ? ymax : Math.max(...all, 1e-9);
  const yMin = ymin !== undefined ? ymin : Math.min(...all, 0);
  const xMax = xmax !== undefined ? xmax : Math.max(...series[0].values.length - 1, 1);
  const n = series[0].values.length;

  // frame + grid
  rect(img, x, y, w, h, [24, 26, 32, 255]);
  for (let g = 1; g < 5; g++) {
    const gy = y + Math.round((h * g) / 5);
    for (let gx = x; gx < x + w; gx++) px(img, gx, gy, [46, 50, 60, 255]);
  }
  for (let g = 1; g < 6; g++) {
    const gx = x + Math.round((w * g) / 6);
    for (let gy = y; gy < y + h; gy++) px(img, gx, gy, [46, 50, 60, 255]);
  }
  rect(img, x, y, w, 1, [120, 126, 140, 255]);
  rect(img, x, y + h - 1, w, 1, [120, 126, 140, 255]);
  rect(img, x, y, 1, h, [120, 126, 140, 255]);
  rect(img, x + w - 1, y, 1, h, [120, 126, 140, 255]);

  for (const s of series) {
    const pts = [];
    for (let i = 0; i < n; i++) {
      const v = s.values[i];
      if (!Number.isFinite(v)) continue;
      const px_ = x + (n === 1 ? w / 2 : (i / (n - 1)) * (w - 1));
      const py = y + h - 1 - ((v - yMin) / (yMax - yMin || 1)) * (h - 1);
      pts.push([px_, Math.max(y + 1, Math.min(y + h - 2, py))]);
    }
    polyline(img, pts, s.color);
  }

  // labels
  let ty = y - 22;
  if (title) { text(img, title, x, ty, [235, 238, 245, 255], 2); ty -= 0; }
  let lx = x;
  for (const s of series) {
    rect(img, lx, y + h + 8, 14, 3, s.color);
    text(img, s.label, lx + 18, y + h + 4, [210, 214, 224, 255], 2);
    lx += 18 + textWidth(s.label, 2) + 20;
  }
  text(img, `MAX ${yMax.toFixed(3)}`, x, y + h + 26, [150, 156, 170, 255], 2);
  text(img, `MIN ${yMin.toFixed(3)}`, x + 220, y + h + 26, [150, 156, 170, 255], 2);
  if (xlabel) text(img, xlabel, x + 440, y + h + 26, [150, 156, 170, 255], 2);
}

/** Horizontal contact sheet of decoded frames with a labelled caption bar. */
function filmstrip(frames, opts = {}) {
  const { cell = 140, gap = 6, captionH = 26, bg = [16, 17, 20, 255] } = opts;
  const w = frames.length * cell + (frames.length + 1) * gap;
  const h = cell + (captionH + gap) * 2;
  const img = create(w, h, bg);
  frames.forEach((f, i) => {
    const x = gap + i * (cell + gap);
    // fit the frame into the cell preserving aspect
    const scale = Math.min(cell / f.width, cell / f.height);
    const dw = Math.round(f.width * scale), dh = Math.round(f.height * scale);
    const dst = create(dw, dh, [0, 0, 0, 0]);
    // nearest-neighbour resample
    for (let y = 0; y < dh; y++) {
      for (let xx = 0; xx < dw; xx++) {
        const sx = Math.min(f.width - 1, Math.floor((xx / dw) * f.width));
        const sy = Math.min(f.height - 1, Math.floor((y / dh) * f.height));
        const si = (sy * f.width + sx) * 4;
        dst.data[(y * dw + xx) * 4] = f.data[si];
        dst.data[(y * dw + xx) * 4 + 1] = f.data[si + 1];
        dst.data[(y * dw + xx) * 4 + 2] = f.data[si + 2];
        dst.data[(y * dw + xx) * 4 + 3] = 255;
      }
    }
    blit(img, dst, x, gap);
    rect(img, x, gap + cell - 1, cell, 1, [70, 74, 86, 255]);
    const label = opts.labels ? opts.labels[i] : '';
    text(img, label, x + 2, gap + cell + 8, [225, 228, 236, 255], 2);
  });
  return img;
}

module.exports = { create, px, rect, line, polyline, blit, text, textWidth, chart, filmstrip, encode };

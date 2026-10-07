// Minimal dependency-free PNG reader (8-bit, non-interlaced) — enough to
// pixel-diff Chrome's `Page.captureScreenshot` output in the orb trace tests.
// We deliberately do NOT add a pngjs dependency (no version drift, ORB_REBUILD
// appendix item 7): Electron captures as color type 2 (RGB) or 6 (RGBA).
const zlib = require('zlib');

const SIGNATURE = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);

function paeth(a, b, c) {
  const p = a + b - c;
  const pa = Math.abs(p - a), pb = Math.abs(p - b), pc = Math.abs(p - c);
  if (pa <= pb && pa <= pc) return a;
  if (pb <= pc) return b;
  return c;
}

function decode(buf) {
  if (!buf || buf.length < 8 || !buf.subarray(0, 8).equals(SIGNATURE)) {
    throw new Error('not a PNG');
  }
  let off = 8;
  let ihdr = null;
  const idat = [];
  while (off + 8 <= buf.length) {
    const len = buf.readUInt32BE(off);
    const type = buf.toString('ascii', off + 4, off + 8);
    const data = buf.subarray(off + 8, off + 8 + len);
    if (type === 'IHDR') {
      ihdr = {
        width: data.readUInt32BE(0), height: data.readUInt32BE(4),
        bitDepth: data[8], colorType: data[9], interlace: data[12],
      };
    } else if (type === 'IDAT') {
      idat.push(Buffer.from(data));
    } else if (type === 'IEND') {
      break;
    }
    off += 12 + len;
  }
  if (!ihdr) throw new Error('PNG has no IHDR');
  if (ihdr.bitDepth !== 8) throw new Error('only 8-bit PNG supported, got ' + ihdr.bitDepth);
  if (ihdr.interlace !== 0) throw new Error('interlaced PNG not supported');
  const channels = { 0: 1, 2: 3, 4: 2, 6: 4 }[ihdr.colorType];
  if (!channels) throw new Error('unsupported color type ' + ihdr.colorType);

  const raw = zlib.inflateSync(Buffer.concat(idat));
  const { width, height } = ihdr;
  const bpp = channels;                 // bytes per pixel
  const stride = width * bpp;
  const out = Buffer.alloc(height * stride);

  for (let y = 0; y < height; y++) {
    const f = raw[y * (stride + 1)];
    const rowIn = raw.subarray(y * (stride + 1) + 1, (y + 1) * (stride + 1));
    const rowOut = out.subarray(y * stride, (y + 1) * stride);
    const prev = y > 0 ? out.subarray((y - 1) * stride, y * stride) : null;
    for (let x = 0; x < stride; x++) {
      const a = x >= bpp ? rowOut[x - bpp] : 0;
      const b = prev ? prev[x] : 0;
      const c = (prev && x >= bpp) ? prev[x - bpp] : 0;
      const v = rowIn[x];
      switch (f) {
        case 0: rowOut[x] = v; break;
        case 1: rowOut[x] = (v + a) & 255; break;
        case 2: rowOut[x] = (v + b) & 255; break;
        case 3: rowOut[x] = (v + ((a + b) >> 1)) & 255; break;
        case 4: rowOut[x] = (v + paeth(a, b, c)) & 255; break;
        default: throw new Error('bad PNG filter ' + f);
      }
    }
  }

  // normalize to RGBA so diffing never cares about the source color type
  const rgba = Buffer.alloc(width * height * 4);
  for (let i = 0, p = 0; i < width * height; i++) {
    const s = i * bpp;
    if (channels === 4) {
      rgba[i * 4] = out[s]; rgba[i * 4 + 1] = out[s + 1];
      rgba[i * 4 + 2] = out[s + 2]; rgba[i * 4 + 3] = out[s + 3];
    } else if (channels === 3) {
      rgba[i * 4] = out[s]; rgba[i * 4 + 1] = out[s + 1];
      rgba[i * 4 + 2] = out[s + 2]; rgba[i * 4 + 3] = 255;
    } else if (channels === 2) {
      rgba[i * 4] = rgba[i * 4 + 1] = rgba[i * 4 + 2] = out[s];
      rgba[i * 4 + 3] = out[s + 1];
    } else {
      rgba[i * 4] = rgba[i * 4 + 1] = rgba[i * 4 + 2] = out[s];
      rgba[i * 4 + 3] = 255;
    }
    p += 4;
  }
  return { width, height, data: rgba };
}

module.exports = { decode, encode, average };

// ---------------------------------------------------------------------------
// Minimal PNG writer (8-bit RGBA, no interlacing, filter 0) so the trace can
// write the TEMPORALLY AVERAGED image of a state — a single screenshot of an
// animated orb differs from the next one purely because it is spinning, which
// would drown out the state difference the gate is trying to measure.
// ---------------------------------------------------------------------------
const CRC_TABLE = (() => {
  const t = new Int32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c;
  }
  return t;
})();

function crc32(buf) {
  let c = 0xffffffff;
  for (let i = 0; i < buf.length; i++) c = CRC_TABLE[(c ^ buf[i]) & 255] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

function chunk(type, data) {
  const out = Buffer.alloc(12 + data.length);
  out.writeUInt32BE(data.length, 0);
  out.write(type, 4, 'ascii');
  data.copy(out, 8);
  out.writeUInt32BE(crc32(out.subarray(4, 8 + data.length)), 8 + data.length);
  return out;
}

function encode({ width, height, data }) {
  const stride = width * 4;
  const raw = Buffer.alloc((stride + 1) * height);
  for (let y = 0; y < height; y++) {
    raw[y * (stride + 1)] = 0; // filter: none
    data.copy ? data.copy(raw, y * (stride + 1) + 1, y * stride, (y + 1) * stride)
              : Buffer.from(data.subarray(y * stride, (y + 1) * stride))
                  .copy(raw, y * (stride + 1) + 1);
  }
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8;  // bit depth
  ihdr[9] = 6;  // color type RGBA
  ihdr[10] = 0; ihdr[11] = 0; ihdr[12] = 0;
  return Buffer.concat([
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
    chunk('IHDR', ihdr),
    chunk('IDAT', zlib.deflateSync(raw, { level: 6 })),
    chunk('IEND', Buffer.alloc(0)),
  ]);
}

/**
 * Average N decoded frames into one image (per-channel, alpha included).
 * The orb is a continuously animated surface: a single screenshot differs from
 * the next purely because it is spinning. Averaging a short burst collapses
 * that motion to the state's time-mean appearance, which is both what a human
 * actually perceives and a stable signature to diff against.
 */
function average(decoded) {
  if (!decoded.length) throw new Error('average(): no frames');
  const { width, height } = decoded[0];
  const acc = new Float64Array(width * height * 4);
  for (const d of decoded) {
    if (d.width !== width || d.height !== height) throw new Error('average(): size mismatch');
    for (let i = 0; i < d.data.length; i++) acc[i] += d.data[i];
  }
  const out = Buffer.alloc(width * height * 4);
  for (let i = 0; i < acc.length; i++) out[i] = Math.round(acc[i] / decoded.length);
  return { width, height, data: out };
}

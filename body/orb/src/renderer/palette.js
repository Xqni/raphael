// palette.js — the theme hook (fidelity pass §5).
//
// ONE design, recolourable. `orb.theme: raphael | ciel | custom` resolves to a
// flat token map; `orb.vibrance` (0.8-1.5) then scales saturation/lightness of
// every token so §3.7's "raise saturation toward the reference haze" is a
// config number rather than a hand-edit. A later Ciel upgrade is a config
// change — see docs/orb/THEMES.md.
//
// No THREE import here: the renderer owns the library, this only returns hex.

const RAPHAEL = {
  core_tint: '#FFFFFF',
  haze_lime: '#B8E02A',
  haze_teal: '#2DD4BF',
  haze_blue: '#3B82F6',
  haze_magenta: '#C026D3',
  ring_color: '#FFFFFF',
  glyph_color: '#FFB000',
  accent: '#2DD4BF',
  // SEMANTIC, never themed: the Private-Mode ring (ORB_REBUILD §3 names teal
  // #2DD4BF explicitly). Keeping it out of the theme means Private stays
  // unmistakable over ANY palette — including the gold-leaning Ciel one — and
  // never collides with paused/offline greys.
  private_ring: '#2DD4BF',
};

// CIEL — tier 3, gold-leaning (docs/evolution/02-persona-tiers.md §5.3,
// requested by evolution-persona in evolution-persona__to__orb__ciel-gold-
// palette.md). Direction is theirs; the exact swatches are this lane's design
// authority: a warm gold/amber family built on #E8B84B, distinctly warmer than
// Raphael's white + green/teal/blue haze. `great_sage`/`raphael` are untouched
// and must stay byte-identical (asserted in tests/palette.test.mjs).
const CIEL = {
  core_tint: '#FFF6E3',   // warm white-hot (Raphael: pure white)
  haze_lime: '#E8B84B',   // the base they named
  haze_teal: '#F0A45C',   // amber, warmer stand-in for Raphael's teal
  haze_blue: '#D98C3A',   // burnt amber
  haze_magenta: '#E0674F',// warm coral
  ring_color: '#FFE9B8',  // pale gold orbit ring
  glyph_color: '#FFC247', // gold, warmer than Raphael's #FFB000
  accent: '#E8B84B',      // orbiting job beads
  private_ring: '#2DD4BF',// SAME teal — semantic, see RAPHAEL.private_ring
};

// `ciel` is currently an ALIAS of raphael (THEMES.md §4) — same tokens, so a
// persona change cannot fork the design.
// `great_sage` is the IDENTITY tier (docs/evolution/04-tier-switch-test-plan.md
// A2: it changes nothing) — so it renders exactly like Raphael today. Adding a
// Ciel look later means editing this map, not the renderer.
const THEMES = { great_sage: RAPHAEL, raphael: RAPHAEL, ciel: CIEL };

// --- tiny hex<->hsl helpers (no THREE dependency) ---------------------------
function hexToRgb(hex) {
  const h = hex.replace('#', '');
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
}
function rgbToHsl(r, g, b) {
  r /= 255; g /= 255; b /= 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b);
  let h = 0, s = 0;
  const l = (max + min) / 2;
  if (max !== min) {
    const d = max - min;
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    if (max === r) h = ((g - b) / d + (g < b ? 6 : 0));
    else if (max === g) h = (b - r) / d + 2;
    else h = (r - g) / d + 4;
    h /= 6;
  }
  return [h, s, l];
}
function hslToHex(h, s, l) {
  const hue2rgb = (p, q, t) => {
    if (t < 0) t += 1;
    if (t > 1) t -= 1;
    if (t < 1 / 6) return p + (q - p) * 6 * t;
    if (t < 1 / 2) return q;
    if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6;
    return p;
  };
  let r, g, b;
  if (s === 0) { r = g = b = l; } else {
    const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
    const p = 2 * l - q;
    r = hue2rgb(p, q, h + 1 / 3);
    g = hue2rgb(p, q, h);
    b = hue2rgb(p, q, h - 1 / 3);
  }
  const to2 = (v) => Math.round(v * 255).toString(16).padStart(2, '0');
  return `#${to2(r)}${to2(g)}${to2(b)}`.toUpperCase();
}

/** Saturation/lightness scaled by vibrance (1.0 = untouched). */
function vibrance(hex, v) {
  if (!Number.isFinite(v) || v === 1) return hex;
  const [r, g, b] = hexToRgb(hex);
  const [h, s, l] = rgbToHsl(r, g, b);
  const ns = Math.max(0, Math.min(1, s * v));
  const nl = Math.max(0, Math.min(1, l * (1 + (v - 1) * 0.35)));
  return hslToHex(h, ns, nl);
}

/**
 * @param {{theme?:string, vibrance?:number, themeTokens?:object}} cfg
 * @returns {object} flat hex token map, vibrance applied, every key present
 */
function resolvePalette(cfg) {
  // `auto` (the Wave-5 default) follows persona.tier so a tier switch is a
  // config change; an explicit theme name pins it and wins over the tier.
  const wanted = (cfg && cfg.theme === 'auto')
    ? (cfg.personaTier || 'great_sage')
    : (cfg && cfg.theme);
  const named = THEMES[wanted] || RAPHAEL;
  const raw = (cfg && wanted === 'custom')
    ? { ...named, ...(cfg.themeTokens || {}) }
    : { ...named };
  // 0.8..1.5 per THEMES.md. config.js clamps too, but this is the point of
  // use, so an out-of-range value from any caller cannot slip through.
  const rawV = (cfg && Number.isFinite(cfg.vibrance)) ? cfg.vibrance : 1.15;
  const v = Math.min(1.5, Math.max(0.8, rawV));
  const out = {};
  for (const k of Object.keys(RAPHAEL)) {
    // unknown/absent custom token falls back to the Raphael default, so a
    // partial theme still renders rather than going black
    out[k] = vibrance(raw[k] || RAPHAEL[k], v);
  }
  out.vibrance = v;
  return out;
}

export { resolvePalette, RAPHAEL, THEMES, vibrance };

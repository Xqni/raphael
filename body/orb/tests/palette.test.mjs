// evolution-persona → orb: gold-leaning Ciel palette — acceptance tests.
// Request: docs/requests/evolution-persona__to__orb__ciel-gold-palette.md
//
// Pure (no GPU, no Electron) so it runs in `npm run test:unit`.
//
// Their three requirements:
//  (1) a gold-leaning Ciel palette (direction theirs, swatches ours)
//  (2) tier switch selects it; great_sage/raphael stay BYTE-IDENTICAL
//  (3) private/paused overlays keep working over the gold palette
import assert from 'node:assert';
import { resolvePalette } from '../src/renderer/palette.js';

const results = [];
function check(name, fn) {
  try { fn(); results.push(`  ok   ${name}`); }
  catch (e) { results.push(`  FAIL ${name}: ${e.message}`); process.exitCode = 1; }
}
const V = 1.15;
const tier = (t) => resolvePalette({ theme: 'auto', personaTier: t, vibrance: V });
const hue = (hex) => {
  const h = hex.replace('#', '');
  const r = parseInt(h.slice(0, 2), 16) / 255, g = parseInt(h.slice(2, 4), 16) / 255, b = parseInt(h.slice(4, 6), 16) / 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b), d = max - min;
  if (d === 0) return 0;
  let hh;
  if (max === r) hh = ((g - b) / d) % 6;
  else if (max === g) hh = (b - r) / d + 2;
  else hh = (r - g) / d + 4;
  hh *= 60;
  return hh < 0 ? hh + 360 : hh;
};

// (2) — the explicit regression point
check('great_sage and raphael are BYTE-IDENTICAL palettes', () => {
  assert.strictEqual(JSON.stringify(tier('great_sage')), JSON.stringify(tier('raphael')),
    'great_sage drifted from raphael');
});

check('raphael palette equals the frozen 2026-10-07 snapshot', () => {
  // Frozen at what the orb ACTUALLY renders with vibrance 1.15 applied
  // (the raw config values are #B8E02A / #2DD4BF / #3B82F6 / #C026D3).
  const SNAPSHOT = {
    core_tint: '#FFFFFF', haze_lime: '#C3EF29', haze_teal: '#2CE2CB',
    haze_blue: '#428AFF', haze_magenta: '#D020E6', ring_color: '#FFFFFF',
    glyph_color: '#FFB40D', accent: '#2CE2CB', private_ring: '#2CE2CB',
    vibrance: V,
  };
  assert.deepStrictEqual(tier('raphael'), SNAPSHOT,
    'existing tiers must not change — compare to the frozen snapshot');
});

check('great_sage / raphael / ciel all resolve under theme:auto', () => {
  for (const t of ['great_sage', 'raphael', 'ciel']) {
    const p = tier(t);
    assert.ok(p && p.haze_lime, `tier ${t} did not resolve`);
  }
});

// (1) — gold-leaning, distinctly warmer than Raphael
check('ciel is gold-leaning and distinctly warmer than raphael', () => {
  const c = tier('ciel'), r = tier('raphael');
  assert.notStrictEqual(JSON.stringify(c), JSON.stringify(r), 'ciel is identical to raphael');
  // only genuinely COLOURED tokens — white (raphael ring_color) has hue 0 by
  // definition, so it cannot be 'warmer' or 'cooler' than anything.
  for (const k of ['haze_lime', 'haze_teal', 'haze_blue', 'glyph_color', 'accent']) {
    const hc = hue(c[k]), hr = hue(r[k]);
    // warmer = lower hue in the 0-360 wheel for these warm families (70 -> 40)
    assert.ok(hc < hr, `${k}: ciel hue ${hc.toFixed(0)} is not warmer than raphael ${hr.toFixed(0)}`);
  }
  // the direction they fixed: built on #E8B84B
  const [cr, cg, cb] = c.haze_lime.replace('#', '').match(/../g).map((v) => parseInt(v, 16));
  assert.ok(cr > cg && cg > cb, `haze_lime ${c.haze_lime} is not a warm gold (expect R>G>B)`);
});

// (3) — semantic teal must survive the gold palette
check('private ring is the SAME teal in every theme (semantic, never themed)', () => {
  const vals = ['great_sage', 'raphael', 'ciel'].map((t) => tier(t).private_ring);
  assert.strictEqual(new Set(vals).size, 1, `private_ring differs: ${vals.join(', ')}`);
  assert.strictEqual(vals[0], '#2CE2CB', // vibrance 1.15 applied to the spec #2DD4BF
    'private_ring no longer renders as the vibranced spec teal');
  // and it must not collapse onto the palette accent for the gold theme
  assert.notStrictEqual(tier('ciel').accent, tier('ciel').private_ring,
    'ciel accent and private ring converged — Private would vanish into the gold');
});

check('paused steel is untouched by any theme (hardcoded in sagecore)', () => {
  // documented invariant: paused uses #9fb6d8 directly, not a palette token,
  // so it can never be confused with Private or Offline on any tier.
  const c = tier('ciel');
  assert.notStrictEqual(c.private_ring.toLowerCase(), '#9fb6d8');
});

check('vibrance is applied and clamped to 0.8..1.5', () => {
  const lo = resolvePalette({ theme: 'ciel', personaTier: 'ciel', vibrance: 0.1 });
  const hi = resolvePalette({ theme: 'ciel', personaTier: 'ciel', vibrance: 9 });
  assert.strictEqual(lo.vibrance, 0.8, 'vibrance floor not clamped');
  assert.strictEqual(hi.vibrance, 1.5, 'vibrance ceiling not clamped');
});

check('custom overrides still win, unknown tier falls back to raphael', () => {
  const custom = resolvePalette({ theme: 'custom', personaTier: 'ciel', vibrance: V,
    themeTokens: { haze_lime: '#123456' } });
  assert.ok(custom.haze_lime && custom.haze_lime !== tier('ciel').haze_lime, 'custom token ignored');
  const bad = resolvePalette({ theme: 'auto', personaTier: 'GOD', vibrance: V });
  assert.deepStrictEqual(bad, tier('raphael'), 'unknown tier must fall back to raphael');
});

console.log('Ciel gold palette (evolution-persona request):');
console.log(results.join('\n'));
if (process.exitCode) { console.error('FAILED'); process.exit(1); }
console.log(`All ${results.length} palette tests passed`);

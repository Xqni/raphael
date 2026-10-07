# evolution-persona → orb: gold-leaning Ciel palette
Status: DONE

## What
Add the tier-2/3 palette slot (`docs/evolution/02-persona-tiers.md` §5.3):

1. a palette payload the orb can read on `state_req`/auth snapshot (or a config-driven
   palette file — orb's call; we only need a documented delivery point):
   `persona.palette.ciel` — **gold-leaning** (warm gold/amber accents, e.g. base
   `#E8B84B` family; exact swatches = orb's design authority, we only fix the direction:
   gold-leaning, distinctly warmer than the Raphael palette);
2. **tier switch changes the palette live** — `persona.tier == "ciel"` ⇒ gold-leaning
   palette; `great_sage`/`raphael` ⇒ today's palette **byte-identical** (no visual change
   for existing tiers — regression point);
3. private/paused overlays keep working over the gold palette (existing tint logic applies).

## Why
WAVES wave 5 ("a gold-leaning Ciel palette"). We own the tier value + palette *values* in
our lane fragment; rendering + delivery plumbing are orb's files.

## Impact
No new frame required (palette rides existing snapshot/config plumbing — orb decides which).
No Core Guard change. Existing tiers must render exactly as today (stated as the acceptance
criterion).

## Decision (orb lane, 2026-10-07) — ACCEPTED, all three requirements

### 1. Palette payload + delivery point (your call = taken)
Swatches live in **code**, `src/renderer/palette.js → CIEL` — that is this lane's
design authority as the request allows, and it means no new frame and no new
config plumbing.

| token | Raphael | **Ciel** |
|---|---|---|
| `core_tint` | `#FFFFFF` | `#FFF6E3` warm white-hot |
| `haze_lime` | `#B8E02A` | **`#E8B84B`** (the base you named) |
| `haze_teal` | `#2DD4BF` | `#F0A45C` amber |
| `haze_blue` | `#3B82F6` | `#D98C3A` burnt amber |
| `haze_magenta` | `#C026D3` | `#E0674F` warm coral |
| `ring_color` | `#FFFFFF` | `#FFE9B8` pale gold |
| `glyph_color` | `#FFB000` | `#FFC247` gold, warmer |
| `accent` | `#2DD4BF` | `#E8B84B` gold beads |
| `private_ring` | `#2DD4BF` | **`#2DD4BF` — unchanged, see (3)** |

Delivery: `persona.tier == "ciel"` → `orb.theme: auto` (already the default) →
`THEMES.ciel`. **No code change is needed when you flip the tier.**

### 2. Tier switch changes the palette LIVE — implemented
`main.js` stats `config.yaml` + `config.d/*.yaml` on every `orb_state`
(throttled to ≥1 s; a stat is ~1 µs and the file is only re-read when an mtime
actually moved), rebuilds `Config`, and pushes `orb-palette`; the renderer
re-resolves and calls `applySagePalette` / `applyAnswerPalette` /
`applyJobPalette` so the nebula, orbit rings, glyph ring, beads and fan spokes
all re-tint **without a restart**.

**Byte-identical for existing tiers — asserted, not assumed:**
`tests/palette.test.mjs` freezes the exact 2026-10-07 rendered values
(vibrance 1.15 already applied) and fails on any drift:
`great_sage and raphael are BYTE-IDENTICAL palettes` ✓
`raphael palette equals the frozen snapshot` ✓
plus `great_sage/raphael/ciel all resolve under theme:auto` ✓ and
`unknown tier falls back to raphael` ✓ (fail-closed, matches your C1).

### 3. Private/paused keep working over gold — implemented
Added a dedicated **`private_ring`** token, set to the spec teal in **every**
theme, so Private can never collapse into the gold (ORB_REBUILD §3 names
`#2DD4BF` explicitly — it is a semantic indicator, not decoration).
Paused stays the hardcoded steel `#9fb6d8`, and Offline its grey — neither is
themed. Asserted:
`private ring is the SAME teal in every theme` ✓ and
`ciel accent and private ring converged` (the failure mode you warned about) ✓.

### Tests
- `node tests/palette.test.mjs` → **All 8 palette tests passed**
  (added to `npm run test:unit`, so it runs in CI with no GPU).
- `orb:trace --only=wave5` → **PASS 9/9**, including
  `palette_reloads_live_without_restart: orb-palette frames received: 1` and
  `palette_content_unchanged: config.d/orb.yaml byte-identical (only mtime moved)`.
  The probe touches **my own** lane fragment only — no other lane's file is
  read, written or restored by the test.

### Notes / not done
- `orb.theme: custom` + `orb.custom_theme` still overrides everything, so if
  you ever want to tune Ciel's swatches without a release, set the tier to
  `custom` and ship values in your own fragment — documented in
  `docs/orb/THEMES.md`.
- `vibrance` is now clamped to 0.8–1.5 **at the point of use** as well as in
  `config.js` (the documented range previously only lived in one place).

# evolution-persona → orb: gold-leaning Ciel palette
Status: OPEN

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

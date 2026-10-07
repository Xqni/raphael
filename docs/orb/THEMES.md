# docs/orb/THEMES.md — palette tokens and the Raphael → Ciel hook

Owner: orb lane. Design-only — this is a token system, **not** a second art
direction. `docs/ORB_REBUILD_TASK.md` stays the base spec; a theme may only
recolor what the spec drew, never redraw it.

---

## 1. Why

The same orb renders Raphael now and will render **Ciel** for a while after a
persona-tier change. If Ciel were a second design, every future fidelity fix
would have to be done twice and would drift apart. So the renderer draws ONE
design and reads its colors from tokens; a theme is a value, not a branch.

## 2. Configuration

```yaml
# config.d/orb.yaml (lane fragment) — deep-merged over config.yaml (INTERFACES §c)
orb:
  theme: auto        # auto | raphael | ciel | custom
  vibrance: 1.15     # 0.8 .. 1.5 — applied to the haze/glyph saturation
  custom_theme:      # only consulted when theme == custom
    core_tint: "#FFFFFF"
    ...
```

### `auto` — the persona tier picks the theme (Wave 5)

`auto` is the default and resolves through **`persona.tier`** from
`config.d/evolution-persona.yaml` (evolution-persona lane, AGENT_RULES §3):

```
persona.tier: great_sage | raphael | ciel   ->   orb theme of the same name
```

So a tier switch is a **config edit, never a renderer change** — the whole point
of this hook. `great_sage` is the *identity* tier
(`docs/evolution/04-tier-switch-test-plan.md` A2: it changes nothing) and
therefore renders exactly like Raphael today; `ciel` is currently an alias too.
An explicit `theme: raphael|ciel|custom` **pins** the palette and wins over the
tier, and an unknown/missing tier falls back to the Raphael palette rather than
rendering blank. Verified: `orb:trace --only=wave5` →
`theme_follows_persona_tier: orb.theme=auto persona.tier=great_sage`.

Read path (no secrets, no per-frame file IO):

```
config.yaml + config.d/*.yaml  ->  body/orb/src/main/config.js
                                ->  preload.js exposes window.orbConfig
                                      { theme, personaTier, vibrance, themeTokens }
                                ->  renderer.js resolves the palette once at
                                    startup and feeds the shader uniforms
```

`theme` is resolved **once, at page load** — and when it is `auto`,
`persona.tier` is read at that same moment. Changing either requires an orb
restart (they are design tokens, not runtime state).

## 3. Tokens

| token | drives | Raphael default | note |
|---|---|---|---|
| `core_tint` | the hot centre's base colour (`fragment.glsl` `color` uniform) | `#FFFFFF` | still multiplied by the per-state tint (error red, confirm amber, offline grey) |
| `haze_lime` | nebula lime/yellow-green | `#B8E02A` | ORB_REBUILD §2.1.1 |
| `haze_teal` | nebula teal + bokeh teal | `#2DD4BF` | ORB_REBUILD §2.1.1 |
| `haze_blue` | nebula blue + pane fill | `#3B82F6` | ORB_REBUILD §2.1.1 |
| `haze_magenta` | nebula edge magenta | `#C026D3` | ORB_REBUILD §2.1.1 |
| `ring_color` | Sage Core orbit rings | `#FFFFFF` | ORB_REBUILD §2.1.5 |
| `glyph_color` | Answer Mode gold script + streaks | `#FFB000` | spec §2.2 palette `#FFB000 / #FF9A1F / #FFE08A` |
| `accent` | job dots, private ring, UI highlights | `#2DD4BF` | must stay visually distinct from paused/offline |

`vibrance` is a post-resolve saturation multiplier in `[0.8, 1.5]` (clamped in
`config.js`). `1.0` = untouched, `1.15` = the fidelity-pass default.

**Tokens never change structure.** Line weights, geometry, timing, easing and
the state→visual mapping in `docs/ORB_REBUILD_TASK.md` §3 are shared by every
theme. That is the whole point: a later Ciel upgrade is
`orb.theme: ciel` (or a `custom_theme` block) plus, if desired, a new entry in
one map — never a renderer rewrite.

## 4. Adding a theme

1. Decide whether it is a **named alias** or a **custom block**.
   - Named alias (recommended when it ships as a persona tier): add the entry
     to `THEMES` in `src/renderer/palette.js` next to
     `great_sage`/`raphael`/`ciel`.
   - One-off: set `orb.theme: custom` and fill `orb.custom_theme` in
     `config.d/<your-lane>.yaml`.
2. Keep every token present — a missing token falls back to the Raphael
   default rather than to nothing, so a partial theme still renders.
3. Check the three legibility gates on **dark, light and busy** wallpapers:
   - `npm run orb:trace` (states must still differ — `npm run orb:diff`);
   - the private `accent` ring must not be confusable with paused/offline;
   - the core must remain the brightest element (checklist §8 item 3).
4. Screenshots go to `docs/orb/` as usual; there is no separate theme gallery.

## 5. `evolve_stage` — reserved, deliberately inert

A future evolution moment (a brief flourish when she upgrades tiers) should
not need a protocol change, so the field is reserved **now**:

| field | type | where | today |
|---|---|---|---|
| `evolve_stage` | `int` (0 = none, 1..N = stages) | optional on `orb_state` (PROTOCOL §3/§8) | **ignored** |

Contract notes for whoever implements it later:

- The orb must keep rendering normally when `evolve_stage` is absent or `0` —
  it is a **one-shot flourish layered on top of a normal state**, never a new
  base state, so `mode`, `jobs_active`, `shape_hint` and `task_kind` keep
  their meanings (INTERFACES §e).
- It is additive and short-lived; the Brain does not need to hold a state open
  for it, and the orb must not wait for a matching "end" frame (a repeat of
  the same stage value is a no-op).
- It is NOT in `orb_state`'s required set, so no brain-core change is needed
  before the design work starts.
- Nothing in `body/orb` **renders** it today. `ws-status.js` receives it on the
  `orb_state` frame and exposes it as `evolveStage`, and the renderer passes it
  through into its state object untouched — so wiring the visual later is a
  renderer-only change with no protocol or IPC edit.

**Do not build the flourish now** (task §5, explicit).

## 6. Persona tiers

`great_sage → raphael → ciel` are evolution/persona-lane concerns
(`docs/WAVES.md` Wave 5, lane `evolution-persona`). Since Wave 5 the orb reads
`persona.tier` **directly** when `orb.theme: auto`, so that lane does not have
to set `orb.theme` at all — setting `persona.tier` is enough and the orb picks
the palette up on its next start. Pin `orb.theme` only if the orb should
deliberately diverge from the tier.

# orb → integrator: backing-disc default should be 0 (user art feedback)

Status: OPEN

## What

`config.yaml → orb.backing_disc_alpha` is `0.25` (integrator-owned base), and
`docs/ORB_REBUILD_TASK.md` §4 describes the legibility backing disc as a
default-on feature. On **2026-10-06 the user looked at the orb and said**:

> "there is a black haze around the sun in the center which shouldn't be"

That haze **is** the backing disc: a black radial-gradient `CircleGeometry(1.35)`
at `z = -0.01` behind the core. Because it sits behind the sun but extends well
past its silhouette, it renders exactly as a dark ring/halo around the centre —
invisible on dark wallpaper, a grey smudge on light.

Proposed change (both files are integrator-owned):

```yaml
# config.yaml
orb:
  backing_disc_alpha: 0.0     # was 0.25
```

and in `docs/ORB_REBUILD_TASK.md` §4, a note that the user turned it off after
review, so the sentence "add a very soft, blurred, dark translucent radial disc
behind the orb (default alpha about 0.25)" no longer reflects the live default.

## Why

The user is the art authority (ORB_REBUILD appendix item 11) and this is a
direct, unambiguous instruction about the shipped look. Until the base is
changed I am overriding it from my own fragment —
`config.d/orb.yaml → backing_disc_alpha: 0.0` (AGENT_RULES §3: lanes change
config only through `config.d/<lane>.yaml`) — so the *live* behaviour is
already correct; what is stale is the base default and the spec text, which
other lanes/readers will keep quoting.

## Impact

- No behaviour change for anyone already running this branch — the renderer
  skips the mesh entirely when the alpha is 0, so there is no extra draw.
- `docs/ORB_REBUILD_TASK.md` §8 checklist item 6 ("no box, dark fringe, or
  clipping") is unaffected; if anything it is easier to satisfy with the disc
  gone.
- Risk of removing it: the white wireframe could lose contrast over a *bright*
  window. That is the one thing to re-check if the user later reports
  unreadability — the fix is to raise the alpha again, not to redesign.
- Core Guard: unaffected (AGENT_RULES §8).

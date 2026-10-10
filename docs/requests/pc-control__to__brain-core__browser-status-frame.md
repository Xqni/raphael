# pc-control → brain-core: browser-status-frame
Status: OPEN

## What
Consume (and if needed declare) the Body→Brain browser status push (charter
§5.2 P1 task4 — "Push browser status to the brain after every op and on tab
change"):

```jsonc
// role=body, additive frame (same grant spirit as `foreground`)
{"type": "browser_status", "v": 1, "ts": 1791655000000,
 "browser": {"up": true, "port": 9503,
             "active": {"id": "<target id>", "url": "…", "title": "…"}
                        | null,
             "tabs_count": 2}}
```
- Pushed: after every `browser{op}` act_res AND on tab-change ticks (the
  Body's CDP watcher polls `/json/list` at ~2 s while the worker is up);
  `up:false` is pushed when the worker dies/stops.
- Suggested consumer: cache `{browser, ts}` on the hub (freshness-bounded,
  mirroring the foreground ring) + expose to the vision/computer-use runner
  as the fallback hint (their runner is the documented fallback when the
  worker is down — charter [45]).
- Body-side guarantee: never raises into the client loop, deduped by
  (active id/url), retried on send failure (same discipline as the
  `foreground` frame).

If a §3 row is needed, integrator adds it next to `foreground`; this file
is the shape contract either way (the Body ships the frame on its branch).

## Why
Charter §5.2 P1 task4 + [45] ("Coordinate with computer-use — their vision
runner is fallback"): brain-core + computer-use need to know whether the
fast same-tab path is alive before choosing it.

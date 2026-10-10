# brain-core → integrator: browser-tab-frame (Wave 5U task 6)
Status: OPEN — code shipped additive (consumer live in brain/ws.py); needs PROTOCOL.md §3 + pc-control to send it

## What (new body→brain frame, role=body only)

```jsonc
// sent on focus/tab change; null url = tab context cleared (browser closed)
{"type": "browser_tab", "v": 1,
 "url": "https://www.youtube.com/watch?v=…", "title": "… - YouTube",
 "tab_id": "t123"}          // tab_id optional (opaque, browser's own)
```

Consumer (brain-core, shipped): `brain/ws.py:_on_browser_tab` →
`brain/worldstate.record_browser_tab()` — length-capped, value-blind, null
clears, never breaks the session; ack `{'kind':'browser_tab'}`.
Follow-up consumers (fastpath search-surface + later browser ops) treat an
absent/stale tab (>15 min) as NO context and fall back to today's
launch/search tools — fail-open to fallback, never a wrong-tab action.

## Asks

1. Integrator: add the frame to docs/PROTOCOL.md §3 (additive, v 1).
2. pc-control: send it from the browser worker (tab_id = your opaque id);
   coordinate the follow-up tool names in
   `brain-core__to__pc-control__browser-followup-tools.md`.

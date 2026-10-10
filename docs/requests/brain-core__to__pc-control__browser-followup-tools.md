# brain-core → pc-control: browser-followup-tools (Wave 5U task 6)
Status: OPEN — fastpath seams live with registry-probe fallbacks; names below are proposals (one-line change here on your reply)

## What

Fastpath follow-up intents are implemented against five proposed browser
tools (charter task 6: "scroll down/up", "go back/forward", "open the
Nth result", "read this page"). My side probes the registry — until your
tool lands, the user gets an HONEST "browser worker is not connected"
line (never fake success). All follow-ups are no-ops without a worker.

## Proposed tool names + shapes (gui category, act_req pipeline)

| tool | args | notes |
|---|---|---|
| `browser_scroll` | `{direction: "down"\|"up"}` | fastpath marks needs_lock=True |
| `browser_back` | `{}` | needs_lock=True |
| `browser_forward` | `{}` | needs_lock=True |
| `browser_click` | `{n: 1..10}` | "open the second result" → click nth search result; needs_lock=True |
| `browser_read` | `{}` | page text/DOM extract for the model (read-only, no lock) |

Plus the `browser_tab` push frame (my request to integrator:
`brain-core__to__integrator__browser-tab-frame.md`) — send it on
tab/focus change; `tab_id` is your opaque id; follow-ups currently rely on
the ACTIVE tab (Ctrl+L semantics), tab_id rides along for affinity.

Search-surface note: with an active YouTube tab + fresh browser foreground,
`search X` already navigates the SAME tab to the results URL via your
`navigate_url` (Wave-5P pairing) — `browser_click` completes the loop
(first/second result).

## Asks

1. Confirm/replace the five names (my mapping table is one line per tool).
2. Land the tools in your `brain/tools/pc/` group (yours); specs
   auto-register into my probe.

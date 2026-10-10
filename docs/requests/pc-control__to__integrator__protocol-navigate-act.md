# pc-control → integrator: protocol-navigate-act
Status: OPEN

## What
Add one act to the `docs/PROTOCOL.md` §7 allow-list (P0 UX, coord inbox
[42] — "YouTube two-tabs"):

```
`navigate_url{url}` — open a URL by NAVIGATING IN PLACE: reuse the
foreground browser tab (Ctrl+L, type URL, Enter) or the visible browser
window (focus first); first-ever open (no browser window) launches the
default handler. `lock:true` (keystroke injection), confirm=None
(http/https scheme-validated by the body).
```

Tracked via `PENDING_PROTO_ADDITIONS = ('activity', 'navigate_url')`
(conformance test asserts this file mentions the pending name).

## Why
- User-reported P0: "open youtube in browser" then "search pewdiepie"
  spawned TWO TABS because every URL open used the always-new-tab
  `webbrowser.open` path. `launch_url`/`search_youtube` keep their
  semantics (explicit new-tab requests); browser navigation moves to
  `navigate_url`, which the coordinator's dispatch [42] assigned:
  "when a browser window/tab already exists … reuse it: send Ctrl+L +
  type URL + Enter to the FOREGROUND browser via the input-lock path,
  NOT a fresh shell-open … First-ever open still launches."
- The fastpath/tool mapping ("search X on <site>" → navigate_url with the
  search URL) is brain-core's half (already dispatched by the coordinator).

## Impact
- Body: `body/win/act_launch.py` (reuse logic + input-lock injection),
  needs_lock=True (input injection — the dispatcher already arbitrates);
- Confirm-first only if the target tab can't be identified — in the shipped
  pick (foreground browser → topmost EnumWindows browser window → launch)
  the target is always deterministic, so no confirm path exists yet;
- Tests: reuse-foreground / reuse-non-foreground / launch-first fixtures on
  FakeWin + wave-4 failure-matrix auto-coverage (invalid/crash/locked).

# pc-control → brain-core: foreground-frame-consumer
Status: OPEN

## What
Consume the new body→brain `foreground` frame (declared in
`docs/PROTOCOL.md` §3 under the AUD-05 protocol-event grant, 2026-10-08) —
this is the PC half's counterpart that keeps the router's chat gate fed
while idle:

```jsonc
// role=body only, sent on WS connect (snapshot) + every focus change
{"type": "foreground", "v": 1, "ts": 1791461000000,
 "window": {"hwnd": 1002, "title": "Inbox - Thunderbird",
            "process": "thunderbird.exe", "pid": 4711} | null}
```

Proposed consumer (brain-core owns `brain/ws.py` + `brain/vision/context.py`):

1. On receipt, role == `body` only (other roles → `E_UNSUPPORTED` per §4):
   - `window is null` → treat as **unverifiable**: do NOT record (the ring
     must never carry an empty identity; router stays fail-closed — matches
     `gateway.foreground_window()` returning None for unverifiable);
   - else record exactly the identity shape the probes use
     (`brain/tools/computer_use/gateway.py:134` — `"title | process"`, both
     may be absent):
     `record_foreground(f"{window.get('title','')} | {window.get('process','')}".strip(" |"))`
     — consecutive-duplicate collapse + ts refresh already live in
     `brain/vision/context.py::record_foreground`, so the 60 s-fresh
     `_foreground_provider` (app.py lifespan) stays warm even with zero
     vision probes.
2. Private mode: propose NOT recording while private is on (mirrors probes,
   which stop) — your call, ring is local-only either way.
3. Optional: cache `{window, ts}` on the hub for `foreground_info`-style
   consumers; not required for the gate fix.

Producer guarantees (pc-control, tested):
- connect snapshot pushed right after `auth_ok` + on every focus change
  (Win32 `SetWinEventHook(EVENT_SYSTEM_FOREGROUND)` thread, 1 s poll
  fallback, 30 s force-resync);
- lock-free (`foreground_info` is `lock:false`) — no input lock, no
  `act_req` round trip;
- deduped (identical hwnd+title+process → no frame), retried on send
  failure; `body/win/foreground.py` + tests `test_pc_foreground.py`.

## Why
AUD-05 P0 (dispatch [32]): the gate's only feeder was the vision/CU probe
ring (<60 s fresh) → chat died all night with `E_OFFLINE` while idle
(`require_foreground=false` is the documented INTERIM and must be reverted
once this lands + brain-core caches). Router half (fail-closed) and
brain-core hook wiring are already merged; this closes the data source.

## Impact
- Additive frame handler (no transport change, no Core Guard semantics);
- brain-core-owned files (`brain/ws.py`, maybe `brain/vision/context.py`
  helper) — pc-control edits none of them; PROTOCOL row already landed per
  the coordinator's grant.

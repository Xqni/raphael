# pc-control → integrator: protocol-act-req-enum
Status: DONE

## Decision (coord inbox 2026-10-06, integrator)
APPROVED and APPLIED — docs/PROTOCOL.md §7 now lists `list_windows{}`,
`foreground_info{}`, `list_running_apps{}` with the read-only / `lock:false`
note and `foreground_info`'s privacy-gate role; no transport change. Closed by
pc-control: `PENDING_PROTO_ADDITIONS` emptied in
`body/win/actions.py` (conformance test now asserts registry == §7 enum
exactly), same branch as this closure.

## What
Extend the `act_req` action allow-list in `docs/PROTOCOL.md` §7 by three
read-only inspection actions (implemented + tested in the pc-control lane,
`body/win/actions.py`):

```
`list_windows{}` (hwnd/title/process/pid/rect/foreground per window),
`foreground_info{}` (current foreground window: title/process/pid),
`list_running_apps{}` (running processes grouped with window titles)
```

Proposed §7 line after `brightness{level}`, `notify{text}`:

> …, `brightness{level}`, `notify{text}`, `list_windows{}`, `foreground_info{}`,
> `list_running_apps{}` (read-only inspection: window/app enumeration —
> `foreground_info` feeds the `privacy.blocklist_apps` check before any
> screenshot leaves the machine).

No transport change: same `act_req`/`act_res` envelope, all three are
`lock:false`, non-destructive, and return structured JSON.

## Why
1. PROTOCOL §7 is an allow-list ("server never sends free-form … structured
   args only") — the Brain cannot legally send these until the enum lists
   them, yet:
2. the privacy gate in §7 needs `foreground_info` to match the foreground
   window against `privacy.blocklist_apps` BEFORE a screenshot is sent to
   cloud vision (Wave 2 exit criterion "What am I looking at"); and
3. the pc-control Wave 2 task list (docs/lanes/pc-control.md, session brief)
   explicitly asks for these three additions.
The pc-control lane tracks them in `body/win/actions.py
PENDING_PROTO_ADDITIONS` with a conformance test asserting the registry ==
§7 enum ∪ exactly these three; the test also asserts this request file exists.

## Impact
- Shared contract edit (integrator/protocol-architect only) — no Core Guard
  semantics touched (read-only actions, no input injection, no egress).
- Consumers: `brain/tools/pc/` already exposes them as LLM tools; once the
  enum lands, the request file can be closed and `PENDING_PROTO_ADDITIONS`
  emptied (the conformance test keeps passing either way).

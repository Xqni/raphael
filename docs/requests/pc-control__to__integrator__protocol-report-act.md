# pc-control → integrator: protocol-report-act
Status: DONE

## Decision (coord inbox 2026-10-07, integrator)
APPROVED AS PROPOSED — PROTOCOL §7 line updated BY THE INTEGRATOR'S HAND
(`report{op, title, body, format}`, fixed `Documents\Raphael\reports`,
slug+atomic, `lock:false`, length-only logs — security notes airtight: model
never picks a path). Verified b8955df clean, body 150 green, e2e 130 PASS.

## Implemented (pc-control, same merge)
`PENDING_PROTO_ADDITIONS` cleared to `()` in `body/win/actions.py`; the
conformance test now asserts the registry == §7 enum exactly (report included).

## What
Add ONE new Body action to the `docs/PROTOCOL.md` §7 allow-list — Report-format
delivery (Wave 5, pc-control lane task "Report-format delivery acts"):

```
`report{op}` — op: save | list.
  save {op, title, body, format?} — persist a Report-format output to the
      FIXED per-user folder `%USERPROFILE%\Documents\Raphael\reports\`
      (slugified timestamped filename; format md|txt|json, json is validated;
      atomic write). Returns {path, name, bytes, lines}.
  list {op}` — enumerate saved reports (name/bytes/mtime, newest first, cap 100).
  All `lock:false`, non-destructive, read-only outside that one folder.
```

Proposed §7 line addition after `list_running_apps{}`:

> …, `list_running_apps{}`, `report{op, title, body, format}` (Report-format
> delivery: save into `Documents\Raphael\reports` / list saved reports —
> fixed directory only, never an arbitrary path, `lock:false`).

Full rationale, security notes and shapes: body/win/act_report.py docstring +
brain/tools/pc/report.py spec (land on the same branch).

## Why
- Wave-5 lane task (docs/lanes/pc-control.md): delivery acts for the
  Answer/Report formats from docs/evolution/02 §3 — Report bodies
  (findings/evidence/confidence/next-steps) need to reach the user as a real
  file on the Windows box; "share/open" composes from EXISTING acts
  (`open_path`, `clipboard{write}`, `notify`), so `report{op}` is the only
  genuinely new capability.
- §7 is the server-side allow-list — the Brain cannot legally send `report`
  until the enum lists it. The act is implemented behind
  `body/win/actions.py::PENDING_PROTO_ADDITIONS = ('report',)` with the
  conformance test asserting this request file mentions the pending name.

## Security impact (none to Core Guard)
- Model CANNOT choose a path: fixed base directory, slugified title (no
  separators/traversal), fixed extension set, atomic write; `list` reads only
  that directory. No input injection, no delete, no network, `lock:false`.
- Action log treats `body` as content (length only) — reports never land in
  `logs/actions*.log`.

## Impact
- Shared contract edit (integrator/protocol-architect only). Apply at or
  BEFORE pc-control's Wave-5 merge (same pattern as the 2026-10-06 §7
  additions). `PENDING_PROTO_ADDITIONS` flips to `()` in my closing commit.

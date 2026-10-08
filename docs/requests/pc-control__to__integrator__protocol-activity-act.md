# pc-control → integrator: protocol-activity-act
Status: OPEN

## What
Add the F-3 journal act to the `docs/PROTOCOL.md` §7 allow-list:

```
`activity{op}` — op: list | log | undo.
  list {op, limit?} — newest-first REVERSIBLE journal entries
      {seq, ts, id, kind, act, job, summary, inverse, undone, undo}.
  log  {op, limit?} — orb-viewer view: EVERY executed act joined with
      reversibility {id, ts, job, action, args, ok, error, summary,
      reversible, undo, undone, undo_ok} (redacted args; read-only).
  undo {op, seq?, id?} — invert the newest undoable entry, or target one
      by journal seq or stable id (seq XOR id); inverse applies FIRST,
      success marks undone (ok:true marker), failure marks undo_ok:false
      and changes nothing.
  lock:false, no confirm category (journaling adds NO confirmation bypass —
  every act keeps its existing risky/confirm metadata, AGENT_RULES §8).
```

Proposed §7 line addition after `report{op, title, body, format}`:

> …, `report{op, title, body, format}`, `activity{op, limit, seq, id}`
> (F-3 undoable-act journal: query — reversible list / full orb activity
> log — and inverse-apply for reversible acts; `lock:false`, append-only
> JSONL store; entry ids stable across restarts).

Implementation + schema: `body/win/journal.py`, `body/win/act_activity.py`;
tracked via `PENDING_PROTO_ADDITIONS = ('activity',)` (conformance test
asserts this file mentions the pending name).

## Why
- Audit F-3 (docs/AUDIT-2026-10-07, packet docs/audit-tasks/pc-control.md):
  "undoable-act journal (inverse ops for reversible acts; schema + tests);
  orb renders the viewer." The undo executor must live in the Body (it owns
  the Windows state); orb/CLI query reach it through brain-core's relay
  (request pc-control__to__brain-core__activity-endpoint.md).
- §7 is the server-side allow-list — `activity` cannot be sent until listed.

## Impact
- Shared contract edit (integrator only). Read-mostly act; `undo` only
  RESTORES prior state (never destructive). No Core Guard semantics change.

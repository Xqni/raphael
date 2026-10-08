# pc-control → orb: activity-viewer-schema
Status: SUPERSEDED (integrator 2026-10-08)

## What
Co-share contract for the F-3 activity viewer (packet: "CO-SHARE with orb …
orb renders the viewer"). pc-control owns the journal + inverse ops + schema;
this file is the render-side spec. Data source once brain-core's relay lands
(pc-control__to__brain-core__activity-endpoint.md):
`GET /activity?limit=20`.

### Entry schema (JSON, append-only journal — `body/win/journal.py`)
```json
{"seq": 42,                      // monotonic id (undo targets this)
 "ts": 1791429000000,            // ms epoch (display: relative "2 min ago")
 "kind": "volume|brightness|window|recycle_move",   // open enum
 "act": "volume",                // act_req action that produced it
 "job": "j_20261007_0042",       // producing job (null for seeds/imports)
 "summary": "volume 55 -> 42",   // one-line human text (safe to render)
 "inverse": {...},               // opaque to the viewer (restore payload)
 "undone": false,                // true after a successful undo
 "undo_seq": 43}                 // present once undone (marker seq)
```

### Viewer rules
- Render newest-first from `GET /activity`; show `summary`, relative `ts`,
  and an **Undo** affordance only when `undone == false` AND `kind` has an
  inverse handler (today: volume/brightness/window; `recycle_move` is
  reserved — never render Undo for unknown kinds).
- Undo → `POST /activity/undo {"seq": n}`; on 503 (body offline) show
  "Body offline" and keep the entry un-undone (server state is truth).
- After a successful undo the entry flips `undone: true` — re-fetch or use
  the response's `{seq, kind, summary}` to update in place.
- Never render `inverse` internals; `summary` is pre-sanitized (no screen
  content, no paths from other acts).

## Why
F-3 audit (docs/AUDIT-2026-10-07): schema + tests land in pc-control (done
on my branch: `body/win/journal.py` + `body/win/tests/test_pc_journal.py`),
viewer is orb-owned. Written as a request so the contract is reviewable
before either side renders/relays it.

## Impact
- No code on pc-control's side depends on orb; orb may render lazily from
  the endpoint once it exists (additive UI).

## Decision (integrator 2026-10-08): SUPERSEDED BY THE SIGNED AGREEMENT
The canonical F-3 wire contract is docs/requests/orb__to__pc-control__act-journal-schema.md
("Agreement (pc-control, 2026-10-08) — ACCEPTED with 3 corrections", Status DONE):
12-field entries, undo by journal seq (id accepted alongside), REST
`POST /activity/<id>/undo`, no §3 frame. THIS file's earlier shape
(seq/kind/inverse/undo_seq, `POST /activity/undo {seq}`) predates that
agreement and must not be implemented — orb flagged the divergence correctly
(orb realigned ACTIVITY-VIEWER.md to the signed agreement). pc-control: flip
any consumers/notes to the agreement file; brain-core's GET/POST /activity
relay implements the SIGNED shape only.

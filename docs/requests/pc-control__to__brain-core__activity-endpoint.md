# pc-control → brain-core: activity-endpoint
Status: OPEN

## What (updated 2026-10-08 — orb agreement landed)
Relay endpoints so the orb/CLI can query the F-3 activity view
("with an API the orb/CLI can query") — shape per the AGREEMENT in
`docs/requests/orb__to__pc-control__act-journal-schema.md` (Status DONE):

```
GET  /activity?limit=30  -> relay act_req {action:"activity",
                            args:{op:"log", limit}}  -> {"ok": true,
                            "entries": [<orb entry shape: id, ts, job,
                            action, args, ok, error, summary, reversible,
                            undo, undone, undo_ok>}]}   (newest first)
POST /activity/{id}/undo -> relay act_req {action:"activity",
                            args:{op:"undo", id:"a_..."}}
                            -> {"ok": true, "entry": {...undone entry...}}
                            error mapping (UndoError text -> orb codes):
                              "no journal entry"   -> E_NOT_FOUND
                              "already undone" /
                              "no inverse handler" -> E_NOT_REVERSIBLE
                              BackendError (set
                              failed / busy)       -> E_BUSY
```

Both: token-auth (`token_auth`, same as /jobs), implemented exactly like the
loop's gui path (register waiter BEFORE broadcast, `lock: false`, 5 s
timeout, no body session -> 503 `{"error":"body offline"}`):

```python
fut = engine.expect_act(jid)
hub.broadcast({'type': 'act_req', 'v': 1, 'job': jid, 'action': 'activity',
               'args': {'op': 'log'|'undo', 'limit'?, 'id'?},
               'lock': False, 'timeout_ms': 5000}, roles={'body'})
res = await engine.await_act_res(fut, jid, timeout=5.0)
```

Earlier draft relayed `op:"list"` (journal-only) — the agreement needs the
FULL per-act view: `op:"log"` joins the §7 action log with the reversibility
overlay Body-side (both files live on the Windows host, so Brain must ask,
not read).

Depends on the §7 entry landing (pc-control__to__integrator__
protocol-activity-act.md, same batch).

## Why
- F-3 co-share: pc-control owns journal + inverse ops + schema; the orb
  renders the viewer (pc-control__to__orb__activity-viewer-schema.md) and
  needs this data path — orb/CLI speak Brain REST, never the Body directly.
- Keeps confirmation/lock semantics untouched: `lock:false`, read/restore
  only; no new model-facing surface beyond the existing `activity` tool.

## Impact
- brain-core-owned `brain/app.py` addition (additive, token-gated,
  localhost-only — PROTOCOL §11 unchanged). Fails soft when the body is
  offline (503), never blocks other routes.

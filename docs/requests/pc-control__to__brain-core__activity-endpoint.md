# pc-control → brain-core: activity-endpoint
Status: OPEN

## What
Relay endpoints so the orb/CLI can query the F-3 undoable-act journal
without going through an LLM turn (packet: "with an API the orb/CLI can
query"):

```
GET  /activity?limit=20   -> {"count": N, "entries": [journal entries]}
POST /activity/undo       -> {"undone": {seq, kind, summary}}
                             body optional {"seq": int} (default newest)
```

Both: token-auth (`token_auth` dependency, same as /jobs), and implemented
by sending an `act_req` to the body exactly like the loop's gui path:

```python
fut = engine.expect_act(jid)          # register waiter BEFORE send
hub.broadcast({'type': 'act_req', 'v': 1, 'job': jid, 'action': 'activity',
               'args': {'op': 'list'|'undo', 'limit'?, 'seq'?},
               'lock': False, 'timeout_ms': 5000}, roles={'body'})
res = await engine.await_act_res(fut, jid, timeout=5.0)
# no body session -> 503 {"error": "body offline"} (viewer shows stale/empty)
```

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

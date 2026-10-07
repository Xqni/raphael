# qa-security → integrator: ws-query-token
Status: OPEN

## What
`brain/ws.py::handle()` accepts the upgrade token from the query string:
```python
up_token = ... or ws.query_params.get('token')
```
Query-string secrets are the canonical log-leak vector: uvicorn's access log
(default `log_level='info'` in `brain/run.py`) logs the request line including
query, so `ws://…/ws?token=…` prints the token to stdout/journal — violating
PROTOCOL §11 ("Token never appears … in logs"). The header-based upgrade check
(`X-Raphael-Token` / `Authorization`) already exists next to it.

Proposed change: drop the `query_params.get('token')` branch (keep header +
the §2 frame auth). If some client needs URL injection at launch, pass it via
header at connect (the orb launch path already injects the token outside
argv — verify it uses a header or the auth frame, not a query URL).

## Why
Review §1.3 B3 / §1.5 S3. No in-repo client uses `?token=` (body/orb use the
auth frame), so removal is behavior-neutral.

## Impact
Touch: `brain/ws.py` — **integrator-owned** (OWNERSHIP default), Core Guard
adjacent (auth) → your call; qa-security will drop nothing on its side (no
test depends on the query path — `test_ws_upgrade_wrong_token_refused_immediately`
uses the header).

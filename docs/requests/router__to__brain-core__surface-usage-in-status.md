# router → brain-core: surface router usage/rate tracking in GET /status
Status: OPEN

## What
Add the router's Wave-3 usage block to your `GET /status` handler
(`brain/app.py:216-220`, brain-core-owned):

```python
# AFTER (proposed)
from brain.router import usage_status          # top-level import, next to the others

@app.get('/status')
async def status(auth: bool = Depends(token_auth)) -> Dict[str, Any]:
    engine = get_engine()
    router_block: Dict[str, Any] = {}
    try:
        router_block = await usage_status()    # never raises / never hits network
    except Exception:                          # noqa: BLE001 — /status must stay up
        router_block = {"error": "unavailable"}
    return {'ok': True, 'server_v': SERVER_V1, 'mode': get_mode().label(),
            'sessions': get_hub().session_counts(), 'router': router_block,
            **engine.stats()}
```
(Correction: keep your existing `SERVER_V` constant — only the `'router': router_block`
line is the actual change.)

`brain.router.usage_status()` (already implemented + tested by this lane) returns:

```json
{"window_hours": 24, "log": "<repo>/brain/router/usage.jsonl",
 "calls": {"total": n, "ok": n, "errors": n},
 "tokens": {"input": n, "output": n},
 "by_provider": {"groq": {"calls", "errors", "input", "output"}, ...},
 "by_purpose":  {"chat"|"tool"|"vision"|"stt"|"ack": {...}, ...},
 "errors":      {"E_PROVIDER_429": n, ...},
 "providers":   {"groq": {"circuit": "closed|open|half-open", "cooldown_s": s,
                          "rpm": {"used","cap","window_s"},
                          "tpm": {"used","cap","window_s"}, "last_error": ...}, ...},
 "vision_paid": {"cap_usd", "spent_usd", "calls", "exhausted", "date"}}
```
(`vision_paid` only present while `providers.allow_vision_paid` is on.)

## Why
- docs/lanes/router.md Wave-3 goal: "usage/rate tracking surfaced in `/status`" —
  the aggregator lives in `brain/router/status.py` + `Router.usage_status()`, but the
  endpoint file is yours (AGENT_RULES §2: I propose, you edit).
- Supervisor/CLI get provider health, budget burn and error mix for free — no new
  endpoint, no protocol change (it is additive; existing consumers read keys).

## Impact
Additive key in the `/status` payload only. The function reads a local file + in-memory
state: **no network, no keys, never raises** (corrupt/missing log → zeroed window;
tests: `brain/router/tests/test_status.py`, 8 green). Nothing in PROTOCOL.md changes.

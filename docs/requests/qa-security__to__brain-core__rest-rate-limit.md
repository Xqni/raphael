# qa-security → brain-core: rest-rate-limit
Status: OPEN

## What
PROTOCOL §2: "REST: `Authorization: Bearer <token>` header (or
`X-Raphael-Token`). **Same token, same rate limiting.**" — `brain/app.py`
`token_auth` is a bare `check_token()`: no per-IP request limiter and no
auth-fail ban for REST (the WS hub has both: 40 msgs/s + ≥5 fails/60 s →
`E_AUTH_RATE`).

Proposed change: a small ASGI/dependency limiter mirroring the WS numbers —
failed REST auths recorded per client IP into the same ban structure as
`WsHub._record_auth_fail` (reuse or extract), returning **429** on exceed;
optionally a coarse RPS cap per IP. Keep it dependency-free.

## Why
Unlimited token guessing over REST (localhost today, but the surface exists
and §2 promises it). Pinned by xfail
`tests/contract/test_auth.py::test_rest_auth_fail_rate_limited`.

## Impact
Touch: `brain/app.py` (+ maybe `brain/ws.py` for the shared ban map —
ws.py is integrator-owned → co-sign). Wire shape unchanged (status 429 +
`{"detail": …}`).

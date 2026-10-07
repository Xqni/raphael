# qa-security → brain-core: disable-fastapi-docs
Status: OPEN

## What
`brain/app.py` builds `FastAPI(lifespan=lifespan)` with default docs —
`GET /docs`, `/redoc`, `/openapi.json` answer **without any token** on the
bound interface (0.0.0.0 in WSL NAT mode). PROTOCOL §11: "Everything is
localhost-only; no other listeners" + token-gated surface intent.

Proposed change (one line):
```python
app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
```
(or gate them behind `token_auth` if the debug UI is wanted during dev).

## Why
Unauthenticated API-surface disclosure (endpoint list + schemas) on a service
that binds 0.0.0.0; also makes accidental public-schema probing trivial.
Pinned by xfail
`tests/security/test_core_guard_and_secrets.py::test_only_expected_routes_exist`.

## Impact
Anyone using /docs for local dev loses it (openapi_url=None also disables
client-codegen tooling — if that matters, gate instead of disable).

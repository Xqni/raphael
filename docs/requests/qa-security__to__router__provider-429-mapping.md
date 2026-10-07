# qa-security → router: provider-429-mapping
Status: OPEN

## What
`brain/router/core.py::complete()` catches every `_chat` exception generically
and returns `error_code="E_PROVIDER_5XX"` — including HTTP **429** from the
provider. PROTOCOL §10 defines `E_PROVIDER_429 (rate limit)` as the retryable
code for this case; clients never see it.

Proposed change: in the exception handler, inspect `urllib.error.HTTPError`:
```python
except error.HTTPError as e:
    code = {429: "E_PROVIDER_429", 401: "E_PROVIDER_AUTH",
            403: "E_PROVIDER_AUTH"}.get(e.code, "E_PROVIDER_5XX")
    ... error_code=code
```
(401/403 → `E_PROVIDER_AUTH` is the same gap class — fatal, not retryable.)

## Why
Retry semantics are per-code (§10): callers/backoff must distinguish a
transient 429 from a 5xx. Pinned by xfail
`tests/contract/test_error_codes.py::test_provider_429_maps_to_e_provider_429`.

## Impact
Touch: `brain/router/core.py` only; `CallResult` shape unchanged. The xfail
flips green; llm.plan already passes `error_code` through to the job error.

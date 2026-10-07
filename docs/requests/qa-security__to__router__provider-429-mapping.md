# qa-security → router: provider-429-mapping
Status: DONE

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

## Decision (router, 2026-10-07)
DONE — implemented by the Wave-2 router rewrite; your tripwire confirms it:
- Status→code mapping now lives in `brain/router/errors.py::code_for_status`
  (401/403 → `E_PROVIDER_AUTH`, 429 → `E_PROVIDER_429`, 5xx → `E_PROVIDER_5XX`,
  408 → `E_TIMEOUT`), used by every provider path (`openai_compat`, `ollama`,
  stream + multipart), and `complete()` passes the raised `RouterError.code`
  straight into `CallResult.error_code` (no generic 5XX collapse anymore —
  there is no raw `urllib` exception path left: HTTP statuses come back as
  responses, not exceptions).
- Verified just now: `tests/contract/test_error_codes.py::test_provider_429_maps_to_e_provider_429`
  is **PINNED STRICT and PASSES**; `brain/router/tests/test_resilience.py`
  additionally pins exhaustion codes end-to-end (401 → `E_PROVIDER_AUTH` fatal,
  429 storm → `E_PROVIDER_429` retryable, 5xx → `E_PROVIDER_5XX`, dead network →
  `E_OFFLINE`) — parametrized, mock only.
- Remaining tripwire `test_circuit_open_code_is_catalogued` is NOT mine to flip:
  it needs `E_CIRCUIT_OPEN` in PROTOCOL §10 (shared contract). Your request
  `qa-security__to__integrator__circuit-open-code.md` is the right vehicle —
  router maps circuit-open to `E_OFFLINE` today (§10 transient) and will switch
  to `E_CIRCUIT_OPEN` in one commit if the integrator adds the code.

# qa-security → integrator: circuit-open-code
Status: OPEN

## What
`E_CIRCUIT_OPEN` (router circuit-breaker open) flows to clients as an
`error` frame code / job `error_code` when the chain's breaker is open, but it
is **not in the PROTOCOL §10 catalog**. Two acceptable fixes (protocol owner's
call):
- (a) router maps circuit-open → `E_PROVIDER_5XX` (or `E_OFFLINE`) before it
  reaches the seam — then §10 stays as-is; or
- (b) add `E_CIRCUIT_OPEN` to §10 and classify it retryable (transient,
  closes after the breaker timeout).

qa-security's recommendation: (b) — it is observably distinct and clients
already may want to show "provider cooling down"; but either is contract-valid.

## Why
§10 is the closed set clients parse (`tests/contract/test_error_codes.py`
asserts every wire code ∈ catalog — currently xfail:
`test_circuit_open_code_is_catalogued`). An unknown code breaks the §10
"detail shown only for listed codes" rule.

## Impact
If (b): PROTOCOL.md §10 line + qa-security updates the catalog test (green
either way once decided). If (a): router changes one branch — file there too.

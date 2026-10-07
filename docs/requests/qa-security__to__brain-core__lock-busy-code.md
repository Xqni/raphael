# qa-security → brain-core: lock-busy-code
Status: OPEN

## What
When the Body answers `act_res{ok:false, error:"E_LOCK_BUSY"}`,
`loop.py` raises `RuntimeError(f"Body action failed: …")` and the job fails
with `error_code='E_INTERNAL'`. PROTOCOL §10 classifies `E_LOCK_BUSY` as
**retryable**, and §7 says "Brain handles queuing at job level" — the client
should see `E_LOCK_BUSY` (and ideally the job should retry/queue rather than
hard-fail).

Proposed change (minimal): map known act errors through before failing:
```python
code = res.get('error') if res.get('error') in ('E_LOCK_BUSY', 'E_TIMEOUT', ...) else 'E_INTERNAL'
```
(Queue/retry semantics can come later; the honest code first.)

## Why
Retryable codes must reach clients (§10), else backoff/retry UIs can't work
and dashboards count provider bugs as internal errors. Pinned by xfail
`tests/regression/test_act_pipeline.py::test_lock_busy_reported_as_e_lock_busy`.

## Impact
Touch: `brain/loop.py`. Job outcome unchanged today (still fails), only the
code — the follow-up (queue-at-job-level) is a separate, larger change.

CI heavy first run - tests-heavy workflow
Run ID: 37702802093 (workflow_dispatch trigger)

Status: completed
Conclusion: failure

Jobs:
1. Full battery (all suites, one runner) - conclusion: failure
2. Orb npm gates (node only) - conclusion: failure

Failure details:

Job: Full battery (all suites, one runner)
- Failed test: brain/vision/tests/test_service.py::test_missing_router_seam_degrades
- Root cause: assertion expects 'E_OFFLINE' in output but got 'Vision is unavailable right now (E_PROVIDER_AUTH).'
- This indicates the missing router seam degradation behavior now returns a different error code/message (E_PROVIDER_AUTH) than the test expects (E_OFFLINE). Could be due to a code change affecting how missing router/vision_fn is degraded in the fresh CI environment, or the error classification logic changed. Requires code/test alignment.

Job: Orb npm gates (node only)
- Failed at: actions/setup-node@v4 caching step
- Root cause: "Some specified paths were not resolved, unable to cache dependencies." with cache-dependency-path: body/orb/package-lock.json. The lockfile path may not exist or not be resolvable in the fresh checkout, causing setup-node to fail when trying to resolve cache paths. The workflow may need to handle missing lockfile or use a different cache strategy for this job.

Summary: Both jobs failed - one due to a behavioral/test expectation mismatch in vision service error messaging, and one due to npm cache resolution of a potentially missing lockfile.

## Round 2
- Run: 37703322866 (workflow: tests-heavy, repo: <repo-root>)
- Status: completed, conclusion: success
- Created → Updated duration (approx): 188s (~3m 8s)
- Jobs:
  - Full battery (all suites, one runner): success
  - Orb npm gates (node only): success
- Failure details: none (both jobs passed). Root causes from Round 1 fixed (deterministic missing-seam vision test + tracked package-lock.json).
## Dispatch-chain optimization run
run_id: 37716474814
conclusion: success
status: completed
jobs:
- Full battery (all suites, one runner): success
- Orb npm gates (node only): success
duration_polls: 2 rounds (90s)
timestamp: 2026-10-07T21:12:52-05:00

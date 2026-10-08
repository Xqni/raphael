# CI Encoding Fix — Green

Run ID: 37618571343
Commit: [integrator] fix(ci): conformance PROTOCOL parser forces encoding=utf-8
Status: completed
Conclusion: success
Started: 2026-10-07T12:05:39Z
Duration: ~43s

Jobs:
- Ubuntu — brain + mock suites: success
- Windows — Body unit tests (no GUI): success

Notes:
- Conformance PROTOCOL parser now forces encoding=utf-8; CI passes both jobs.

## Final wave-4/5 pushes
37643487507 ccee742 wave-5 lane rewrites — status: completed/failure; jobs: Protocol conformance (ubuntu-latest)=completed/success, Protocol conformance (windows-latest)=completed/success, Windows Body unit tests (no GUI)=completed/success, Ubuntu brain+mock suites=completed/failure
37643429802 6a96b70 wave-4 gate — status: completed/failure; jobs: Windows Body unit tests (no GUI)=completed/in_progress? (waited — see above), but poll showed completed/failure overall with ubuntu job completed/failure; full details: Protocol conformance (ubuntu-latest)=completed/success, Protocol conformance (windows-latest)=completed/success, Windows Body unit tests (no GUI)=completed/success, Ubuntu brain+mock suites=completed/failure

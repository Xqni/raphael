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

## Final pre-audit runs
- 37710212877 (d97b8470250ca70d908fde0867f7d1731dee552c, CI) — status: completed/failure; conclusion: failure. Failed step: "full brain suite (import-hygiene + order-dependent guards)" (job "Ubuntu — brain + mock suites"); 9 failures in brain/voice/* due to ModuleNotFoundError: No module named 'soundfile'. Protocol conformance (ubuntu-latest/windows-latest) passed; Windows — Body unit tests (no GUI) passed. Conclusion: NOT green overall due to missing test dependency (voice tests failing in full suite).
- 37710210183 (1496d67daa61fd2e2a51816cf73912f4f624e57e, CI) — status: completed/failure; conclusion: failure. Same failure pattern: "full brain suite (import-hygiene + order-dependent guards)" fails with 9 ModuleNotFoundError: No module named 'soundfile' in brain/voice tests (personality_delivery.py + voice_path.py). Protocol conformance (ubuntu-latest/windows-latest) passed; Windows Body unit tests passed. Conclusion: NOT green overall due to missing test dependency.
Earlier failure (37710067102) confirmation: the stale contract test causing the previous config refactor failure was tests/contract/test_config_loader.py::test_load_config_parses_repo_config_yaml (AssertionError). That specific contract test is now fixed by commit 1496d67 (which adjusted config loader behavior); the remaining failures in the latest runs are NEW in nature relative to that contract test (voice audio dependency 'soundfile' missing in full suite environment), not the stale test_config_loader failure recurring.


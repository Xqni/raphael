---
run_id: 37795171680
workflow: CI (on main)
head_sha: 8370f05620430a6d12198ec25625e3f51de23130
status: completed
conclusion: success
checked_at: 2026-10-08T14:53:00Z

tests-heavy (same head):
- run_id: 37791936216
- workflow: tests-heavy.yml
- status: completed
- conclusion: success
- created_at: 2026-10-08T14:22:34Z
- url: https://github.com/<gh-owner>/raphael/actions/runs/37791936216

jobs:
- name: Ubuntu — brain + mock suites
  status: completed
  conclusion: success
  duration: ~5m 47s
  url: https://github.com/<gh-owner>/raphael/actions/runs/37795171680/job/113372627499
- name: Protocol conformance (ubuntu-latest)
  status: completed
  conclusion: success
- name: Security scanners (gitleaks / pip-audit / bandit / npm audit)
  status: completed
  conclusion: success
- name: Windows — Body unit tests (no GUI)
  status: completed
  conclusion: success
- name: Protocol conformance (windows-latest)
  status: completed
  conclusion: success

failing_details: null

verdict: GATE_TIP_GREEN
cause: all jobs succeeded (CI + tests-heavy for head)

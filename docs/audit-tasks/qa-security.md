# qa-security — Wave 5H audit packet (from docs/AUDIT-2026-10-07.md)

**VERIFY-FIRST RULE (non-negotiable):** every finding is a HYPOTHESIS from a docs-only
audit. Before changing ANY code: quote the exact `file:line` (verbatim), then report
one of **CONFIRMED / NOT-APPLICABLE / ALREADY-DONE** in your task_done event, with the
quote inline. Unverified findings are never applied. Scope = ONLY the IDs below.
**QA-4 (new rule):** every wave_done you post MUST link a green CI run
(`gh run list --workflow=ci.yml` → run id) — without it the wave_done is bounced.
Run heavy suites in the CLOUD (`gh workflow run tests-heavy.yml`), one local suite at
a time (Rule 14). Stack stays DOWN — spawn it only for your own live test, tear down
after (user policy 2026-10-07). Speed binds (Rule 15); cost is not a factor.


| ID | Sev | Finding + first-look hints |
|----|-----|------------------------------|
| **QA-1** | P0 | CI scanners: gitleaks (+custom username/path/IP patterns), pip-audit (tests/requirements.txt), npm audit (body/orb), bandit|semgrep, Dependabot — in ci.yml (yours), both OSes stay green, fail ONLY on real findings (documented suppressions). Evidence = green run ids. |
| **QA-2** | P1 | property/fuzz: act_req parser, confirm.py, wake gate — seeded/bounded, mock-only. |
| **QA-3** | P1 | nightly cron sweep + golden-transcript evals (revive your old unchecked bullet; 2-3 transcripts from wave-2/3 e2e logs). |
| **QA-4** | P1 | support the integrator rule 'wave_done must link a CI run': make it machine-checkable where feasible + send the coord-schema note to integrator. |
| **SEC-7** | MED | CO-SHARE (CI side): workflow-level integrity invariants you can enforce; human enables branch protection (ATTENTION). |

Report format (in your task_done event): `ID: STATUS — `file:line` quote …`.

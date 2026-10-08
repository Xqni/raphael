# tools-memory — Wave 5H audit packet (from docs/AUDIT-2026-10-07.md)

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
| **SEC-4** | HUMAN | WRITE docs/security/pat-scope.md: fine-grained PAT, Selected repositories ONLY, Contents/Actions/PRs RW, NO Administration, NO org perms, expiry <=90d, rotation steps. Human applies it (ATTENTION). Optional: value-blind PAT-presence checker (never prints the token). |
| **F-2** | P2 | Predator-style skill acquisition on the EXISTING skills infra (wave-5 loader/dedup/confidence-gate landed): observe failed task -> draft skill -> confidence gate -> publish; mock tests only. |

Report format (in your task_done event): `ID: STATUS — `file:line` quote …`.

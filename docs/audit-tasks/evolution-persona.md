# evolution-persona — Wave 5H audit packet (from docs/AUDIT-2026-10-07.md)

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
| **SEC-7** | P0-control | DO FIRST: request to integrator proposing the Core Guard manifest EXPANSION (tools/conductor/**, .github/workflows/**, docs/OWNERSHIP*.md, boot/root scripts, scripts/win/*.ps1 → tests/core_guard.py --update runs at merge) + a spec for untrusted control-plane messages (structured fields, size caps, never execute/merge on prose) that the integrator applies to conductor code. |
| **F-1** | P2 | first evolution loop in PROPOSE mode on a harmless target (docs/mock-test tweak): proposal file ONLY, never auto-apply; before/after + quality report. |
| **F-6** | P2 | Ciel promotion checklist (tier unlock -> config.d flip -> voice slot -> orb theme verify) + status of the two open Ciel requests. |

Report format (in your task_done event): `ID: STATUS — `file:line` quote …`.

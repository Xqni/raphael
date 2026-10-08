# orb — Wave 5H audit packet (from docs/AUDIT-2026-10-07.md)

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
| **ARCH-1** | P1 | PLAN ONLY (human gate: Node-on-Windows = ATTENTION): docs/orb/WINDOWS-NATIVE-PLAN.md — Windows-native Electron migration, parity checklist (drag/persistence/transparency/hotkeys/mutex/CDP), rollback. No installs/code until approved. |
| **F-3** | P2 | CO-SHARE: activity-viewer render — agree the act-journal schema with pc-control via docs/requests; viewer in menu area; mock-brain tests only. |
| **F-4** | P2 | usage/rate headroom rows in the right-click menu (native menuSpec path; no new frames) from router's accessor. |

Report format (in your task_done event): `ID: STATUS — `file:line` quote …`.

# pc-control — Wave 5H audit packet (from docs/AUDIT-2026-10-07.md)

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
| **SEC-9** | LOW | runtime pip-install in YOUR body paths: quote every _ensure_pkg/pip install; pre-installed hashed venv or fail-loud; coordinate voice for shared helpers. |
| **F-3** | P2 | CO-SHARE with orb: undoable-act journal (inverse ops for reversible acts; schema + tests); orb renders the viewer. |

Report format (in your task_done event): `ID: STATUS — `file:line` quote …`.

# router — Wave 5H audit packet (from docs/AUDIT-2026-10-07.md)

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
| **SEC-8** | MED | expected ALREADY-DONE: quote brain/router/core.py vision() DailySpend enforcement lines + run/vision_paid_daily.json persistence (grep vision_paid_daily|DailySpend|exhausted). CONFIRMED with quotes, or fix the ledger-write-failure gap. Feeds qa's SEC-8 tripwire. |
| **ARCH-5** | P1 | CO-SHARE: router-side contribution to the cloud-primary design note (chain/role_hints/usage accounting). |
| **F-4** | P2 | usage headroom accessor for the orb menu: quote usage_status() and shape a compact JSON (per-provider RPM/TPM headroom + today's spend); orb renders. |

Report format (in your task_done event): `ID: STATUS — `file:line` quote …`.

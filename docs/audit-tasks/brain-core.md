# brain-core — Wave 5H audit packet (from docs/AUDIT-2026-10-07.md)

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
| **SEC-3** | HIGH | P0 CO-OWNER: quote your layer of the fail-open chain (ws.py audio_end -> voice.transcribe_result(reason=) -> activation gate; file:line). Fix your half with voice (they own activation/stt); your tripwire: test proving NO cloud transcribe when gate undecided (SEC-3 exit criterion). |
| **ARCH-5** | P1 | design note: promote cloud_temp from 'temporary pivot' to primary profile shape + hybrid CPU-only local helpers (TTS stays local). Design only, no code. |
| **ARCH-6** | P1 | CO-SHARE: structured logs + uniform latency timestamps in brain (app.py/loop.py/ws.py emission points); value-blind. |

Report format (in your task_done event): `ID: STATUS — `file:line` quote …`.

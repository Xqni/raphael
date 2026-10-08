# computer-use — Wave 5H audit packet (from docs/AUDIT-2026-10-07.md)

**VERIFY-FIRST RULE:** quote exact `file:line`, then CONFIRMED / NOT-APPLICABLE /
ALREADY-DONE in your task_done. Unverified findings are never applied. Scope = IDs below.
**QA-4:** link a green CI run with every wave_done. Heavy suites in cloud
(`gh workflow run tests-heavy.yml`); stack down (spawn only for your test); Rule 15.

| ID | Sev | Finding + first-look hints |
|----|-----|------------------------------|
| **SEC-3 (egress co)** | HIGH | Your half of the fail-open pre-STT/egress surface: vision/observation EGRESS tripwire — a test proving NO image/foreground data leaves the machine when the gate is undecided/blocked (pair with voice+brain-core's STT tripwire; quote brain/tools/computer_use/gateway.py + brain/vision/gate.py decision points). |
| **SEC-3 (context)** | MED | sensitive-context detection: verify blocklist + redact gate coverage for gather_context payloads (quote brain/vision/context.py gates); add the missing-detected-context case if the audit's hypothesis holds. |
| **QA-2 (fixtures)** | P1 | untrusted/injection fixtures for your observation pipeline (as_untrusted wrapping of window titles/OCR-ish strings — quote where as_untrusted is applied; add fixtures for the gaps). |
| **ARCH-6 (vision)** | P1 | vision latency/cost report: from run/vision_paid_daily.json + your gate probes — a one-page report (latency, cost/day, cap headroom); value-blind. |

Report format: `ID: STATUS — `file:line` quote …`

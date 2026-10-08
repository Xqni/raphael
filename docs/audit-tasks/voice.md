# voice — Wave 5H audit packet (from docs/AUDIT-2026-10-07.md)

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
| **SEC-3** | HIGH | P0: always-listen + cloud STT may upload VAD segments BEFORE the wake gate; pre-STT gate FAIL-OPEN. Quote brain/ws.py audio_end path + brain/voice/activation.py should_transcribe/fail-open + stt.py transcribe_result(reason=). FIX: fail-closed when gate state unknown (no cloud upload without wake/ptt verdict); PTT/wake keep working; tripwire test proving no provider call when undecided (gate exit criterion). |
| **SEC-9** | LOW | runtime pip-install: quote _ensure_pkg/pip install calls on the voice path; pre-install into the fish/voice venv (hashed) or fail-loud. |
| **F-5** | P1 | CLOSE-OUT: eval exists (brain/voice/EVAL-pockettts.md) + user decided 'we keep fish'. Write the one-page decision record (blind A/B protocol + latency threshold, reopen PocketTTS only post-RAM-upgrade) and report ALREADY-DONE — or leave OPEN with evidence if you disagree. |

Report format (in your task_done event): `ID: STATUS — `file:line` quote …`.

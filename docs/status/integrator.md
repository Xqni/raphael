# integrator — status

Updated: 2026-10-09 (repo-wide freshness pass; supersedes the 2026-10-05 bootstrap text)

## Done
- Waves 2, 3, 4, 5 gated and tagged (`wave-3-gate`, `wave-4-gate`, `wave-5-gate`); **Wave-5H audit hardening sprint complete and tagged `wave-5h-gate`** (record + five exit-criteria evidence in `docs/WAVES.md`).
- All 10 lanes merged in WAVES order for the wave-5H board AND the cycle-2/post-gate batches; every `wave_done` carried a green CI id (QA-4); ownership/Core Guard/scanners enforced on every merge.
- Live security gate: `require_foreground=true` end-to-end (body SetWinEventHook push → brain-core cache → router fail-closed), verified live with the refusal path pinned by tests.
- Speed work landed: Go session-header fix (was silently failing over to slow free tier), fast-role tier, turbo-STT seam, voice P0 drift fix (2/10 → 10/10), STT latency packet (Cut A/B) with an honest recorded floor.
- Security/scanner posture: SEC-1 strict gate wired into CI/tests-heavy (FAIL-only), gitleaks baseline policy regens with reasons, personal-data scrub of integrator slice → repo-wide 0 FAIL-severity outside the allowlisted ledger.
- Process repairs: keepalive cron PATH fix (OPENCODE_BIN), ownership merge-base CI derivation, import-order test hardening, Core Guard dirty-pin incident + relay zombie-listener fix (all documented in `PROGRESS.md`).
- Electron 30.5.1 → 44.5.1 merged on orb's vetted verdict (6 vulns incl. ASAR HIGH → 0).
- Docs: `docs/HANDOFF-2026-10-09.md` (fresh-joiner map), README/TODO/BUGS refresh, lane status freshness sections, AUDIT register statuses updated from merged evidence.

## Wave 5U (USEFUL-NOW sprint, opened 2026-10-10 — current)
- Charter `docs/USEFUL-NOW-PLAN.md` committed; AGENT_RULES rule 16 (scoped constraint lifts: local Kokoro TTS + faster-whisper STT, confirm cards in chat UI + orb).
- Main reds cleared ×3 (tier-default test, gitleaks baseline, go-first chain restore per owner decision) → main green run 38029764736.
- Wave A merges (5U fixed order): **1. brain-core `c5e131f`** (P1 tier runtime, navigate pairing, P3 confirm policy LIVE, P0 batch: typed_confirm/needs_confirm/input-lock admission/foreground legibility/derived latency), **2. pc-control** (navigate_url in-place act + confirm-class tags on all pc tools, green 38030219227).
- Integration collision fixed: brain-core's strict SPECS validator × pc's new tool entries — registry re-discovery glue (cached lane modules get one idempotent `_register_all` re-run) → brain 1168 green.
- Systemic ownership fixes: exceptions parser comma-lists; `tests/core_guard_manifest.json` re-pin sanctions merged to one line (integrator,infra,evolution); PERMANENT `tests/security/gitleaks-baseline.json` multi-lane grant (SCANNERS.md-mandated regen); reviewed grants: config.yaml → voice,evolution; brain/ws.py + visibility test → voice.
- `safety.confirm_policy.classes` completed (+send_email +account_login — qa PENDING ledger cleared).
- Queued merges, all ownership pre-verified: voice (6 ahead) → orb (2, green 38031831247) → infra (8, CI 38063311634) → qa (12, green 38046653258 incl. the transitional-act_pipeline fix) → tools-memory (12, green 38044483348) → evolution (6, CI 38063314386). voice CI 38063317210 dispatched; watcher running.
- Pre-approval honored: Codex returned `Insufficient balance` (0 calls); chat profile stays opencode-go (Go-first per owner) with `chat_daily_cap_usd: 0.50`.

## In progress
- Wave A merge queue → Wave A live demo (one stack, pre-flight pgrep/port sweep, teardown verified) → Wave B dispatch (browser worker, world-state+tasks, Kokoro+local STT, Raphael Chat, tasks/chat verbs).

## Blocked (human-only — mirrored from the ATTENTION register)
- Repo visibility (make private), PAT rotation/narrowing, git history rewrite approval, branch protection enablement, cloud-vs-RAM decision (gates wave 6), Node-on-Windows approval for orb ARCH-1. Details in `docs/HANDOFF-2026-10-09.md` §2.

## Next
- Wave 6 opens only on the user's word (AGENT_RULES §11); lanes sit in WAIT.
- Restore keepalive cron + bring the stack up when the user returns (HANDOFF §1; cron backup outside git at `~/.raphael-coord/crontab.keepalive.bak`).
- Post-gate threads in HANDOFF §3 (activity relay, AUD-17 offer, PocketTTS HF gate).

## Test output (real runs only — never claim unrun tests)
- 2026-10-08 full gate battery: `pytest brain` → 1127 passed / 4 skipped; root suites (regression+contract+security+resilience+lint+supervisor) → 319 passed; `tests/conformance` → 8 passed; `Core Guard OK (20 files byte-stable)`; `scan_personal.py --strict` → STRICT PASS (0 FAIL-severity, 55 advisory); gitleaks vs baseline → no leaks.
- CI: main runs green both OSes incl. scanners (e.g. 37800865212, tests-heavy 37925272630); `wave-5h-gate` tag points at the passing head.

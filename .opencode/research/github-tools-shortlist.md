# GitHub/OSS Tools Shortlist for Raphael

**Date:** 2026-10-07 · **Researcher:** researcher subagent · **Constraint:** 8GB RAM laptop, security-first (audit `docs/AUDIT-2026-10-07.md`), everything passes a SAFETY VET before adoption. Nothing was installed during this research.

## Summary

Seven adoption candidates were evaluated against the audit findings (AUD-23 SSRF TOCTOU, QA-2 property tests, AUD-30 Electron EOL, AUD-15/7 SQLite, Windows UIA robustness, prompt-injection detection, AUD-06 pre-STT wake gate). Headline results: **hypothesis, Electron 43/44 + electron-builder hardening, and openWakeWord are clean PASS adopts**; SSRF fix should be an **in-house IP-pinning transport patterned on safehttpx/requests-hardened** (no dominant mature dep exists); SQLite needs **no new runtime dep** (stdlib backup API + optional sqlite-utils for migrations); **keep pywinauto but harden in-house**; and the **canonical prompt-injection libraries (Rebuff, LLM Guard) are both archived — SKIP all of them** and build a small in-house scanner + optionally run NVIDIA garak in CI.

## Ranked Summary Table

Ranked by (safety vet PASS, then integration cost ascending):

| # | Need | Candidate | Stars / License / Maint. | Vet | ~Cost | Verdict |
|---|------|-----------|--------------------------|-----|-------|---------|
| 1 | QA-2 property tests | **Hypothesis** (HypothesisWorks/hypothesis) | 9.1k / BSD-3 / very active | **PASS** (no CVEs, ecosystem-standard) | 4h | **ADOPT** |
| 2 | AUD-15/7 SQLite | **stdlib sqlite3 backup() + in-house migration ledger**; optional **sqlite-utils** | stdlib / — / —; 2.2k / Apache-2.0 / active (v4.x, Jun 2026) | **PASS** (zero new runtime surface) | 2h stdlib / +3h sqlite-utils | **ADOPT (stdlib first)** |
| 3 | AUD-06 wake gate | **openWakeWord** (dscripka/openWakeWord) | ~2k / Apache-2.0 / slow but alive | **PASS w/ pins** (vendor .onnx, hash-pin; onnxruntime = MS-maintained) | 6h | **ADOPT** |
| 4 | SEC/UIA robustness | **pywinauto 0.6.9 (keep) + in-house hardening** | 6.2k / BSD-3 / hobby-cadence, latest release Jan 2025 | **PASS** (already hash-pinned in repo) | 3h | **ADOPT hardening, SKIP swap** |
| 5 | AUD-23 SSRF | **in-house IP-pinning urllib transport** (pattern: safehttpx + requests-hardened + langchain SSRFSafeTransport) | gradio-app/safehttpx 71★ Apache-2.0 (ToB-audited lineage); saleor/requests-hardened maintained w/ CVE-fix track record | **PASS pattern / CONDITIONAL dep** (no mature pinning dep exists; tiny 0–2★ repos exist but unvetted) | 4h | **ADOPT pattern in-house; safehttpx only if async path needed** |
| 6 | AUD-30 Electron | **Electron 43.x (or 44.x) + electron-builder v27 hardening** | electron 44.4.5 stable (M152); builder 14.7k / MIT / active | **PASS** (official, security-patched line) | 12h | **ADOPT (URGENT — 30.x long EOL)** |
| 7 | Prompt-injection runtime | **SKIP Rebuff + LLM Guard** (both archived); **in-house heuristic scanner + canary words**; optional **garak** in CI | Rebuff archived May 2025; LLM Guard archived Jul 2026; garak 8.4k / Apache-2.0 / active (NVIDIA) | **FAIL (Rebuff, LLM Guard) / PASS (garak, CI-only)** | 4h in-house | **SKIP libs → ADOPT in-house + garak CI** |

---

## 1. SSRF-safe URL fetching — AUD-23 (DNS-rebinding TOCTOU)

### Current state in Raphael
`brain/tools/web/__init__.py` already implements resolve-then-check (`_assert_public_host` → `socket.getaddrinfo` → private/loopback/link-local/reserved/multicast/unspecified rejection) plus a `_SafeRedirect` handler that re-checks every hop. **Missing piece: IP pinning.** The actual `urllib.request` connection re-resolves the hostname independently → classic TOCTOU rebinding window (public IP at check time, private IP at connect time). Same pattern confirmed in `brain/router/httputil.py`, `ollama.py`, `zen.py` (stdlib `urlopen`).

### Candidates

| Repo | Stars | License | Maintenance | Fit |
|------|-------|---------|-------------|-----|
| **gradio-app/safehttpx** | 71 | Apache-2.0 | Active; spun out of Trail of Bits' Gradio 5 security audit (Oct 2024), used in production Gradio | Async GET wrapper; validates via Google DNS; explicit DNS-rebinding mitigation; domain whitelist |
| **saleor/requests-hardened** | ~1k (Saleor org) | Apache-2.0 | Very active — **had CVE-2026-42175 (SSRF bypass via RFC 6598 range) patched in 1.2.1 within weeks** — a *good* security-maintenance signal | `requests` manager with SSRF IP filter, secure timeouts, redirect control; filters resolved IPs at request time |
| Zaczero/httpx-secure | 2 | 0BSD | 9 commits, single dev | Tiny; DNS cache + **IP rewrite (pinning)** + custom validator — right design, too little vetting |
| tommypj/ssrf-safe-fetch | 0 | MIT | 1 commit (!) | Correct design (resolve-then-check + per-redirect revalidation + pinning + Host/SNI preservation) but **zero provenance — never adopt as dep; steal the design** |
| urllib3 | — | MIT | Active (2.8.0, Sep 2026) but frequent CVEs (CVE-2025-66418/66471, CVE-2026-44431/44432 redirect/header issues) | `Retry.allowed_hosts` exists but **no built-in SSRF/DNS-pinning** — not the answer alone |

### Security vet
- **Industry convergence is on one pattern** (langchain-core `SSRFSafeSyncTransport`, FastMCP `ssrf_safe_fetch`, open-webui CVE-2026-87996 fix): resolve DNS **once**, validate **all** returned IPs, **pin the connection to the validated IP**, preserve Host header + TLS SNI/cert validation against the original hostname, **disable or manually re-validate every redirect hop**.
- No mature, widely-adopted Python dep implements full pinning. The 0–2★ repos that do are individually unvetted; safehttpx is the only one with audit lineage, but it's async-only and depends on Google DNS + the `httpx2` pydantic fork.

### Verdict — **ADOPT the pattern in-house (~4h)**
Extend the existing `_assert_public_host` in `brain/tools/web/__init__.py` with:
1. Return the validated IP from the resolver; rewrite the URL to connect to it (Host header + `server_hostname`/`assert_hostname` set to the original hostname for TLS).
2. Disable automatic redirect following; re-run the full check per hop manually (the `_SafeRedirect` handler already exists — extend it to use the pinned IP).
3. Apply the same wrapper in `brain/router/httputil.py` (Zen/Ollama fetches — currently unchecked `urlopen`).
Reference implementations to copy from (MIT/Apache-2.0 compatible, small enough to port): safehttpx, requests-hardened CVE fix, Joshua Rogers' urllib3 adapter writeup. **Skip adopting any dep**: zero new supply-chain surface, matches the existing stdlib code, and the security-critical logic stays under our own tests + gitleaks/CI.

---

## 2. Property-based testing — QA-2 (act_req parser, confirm.py, wake gate)

### Candidate: HypothesisWorks/hypothesis
- **9.1k stars · BSD-3-Clause · 17,912 commits · docs at 6.168.0 · weekly release cadence**
- Used by numpy, CPython-adjacent projects, thousands of OSS repos; PSF-survey-validated; **no known CVEs**; pure-Python test dependency (never ships in runtime artifacts).
- pytest integration is first-class (`pytest-hypothesis` plugin auto-integrated via the `hypothesis` package).
- Stateful testing (`RuleBasedStateMachine`) also available if job-engine race conditions ever need modeling.

### Fit for Raphael
Directly closes **QA-2 P1**: property tests for the act_req JSON parser (arbitrary nested/malformed payloads must raise cleanly, never crash the brain), confirm.py decision logic (invariants: cancel always wins, confirm timeout always fires), and the wake gate (no input path may bypass the gate — test as invariant over reason-code sequences).

### Verdict — **ADOPT (~4h)**
Add `hypothesis` to `tests/requirements.txt` (test-only; body/win runtime requirements untouched). Write ~3 property test modules under `tests/`. Guard CI flake with `derandomize` or fixed `seed` profiles for the heavy parsers.

---

## 3. Electron security upgrade path — AUD-30 (30.5.1 EOL + no-sandbox + IPC)

### Facts (as of 2026-10-07)
- Orb is pinned to **electron 30.5.1** (`body/orb/package.json`) — **EOL since ~mid-2025**, shipping Chromium M126-era with years of unpatched Chromium CVEs.
- **Supported lines now:** 42 (EOL **2026-10-20 — days away**), 43 (EOL 2027-01-05), 44 (EOL 2027-03-02). Latest stable **44.4.5** (Chromium M152, Node 24). **45.0.0 goes stable 2026-10-20.**
- Official policy: latest 3 stable majors receive fixes; security fixes land on the latest minor of each line.

### Recommendation target
- **Adopt Electron 43.x** (supported through Jan 2027, one full major behind current → mature patches) **or 44.x** if the orb's Three.js stack tests clean (M152, supported to Mar 2027). Do **not** target 42 (EOL in days) or un-released 45.
- Jump is 13–14 majors from 30 — real work, but the orb is a small overlay app (transparent window + canvas + WS client), which is the easy Electron case.

### electron-builder (packaging/hardening)
- **electron-userland/electron-builder — 14.7k stars · MIT · active · v27** (requires Node ≥22.12; breaking changes with automated `electron-builder migrate-schema` migration command).
- Hardening configs to enable: `asar: true` (default — verify not disabled), minimal `files` glob, **Electron Fuses** (via `@electron/fuses` or builder config) to disable `runAsNode`, `enableNodeOptionsEnvironmentVariable`, `enableNodeCliInspectArguments`; `publish` disabled; NSIS `deleteAppDataOnUninstall` etc.
- Pair with Electron security checklist: `contextIsolation: true`, `sandbox: true`, `nodeIntegration: false`, strict CSP, `will-navigate` deny-by-default, `setWindowOpenHandler` deny, IPC channel allowlist validation (AUD-30's "IPC validation" half — stays in-house).

### Security vet — **PASS**
Official Electron/security-patched line; electron-builder is the de-facto standard (14.7k★, MIT, active, used by most production Electron apps). npm audit + gitleaks already in CI cover the dep tree.

### Verdict — **ADOPT, highest priority of all seven (~12h)**
Staged plan: upgrade 30→43, run orb tests + conformance, then apply builder fuses + IPC validation + sandbox flags. Consider bumping to 44 only after 43 is stable in daily use. Note: Electron 23+ dropped Win7/8 — irrelevant (Win10/11 box).

---

## 4. SQLite safe-migration/backup — AUD-15/7 (memory DB perms/retention, no migrations)

### Current state
`brain/memory/` uses **stdlib `sqlite3`** directly (sync, `timeout=30`, `Row` factory). No migrations ledger, no backup routine.

### Candidates

| Lib | Stars | License | Vet | Fit |
|-----|-------|---------|-----|-----|
| **stdlib sqlite3 `backup()`** | — | — | **PASS (zero surface)** | Online backup even while DB is in use; works with WAL. Python 3.7+. Pair with `PRAGMA wal_checkpoint(TRUNCATE)` + `PRAGMA optimize`. |
| **aiosqlite** (omnilib/aiosqlite) | 1.6k | MIT | **PASS** — thin thread-per-connection wrapper over stdlib sqlite3; Debian/Gentoo-packaged; no known CVEs | Only needed if memory calls move onto the asyncio loop without a thread executor; today's code is sync and fine. |
| **sqlite-utils** (simonw) | 2.2k | Apache-2.0 | **PASS** — very active (v4.x, migrations landed Jun 2026; ReversingLabs SAFE: no risks) | Python migration files + `sqlite-utils migrate`; good dev-time schema evolution. ⚠ v4 breaking: upsert syntax, FLOAT→REAL default — pin and read upgrade guide. |
| **sqlean** (nalgeon) | 4.4k | MIT | **CONDITIONAL→SKIP** — explicitly **maintenance-mode**, one-man project; ships **precompiled native binaries** and loads C extensions into sqlite (`fileio`, `crypto`…) = large attack surface vs. our security-first posture | Not needed for anything we do; stdlib covers memory needs. |

### Verdict — **ADOPT stdlib-first (~2h); sqlite-utils optional (+3h)**
1. Backups: stdlib `conn.backup()` to a timestamped file on a cron/supervisor tick; verify with `PRAGMA integrity_check`; retention policy = AUD-15's "retention" half (keep last N).
2. Hardening (AUD-15 "perms" half): DB file `0600`, parent dir `0700`, `PRAGMA foreign_keys=ON`, `journal_mode=WAL`, `secure_delete=ON`.
3. Migrations: a tiny in-house ordered-SQL migration table (`schema_migrations`) — matches existing code style, zero deps. Adopt **sqlite-utils** (Apache-2.0) only if schema churn justifies a real framework.
4. **SKIP sqlean** (maintenance-mode + native extension loading) and **skip aiosqlite** unless memory moves async.

---

## 5. Windows UI-automation robustness (body/win)

### Current state
`body/win/requirements.txt` already hash-pins **pywinauto==0.6.9** (SEC-9 discipline, `--require-hashes`).

### Candidates

| Lib | Stars | License | Maint. | Vet |
|-----|-------|---------|--------|-----|
| **pywinauto** (pywinauto/pywinauto) | 6.2k | BSD-3 | Hobby cadence — 0.6.9 released **2025-01-06** ("last Python 2.7 compatible release"); 505 open issues; still the reference Python Win32+UIA library, ~920k PyPI downloads/mo | **PASS** — pure Python (+pywin32/comtypes), no known CVEs, already hash-pinned |
| **uiautomation** (yinkaisheng/Python-UIAutomation-for-Windows) | 3.6k | Apache-2.0 | Single maintainer; last commit Jun 2026, PyPI 2.0.29 Aug 2025; single-file ctypes wrapper (10.8k lines), fewer deps than pywinauto | PASS but **no compelling reason to swap** — different API, migration cost with no robustness gain |
| FlaUI | C#/.NET | MIT | Active | Wrong language for a Python body; adds .NET runtime dependency |
| Clicknium | — | Proprietary | Vendor | **SKIP** — closed-source recorder/cloud, fails security-first vet |

**Input-injection safety:** no maintained Python lib provides confirmation-gates/allowlists for SendInput-style injection — that is Raphael's own audit layer (input-lock arbitration, confirmation on destructive actions). pywinauto exposes `click_input`/`type_keys` on top of SendInput; our gates wrap them, nothing upstream helps.

### Verdict — **KEEP pywinauto 0.6.9; harden in-house (~3h); SKIP alternatives**
- Robustness hardening in-house: control-target allowlist (never act on arbitrary resolved controls), always verify window PID/title before injection, bounded retries with timeout budget, dry-run/confirm mode for destructive actions, structured action log (ties into input-lock arbitration).
- Optional: keep **uiautomation** as a *dev-time* UISpy-equivalent inspect tool only (not a runtime dep) — skip unless pywinauto's UIA backend proves insufficient for a specific app.

---

## 6. Prompt-injection detection for untrusted content entering prompts

### Market reality check (this is the finding)
- **Rebuff (protectai/rebuff): ARCHIVED May 2025**, read-only since 2024. **SKIP — dead.**
- **LLM Guard (protectai/llm-guard): repository ARCHIVED July 9, 2026.** MIT but **unmaintained** — treat as an owned fork if ever used. **SKIP as a dependency.**
- **Guardrails AI:** active (6.6k★, Apache-2.0) but **discontinued hosted inferencing (cutoff Aug 25, 2026)**; its prompt-injection validator requires **OpenAI + Pinecone cloud keys** — bad fit for our privacy/zero-extra-cloud posture. CONDITIONAL at best.
- **Promptfoo:** acquired by OpenAI (Mar 2026) — commercial trajectory now.
- **Microsoft promptflow guardrails:** Azure-centric, weak maintenance signal for OSS runtime use.
- **NVIDIA garak:** **8.4k★, Apache-2.0, active (v0.15.1, pushed Jul 2026)** — but it is a **red-team/CI scanner**, not a runtime guard. Perfect for what it is.

### Verdict — **SKIP all runtime guard libs; ADOPT in-house scanner + garak in CI (~4h)**
Raphael's untrusted-content boundary (screen text, web fetch output, clipboard, tool results entering prompts) deserves a small in-house module — regex/keyword heuristics ("ignore previous instructions", role-marker spoofing, encoded-payload shapes, instruction-embedded-in-data markers) + **canary-word leak detection** (the one good idea from Rebuff — cheap, local, deterministic) + content tagging (untrusted content wrapped as delimited data in prompts, never as instructions).
Optionally add **garak** to the security CI lane (monthly/manual, cloud-LLM target = router) to red-team the actual prompt stack. Cost ~4h in-house; zero new runtime deps; survives because *we* own it.

---

## 7. Wake-word library for pre-STT gate — AUD-06 (<200MB, CPU, local, zero-shot)

### Candidates

| Lib | Stars | License | Maint. | Footprint | Vet |
|-----|-------|---------|--------|-----------|-----|
| **openWakeWord** (dscripka/openWakeWord) | ~2k | Apache-2.0 (code + bundled models; HF mirror confirms Apache-2.0 weights) | v0.6.0 Feb-2024 era; repo alive with 2026 issues but maintainer slow; openwakeword.com now exists as a training platform | Pretrained ONNX models ~1.5–6 MB each; **onnxruntime CPU wheel ~50–150 MB RSS → well under 200 MB** for 1–3 models; ~70% of one RPi3 core for 4 models | **PASS with pins** — Microsoft-maintained onnxruntime; vendor the `.onnx` files into repo/volume and hash-pin them (no runtime model download) |
| **Porcupine** (Picovoice) | ~3k | **Proprietary** (free personal tier; commercial license needed) | Active | ~1 MB RAM, excellent accuracy | **SKIP** — closed-source native binaries + access-key management + license terms conflict with security-first vetting |
| **ViolaWake** | new (2026) | Apache-2.0 | Brand new, single-vendor comparison pages | ONNX, local | **SKIP for now** — too unproven; watch |
| Snowboy | — | — | **Deprecated 2020 (Kitt.AI/Baidu)** | — | **SKIP — dead** |
| Mycroft Precise | — | Apache-2.0 | Legacy 2019; community forks only | — | **SKIP — unmaintained upstream** |

### Fit for Raphael
openWakeWord slots directly into the **AUD-06 pre-STT gate**: VAD segments → openWakeWord scoring → only `wake`-labeled audio may reach cloud STT. Pretrained zero-shot models ("hey jarvis", "hey mycroft", "computer", …) cover the existing wake phrase; custom-word training exists if we want "Raphael" (training stays on laptop/pod, not runtime). Runs on CPU in the voice venv — **no GPU, no new RAM pressure** (8GB box fine: ~100–200 MB RSS vs. current zero).

### Verdict — **ADOPT openWakeWord (~6h)**
1. Pin `openwakeword==0.6.0` + `onnxruntime==<pinned>` in the voice venv requirements (hash-pin per SEC-9 discipline where applicable).
2. **Vendor the .onnx model files** into the repo/volume with sha256 manifest (kills the runtime-download supply-chain risk; Core Guard already has hash-manifest infrastructure).
3. Wire into the pre-STT gate in `brain/voice/`: score each VAD frame batch; gate passes only on model score ≥ threshold with debounce; **fail-closed** (matches the SEC-3 fail-open concern — unknown-reason segments must NOT reach STT).
4. Mitigations: known issues include false-positive rates on custom-trained models (GitHub #336) and slow upstream — pin exactly, wrap behind our own gate interface so the engine stays swappable.

---

## Trade-offs & Considerations (cross-cutting)

- **Adopt-pattern-over-dep for security-critical code:** where no vetted mature dep exists (SSRF pinning, prompt-injection scanning), in-house code under our own CI is *safer* than an unvetted 2★ dep — and Raphael's code is already small and hash-pinned.
- **Test-only vs runtime deps:** hypothesis, sqlite-utils (dev-time), and garak (CI-time) never touch the runtime artifact → zero RAM/attack-surface cost on the 8GB box.
- **Electron is the one "must spend hours" item** — everything else is ≤6h. 30.5.1 + no-sandbox is the largest live risk in the audit; 43.x gets security patches through Jan 2027.
- **Archived ≠ unused:** LLM Guard/Rebuff still circulate in blog posts recommending them — the 2026 market check overrides those posts.
- **Pin + vendor + hash-manifest** is the adoption ritual for anything that loads models or native code (openWakeWord, onnxruntime, any future sqlean-like tool).

## Sources

- [Langflow DNS-rebinding TOCTOU CVE-2026-10546 (IBM)](https://www.ibm.com/support/pages/security-bulletin-dns-rebinding-toctou-bypass-ssrf-protection-langflow-oss-url-component) — TOCTOU pattern + SSRFProtectedTransport fix
- [langchain-openai SSRF advisory GHSA-r7w7-9xr2-qq2r](https://github.com/langchain-ai/langchain/security/advisories/GHSA-r7w7-9xr2-qq2r) — SSRFSafeSyncTransport: resolve-once + pin + no-redirects
- [gradio-app/safehttpx](https://github.com/gradio-app/safehttpx) — Trail of Bits Gradio-audit-derived SSRF lib (71★, Apache-2.0)
- [saleor/requests-hardened](https://github.com/saleor/requests-hardened) + [CVE-2026-42175 GHSA-vh75-fwv3-pqrh](https://github.com/advisories/GHSA-vh75-fwv3-pqrh) — SSRF filter lib, active CVE-fix record
- [Joshua Rogers — DNS rebinding solution in Python](https://joshua.hu/solving-fixing-interesting-problems-python-dns-rebindind-requests) — pinning adapter pattern for requests/urllib3
- [tommypj/ssrf-safe-fetch](https://github.com/tommypj/ssrf-safe-fetch) — correct pinning design (0★, 1 commit — design only)
- [urllib3 changelog 2.8.0](https://urllib3.readthedocs.io/en/stable/changelog.html) + [SUSE-SU-2026:20175-1](https://lists.suse.com/pipermail/sle-security-updates/2026-February/024008.html) — urllib3 CVE history, no built-in SSRF guard
- [HypothesisWorks/hypothesis](https://github.com/HypothesisWorks/hypothesis) — 9.1k★, property-based testing
- [Electron release schedule](https://releases.electronjs.org/schedule) · [endoflife.date/electron](https://endoflife.date/electron) — supported lines 42/43/44 as of Oct 2026; 45 stable 2026-10-20
- [Electron versioning policy](https://electronjs.org/docs/latest/tutorial/electron-timelines) — latest-3-majors support policy
- [electron-userland/electron-builder](https://github.com/electron-userland/electron-builder) — 14.7k★ MIT, v27, hardening/fuses/migrate-schema
- [omnilib/aiosqlite](https://github.com/omnilib/aiosqlite) — 1.6k★ MIT async sqlite bridge
- [simonw/sqlite-utils](https://github.com/simonw/sqlite-utils) — 2.2k★ Apache-2.0, v4 migrations ([changelog post](https://simonwillison.net/2026/Jun/21/sqlite-utils-40rc1))
- [nalgeon/sqlean](https://github.com/nalgeon/sqlean) — 4.4k★ MIT but maintenance-mode + native extension binaries
- [Python sqlite3 backup() docs](https://docs.python.org/3/library/sqlite3.html) — stdlib online backup
- [pywinauto/pywinauto](https://github.com/pywinauto/pywinauto) — 6.2k★ BSD-3; [0.6.9 release](https://github.com/pywinauto/pywinauto/releases) (2025-01-06)
- [yinkaisheng/Python-UIAutomation-for-Windows](https://github.com/yinkaisheng/Python-UIAutomation-for-Windows) — 3.6k★ Apache-2.0 alternative
- [Best AI Security Tools 2026 (appsecsanta)](https://appsecsanta.com/ai-security-tools) — Rebuff archived May 2025, LLM Guard archived Jul 2026
- [LLM Guard archive notice (mintmcp)](https://www.mintmcp.com/blog/prompt-injection-detection-tools) — archived July 9, 2026
- [guardrails-ai/guardrails](https://github.com/guardrails-ai/guardrails) — 6.6k★ Apache-2.0; hosted inferencing discontinued Aug 2026
- [NVIDIA/garak](https://github.com/NVIDIA/garak) — 8.4k★ Apache-2.0, active (llmthreat snapshot v0.15.1)
- [arxiv 2506.19109 — injection detection evaluation](https://arxiv.org/html/2506.19109v1) — Vigil/LLM Guard/Rebuff comparison data
- [dscripka/openWakeWord](https://github.com/dscripka/openWakeWord) — Apache-2.0 wakeword lib; [release v0.6.0](https://github.com/dscripka/openwakeword/releases/tag/v0.6.0)
- [Picovoice/porcupine](https://github.com/picovoice/porcupine) — proprietary-key model
- [ViolaWake vs Porcupine comparison](https://violawake.com/compare/picovoice) — 2026 wakeword landscape (Snowboy deprecated, Precise legacy)
- [openWakeWord features on HF (littlebearlabs)](https://huggingface.co/littlebearlabs/openwakeword-features) — model sizes ~1.1–1.3 MB, Apache-2.0

## Recommendations (priority order)

1. **Electron 30.5.1 → 43.x + builder fuses/sandbox/IPC validation** — biggest live risk, do first (~12h).
2. **hypothesis into tests/** — closes QA-2, trivial, zero risk (~4h).
3. **SSRF IP-pinning transport in-house** on the existing urllib code + router httputil (~4h).
4. **openWakeWord pre-STT gate**, vendored + hash-pinned models, fail-closed (~6h) — closes AUD-06/SEC-3 properly.
5. **SQLite stdlib backup + perms + migration ledger** (~2h); sqlite-utils only if schema churn grows.
6. **pywinauto hardening layer** (allowlist, PID/title verify, confirm, logging) — no library swap (~3h).
7. **In-house prompt-injection scanner + canary words**; garak as a CI red-team lane; **never depend on Rebuff/LLM Guard** (~4h).

# Raphael project-wide audit

**Audience:** integrator  
**Scope:** read-only static review of main plus all 10 registered Raphael lane worktrees, including security, privacy/network boundaries, Windows action safety, lifecycle/reliability, performance, configuration, CI, and architecture.  
**Baseline:** main `7f9734e`. At inspection, main was clean; `agent/brain-core` and `agent/orb` had uncommitted work (preserve it); the other eight lane worktrees were clean. `git diff --check` was clean.  
**Safety:** no source code was changed; no tests, installs, live-stack probes, elevated commands, or paid calls were run. `.env`, logs, databases, screenshots, audio, and model weights were not opened.

## Executive assessment

The project has good foundations: loopback Brain binding, constant-time token comparison, a non-wildcard relay, structured Body action validation, mock-oriented tests, and screenshot-byte omission from journals. However, **main is not ready for a security sign-off or always-on deployment**. There are static paths to expose/overwrite the Brain token, bypass router config authority, upload ambient speech, bypass non-voice confirmation, and pass all parent credentials to configured MCP servers. Some fixes exist only on unmerged lanes; two worktrees are dirty. The user-facing security claims and current runtime behavior are not consistently aligned.

This is a code/config audit, not a penetration test. Vendored Fish-Speech source, binary/media contents, ignored virtual environments, live host settings, repo visibility, and actual token permissions were not examined. Runtime behavior must be verified by the integrator using mocks first; human-only host/repo actions remain approval-gated.

## Worktree snapshot and integration caution

All 10 lane worktrees were discovered. `agent/brain-core` and `agent/orb` are dirty. Their current uncommitted changes must be preserved and reviewed as active work, not reset or overwritten. Other lane branches contain substantial changes ahead of main; lane status documents are useful context but are not proof of integrated behavior. In particular, pc-control, tools-memory, voice, infra, computer-use, and router fixes below are branch-local until merged and tested together.

## Findings

Severity reflects impact in the checked source, not whether a feature is currently enabled on the user’s machine.

### Release blockers: credentials, policy, or privacy boundary

#### AUD-01 — CRITICAL: File tools can read/write `~/.raphael/token` and other sensitive home data

**Evidence:** `config.d/tools-memory.yaml:30-33` sets `files.allowed_roots: ["~"]`. `brain/tools/files/__init__.py:31-33,123-132` blocks only a short basename/suffix list; `token`, `~/.raphael/token`, many credential directories/files, and arbitrary executables are not covered. `file_read` and `file_write` are implemented at `:176-208`; `file_write` is registered with `risky=False` at `:246-260`. Existing tests prove `.env` refusal, not Raphael token refusal (`brain/memory/tests/test_tools_files.py:51-85`).

**Impact:** A model-directed `file_read` can place the Brain’s authentication token into a cloud prompt; the router does not load that token-file value into its redaction set. A model-directed `file_write` can replace the token or overwrite code/config/scripts and user files without confirmation. Home-wide access also includes SSH/cloud/browser credential stores and sensitive documents.

**Action:** Treat as a release blocker. Restrict roots to an explicit app workspace, add resolved-path and sensitive-directory deny rules, protect all Raphael credentials/data, and confirm-gate or remove arbitrary writes. Test read/write/trash attempts on `~/.raphael/token`, `.ssh`, cloud credentials, config, executable files, and symlinked paths using temporary fixtures only.

#### AUD-02 — CRITICAL: Router config loading bypasses central authority protection

**Evidence:** `brain/config.py:122-157` strips authority keys from lane fragments. The independent router loader does not: `brain/router/config.py:117-123` deep-merges all fragments, and `load_config()` uses that merger at `:280-290`; provider gates/endpoints are then read at `:292-363`.

**Impact:** A lane fragment rejected by the Brain’s central config loader can still change the router’s effective `providers`, `profiles`, endpoints, privacy, or paid gates. Changing a provider URL can disclose an API key to an attacker-controlled host. This defeats the intended authority boundary.

**Action:** Use one authoritative loader or apply the exact same schema/authority policy to every loader. Add adversarial-fragment tests asserting that `config.d` cannot alter router chain, provider endpoint, paid gates, privacy/redaction, or profile. Broken authority config must be visible and fail closed.

#### AUD-03 — HIGH: `.env` is linked into every lane worktree

**Evidence:** Metadata-only `find` found `.env` symlinks in all 10 worktrees pointing at the main checkout’s `.env`. `docs/TEAM_ROSTER.md:24` relies on agent permission rules, not OS-level isolation.

**Impact:** All lane processes run under the same OS account and can reach the same secrets through the symlink if a tool or child process reads it. `chmod 600` protects against other Unix users, not same-UID agents. `.gitignore` is not an access-control mechanism.

**Action:** Remove shared links. Inject only a lane’s required credential into its trusted process, or use a minimal credential broker. Verify child-process environments and file access without reading or printing secret values.

#### AUD-04 — HIGH: Personal-data policy and PII redaction are not enforced on ordinary cloud chat

**Evidence:** `allow_free_models_for_personal_data` is loaded in `brain/router/config.py:321-323`, but a repo-wide source search found no runtime use. `brain/router/privacy.py:238-255,271-279` applies `redact_secrets` to ordinary messages; that path covers credential patterns/cards but not the configured email/phone categories at `:222-229`. `brain/loop.py:165-180` sends user text/history through this path. The memory `include_personal` seam exists but is not wired into `_build_messages`.

**Impact:** Emails, phone numbers, names, clipboard/file contents, and personal conversation history can reach cloud providers. The setting/documentation suggests a policy that is not actually enforced.

**Action:** Decide/document the actual data policy. If personal data must remain local, implement a fail-closed classification/consent gate before every cloud call; no local provider means refusal, not silent cloud fallback. Apply configured redaction consistently to all outbound sources, and test zero provider calls for restricted input. Do not represent regex redaction as complete PII detection.

#### AUD-05 — HIGH: Foreground-sensitive chat blocklist is unwired and fails open

**Evidence:** `brain/router/privacy.py:34,53-69` starts with no foreground hook and returns `None` if it is absent or errors. `blocklist_hit()` treats that as no match (`:72-81`), and `brain/router/core.py:339-356` allows chat. `brain/app.py` lifespan never calls `set_foreground_check` (`:51-90`). Router tests install a synthetic hook themselves (`brain/router/tests/test_privacy.py:92-130`).

**Impact:** The documented password-manager/banking foreground guard does not protect normal chat in production. Unknown/unavailable foreground is treated as safe. The computer-use branch has extra sensitive patterns, but `agent/computer-use/brain/vision/context.py:58-60,103-108,121-153` filters window/history data with only the static blocklist. Password-focus protection also depends on Body fields that the current `agent/pc-control` worktree does not emit.

**Action:** Wire a production foreground provider or remove the claim. Unknown/error must refuse cloud egress unless the user explicitly overrides. Apply sensitive-context checks consistently to foreground, window lists, history, and screenshots; land/test the Body password-focus contract before claiming it works.

#### AUD-06 — HIGH: Always-listen uploads ambient speech before wake-word detection

**Evidence:** Main `brain/voice/activation.py:136-150` fails open on unknown reason and exceptions. The voice branch changes those invalid cases to fail closed, but valid `reason="wake"` still passes (`agent/voice/brain/voice/activation.py:140-169`). `body/win/audio_in.py:200-205,255-278` marks every VAD segment `reason="wake"`; `brain/ws.py:712-748,775-780` performs STT before the transcript wake-word check.

**Impact:** Non-wake ambient speech is still sent to cloud STT. The unmerged voice change closes invalid-reason errors but does not create a local wake-word gate.

**Action:** Treat as an explicit privacy decision. Add local keyword detection before upload or use PTT-only until it exists. If the user knowingly accepts VAD-to-cloud behavior, clearly disclose it and record consent. Do not mark SEC-3 closed based only on tests for unknown reasons.

#### AUD-07 — HIGH: Configured MCP servers receive all process environment secrets

**Evidence:** `brain/tools/mcp/client.py:47-51` uses `env={**os.environ, **(env or {})}` when spawning each server. MCP’s user-authored allow-list is described in `brain/tools/mcp/__init__.py:3-16`, but the process environment is not minimized. Fish similarly copies `os.environ` (`brain/voice/tts.py:418-425`).

**Impact:** A configured server or compromised dependency can read provider API keys, Raphael auth variables, and unrelated credentials even when it does not need them.

**Action:** Use a minimal allowlisted environment for child processes and explicit per-server secrets only. Add tests that inject sentinel parent secrets and prove they are absent from MCP/Fish child environments.

### High: confirmation, computer control, and coordination

#### AUD-08 — HIGH: Client-controlled confirmation channel can bypass non-voice approval

**Evidence:** `brain/ws.py:553-564` accepts `msg['via']` before deriving channel from authenticated session role. `brain/confirm.py:253-273` rejects high-risk affirmative answers only when the resulting channel is voice.

**Impact:** An authenticated body session can claim `via: "click"` or `"text"` and approve a high-risk confirmation. A role is authenticated; an arbitrary field in its message is not.

**Action:** Derive channel solely from authenticated role and trusted UI path; reject/ignore client-supplied `via`. Add WS tests proving a body cannot claim click/text.

#### AUD-09 — HIGH: Risky tools are frequently classified low-risk and voice-approvable

**Evidence:** `brain/confirm.py:31-84,117-151,174-187` computes high risk by membership in `safety.confirm_actions`. Several mapped actions (`system_command`, `git_write`, `network`, `computer_use`, arbitrary plugin/MCP tool names) are not in that list. Tests explicitly assert shell is low-risk and voice-approvable (`brain/tests/test_confirm_hardening.py:39-57,85-92`). PC tool confirmation categories are stored in `ToolSpec`, but registration does not pass them to central policy (`brain/tools/pc/__init__.py:63-75`).

**Impact:** An unknown external tool, shell command, GitHub operation, or future mutating PowerShell script can receive only low-risk confirmation and accept open-mic “yes”. This is especially unsafe with prompt injection.

**Action:** Default every `risky=True`/unknown tool to non-voice approval unless a reviewed explicit policy says otherwise. Propagate confirmation categories through registration and dispatch; test all risky tool namespaces.

#### AUD-10 — HIGH: Unsafe shell fallback survives tool-discovery failures

**Evidence:** `brain/tools/__init__.py:324-344` registers arbitrary `shell=True`; discovery errors are caught and non-fatal (`:250-313`), and app startup treats them as non-fatal (`brain/app.py:78-86`). The fixed `brain/tools/shell` package normally overwrites the placeholder, but failure before replacement leaves it exposed.

**Impact:** An import/spec/startup failure can silently restore arbitrary command execution. Combined with AUD-09, an open-mic affirmation can authorize it.

**Action:** Delete the placeholder and fail closed if the fixed registry is absent/invalid. Simulate import and registration failure and assert the shell tool is not offered or callable.

#### AUD-11 — HIGH: Local executable/file launches and generic UIA actions lack effect-level confirmation

**Evidence:** `body/win/act_launch.py:108-117,154-160` launches literal existing paths; `:163-179` opens any existing local file via its default handler. Both actions register with no confirmation (`:218-233`). Generic UIA click/type also has `confirm=None` (`body/win/act_uia.py:101-139`).

**Impact:** A local executable or handler-active file can be launched without confirmation. A generic click/type can submit a payment/message or modify a sensitive form even when the initial task text did not match a risky phrase.

**Action:** Separate trusted app launch from arbitrary executable/document open; require confirmation for executable/script/handler-active paths. Add a preview/confirm boundary for high-impact GUI submissions and sensitive apps.

#### AUD-12 — HIGH: Lane coordination content enters a privileged integrator without an explicit untrusted-data boundary

**Evidence:** `tools/conductor/conductor.py:337-344` wakes the integrator to read inbox/events; `tools/conductor/prompts/integrator_event.md:25-53` directs the integrator to handle events, decide requests, assign work, and merge. `docs/AGENT_RULES.md:13` covers screen/web/file/tool output but does not explicitly cover coordinator events.

**Impact:** A compromised/prompt-injected lane message can attempt to redirect a privileged integrator session. Shared user identity/worktrees/coord filesystem are collaboration boundaries, not OS isolation.

**Action:** Treat all event/inbox `msg` and `data` as untrusted input. Validate event schema and allowed transitions; no message can override system/ownership rules or authorize shell, merge, secret access, paid calls, or human-only actions. Add injection fixtures for event content and state/session fields.

#### AUD-13 — HIGH, HUMAN-GATED: Main contains the old root WSLg service source

**Evidence:** Main `scripts/wslg-shadow/raphael-wslg-shadow.service:5-8` executes a script under a user-writable home path as root. The audit register reports the live service was disabled by the human. `agent/infra` contains a root-owned/hash-pinned redesign, not yet integrated/applied.

**Impact:** Reinstalling the main-branch unit can reintroduce the confirmed privilege-escalation chain. Live disablement is not a safe source for future installs.

**Action:** Keep disabled. Integrate/review the hardening; make the old install path impossible to use. Installation or re-enable remains a human approval/action; do not run it during integration.

#### AUD-14 — HIGH: Main still registers administration-sensitive GitHub operations

**Evidence:** Main `brain/tools/github/__init__.py:49-77,149-197,205-219` offers public repo creation and visibility changes; private repo creation is `risky=False`. `agent/tools-memory` removes creation/visibility, but that branch is not in main.

**Impact:** Main exposes operations requiring elevated GitHub PAT scopes; current risk-category issues also weaken non-voice approval.

**Action:** Integrate/review the tools-memory removal before enabling GitHub. Keep public creation/visibility human-only and document a selected-repositories, least-privilege PAT. Do not read or change token values.

### P1: deployment, data lifecycle, and reliability

#### AUD-15 — P1: Memory/task data is checkout-local, not instance-scoped or permission-hardened

**Evidence:** `brain/memory/__init__.py:10-23` defaults to `brain/memory/memory.db`; `brain/config.py:225-230` defines instance data directories; supervisor does not set `RAPHAEL_DB_PATH`. The database file is ignored, but SQLite creation does not explicitly enforce owner-only permissions. Jobs/journal are unbounded and `/jobs` returns all rows.

**Impact:** Personal history is stored in the source tree, can be shared by processes using one checkout, can inherit permissive umask, and can grow indefinitely. There is no verified backup/restore path.

**Action:** Move to the per-instance data dir, enforce 0700/0600 for DB/WAL/SHM, migrate safely, define retention for jobs/journal/logs, and test backup/restore before deleting old data.

#### AUD-16 — P1: Timed-out/cancelled `to_thread` Body operations may continue after input-lock release

**Evidence:** `body/win/actions.py:364-370,395-400` uses `asyncio.wait_for` then releases the input lock. Handlers such as UIA click/type use `asyncio.to_thread` (`body/win/act_uia.py:117-133`); cancelling the await does not terminate the worker thread.

**Impact:** The Brain/Body may report timeout/cancel and admit the next GUI action while the first OS call is still running, causing overlapping input or a late unintended action.

**Action:** Hold/quarantine the input resource until the worker truly completes or has a verifiable cancellation mechanism. Test timeout and cancel with a deliberately blocked backend and prove no next action begins early.

#### AUD-17 — P1: Slow STT and Body actions block their session receive loops

**Evidence:** `brain/ws.py:712-748` awaits STT (up to 120 seconds) inline in `WsHub.handle`’s receive loop. `body/win/ws_client.py:124-159,161-177` awaits action dispatch inline in the Body receive loop. The protocol heartbeat allows only three missed pongs (about 30 seconds).

**Impact:** A healthy long STT/UIA action can delay pong/action/control processing and cause the peer to be closed as dead. This can drop responses, trigger retries, or strand GUI state.

**Action:** Keep socket readers/heartbeats responsive and run long work through bounded per-session tasks/queues with explicit ordering and cancellation. Add tests with >30-second mocked STT/UIA while verifying heartbeat and cancellation behavior.

#### AUD-18 — P1: Uninstall is not repo/instance-scoped and does not verify WSL shutdown

**Evidence:** `scripts/uninstall.ps1:68-103` force-stops Windows processes by broad command-line substrings, including any `body/orb`/`supervisor/main.py` path. It does not match the intended repository/instance and does not stop/verify the WSL Brain/Fish/systemd service (`:105-108` says persistent data remains).

**Impact:** It can terminate other active Raphael worktrees/lane sessions and can report completion while WSL-side Brain/TTS remains running.

**Action:** Use verified instance PID/parent metadata and exact repo paths, show targets in dry-run, and report/stop only the requested instance. Explicitly distinguish “Windows supervisor removed” from “Brain/Fish stopped.”

#### AUD-19 — P1: Setup/dependency installation is not reproducible

**Evidence:** `scripts/setup.sh:54-92` advertises nonexistent `brain/requirements.txt` and prints a stale systemd sample (`Wants=ollama`, `brain/app.py`) unlike `brain/raphael-brain.service`. `brain/voice/scripts/build_fish_venv.sh:8,13-27` hardcodes `/home/dami/raphael`, uses floating versions and no hashes; ignored vendor code is not pinned by the repository. `scripts/install-body-venv.ps1:31-33,78-82` uses unhashed `scripts/body-requirements.txt`; the hashed `body/win/requirements.txt` is only in a lane branch and is not consumed by the installer.

**Impact:** Clean setup may fail or install a different runtime; dependencies can drift and machine-specific paths defeat portability.

**Action:** Establish canonical per-platform lockfiles and installers using hashes/pinned vendor revisions; fix/remove stale setup output; add clean-environment build/smoke checks. Do not install anything during this audit.

#### AUD-20 — P1: CI has no security/dependency scan or least-privilege token declaration

**Evidence:** `.github/workflows/ci.yml` and `tests-heavy.yml` run tests/Core Guard but no Gitleaks, dependency audit, or static security checks. Actions use major tags; workflows have no explicit minimal `permissions:` block or `persist-credentials: false`. `tests/requirements.txt` has broad version ranges.

**Impact:** Secret/dependency regressions can merge without detection; pull-request code may receive unnecessary GitHub token capability depending on repository defaults.

**Action:** Add redacted secret scanning and dependency/static checks, set least-privilege workflow permissions, disable persisted checkout credentials when not needed, and lock test dependencies/update policy.

#### AUD-21 — P1: Core Guard branch labels detection as “SAFE MODE” but does not enforce it

**Evidence:** The dirty `agent/brain-core` `brain/coreguard.py` reports manifest mismatch. Its `brain/app.py` calls it after loop/tool startup and adds a status block; no tool/act dispatch checks the safe-mode flag. The manifest and verifier are in the same checkout.

**Impact:** Dangerous actions remain available while the UI says “SAFE MODE”; a repo-local manifest is not a tamper-proof trust root.

**Action:** Implement/test explicit blocked capabilities on mismatch, or rename/document it as detection-only. Do not claim anti-tamper protection from a self-contained hash manifest.

#### AUD-22 — P1: Memory and plugin integration is incomplete

**Evidence:** Main `brain/loop.py:165-180` builds messages from short-lived in-memory history but does not call `brain.memory.retrieval.build_context`, inject saved skills, or invoke `plugins.load_enabled`/schedule `arm_all`. `agent/tools-memory/docs/status/tools-memory.md:73-81,134-139` records those call-site requests as outstanding.

**Impact:** Stored memories/skills may not influence turns; configured schedules/plugins may not run. Merging storage without an explicit end-to-end privacy/injection contract risks either silent feature failure or unsafe later wiring.

**Action:** Decide/close the cross-lane requests before advertising those features. Add end-to-end tests for startup, injection framing, personal-data exclusion, plugin authority, schedule startup/shutdown, and exactly-once timer behavior.

### P2: availability, performance, and future-feature readiness

#### AUD-23 — P2: Web-fetch SSRF check has DNS-rebinding TOCTOU

**Evidence:** `brain/tools/web/__init__.py:84-133` checks DNS, then urllib resolves/connects separately; its own comment at `:17-18` acknowledges the window.

**Impact:** A hostile hostname can resolve public during validation and private/local during connection or redirect.

**Action:** Pin the validated address for the actual connection while preserving TLS host verification, or use a vetted safe transport. Test rebind and redirect cases.

#### AUD-24 — P2: Unbounded queues, frame limits, and logs can grow under stalls

**Evidence:** `body/win/audio_in.py:224-236` uses an unbounded callback queue. `brain/ws.py:338-363` has no explicit binary-frame cap and checks `audio_buf` before appending a whole frame. `brain/router/status.py:35-40` reads all of `usage.jsonl` before slicing the final 2,000 lines. Jobs/journal are unbounded; Fish log has no rotation.

**Impact:** Backpressure or long uptime can increase RAM/disk use and delay status/interaction. A frame can exceed the nominal audio cap; connection/session count is not globally bounded.

**Action:** Add exact byte/frame/session limits, bounded audio backpressure policy, real tail reads or rotation, and documented retention. Stress test stalled network and long-running state.

#### AUD-25 — P2: MCP concurrent requests can discard each other’s responses

**Evidence:** `brain/tools/mcp/client.py:44,98-146` has one shared response queue; a request discards response messages with another request ID. Concurrent calls share the same client.

**Impact:** Concurrent tools can time out with ambiguous external side effects.

**Action:** Use one reader with per-request futures keyed by JSON-RPC ID, serialize writes/id allocation, and test reversed response ordering.

#### AUD-26 — P2: Self-evolution path escape and false “promoted” status

**Evidence:** Dirty/advanced `agent/evolution-persona/brain/evolution/controller.py:108-120` joins user-provided relative path without resolved containment checking. `:134-153,192-204` can label a commit promoted but does not merge it before deleting its temporary worktree/branch.

**Impact:** A traversal/absolute path can write outside the temporary worktree; the auto-safe path can report success while discarding the change.

**Action:** Reject absolute/traversal/symlink escapes before any access; make promotion truthfully merge through a separately approved gate or fail closed to proposal. Do not expose the controller until tests cover these cases.

#### AUD-27 — P2: `usage_status()` is not a bounded read as documented

**Evidence:** `brain/router/status.py:27-40` reads the entire JSONL file, then keeps the last `tail` lines. Main’s usage log is append-only and has no observed rotation policy.

**Impact:** `/status` latency and memory use grow with uptime despite the “tail” contract.

**Action:** Read from end in bounded chunks or rotate/compact; test large logs and damaged final lines. Preserve value-blind metadata-only logging.

#### AUD-28 — P2: Timer scheduler needs atomic claiming/idempotency

**Evidence:** `brain/tools/schedule/__init__.py:300-323` selects pending due rows, submits work, and only later records success. There is no atomic claim/lease before submission.

**Impact:** Two Brain instances or a crash between submission and update can fire a reminder/recurring task twice. The schedule startup hook is also not wired on main per tools-memory’s outstanding request.

**Action:** Add atomic claim/lease and idempotency key semantics, integrate arm/disarm at app lifecycle, and test two pump instances plus crash-after-submit recovery.

#### AUD-29 — P2: Latency evidence is incomplete and fresh voice latency remains material

**Evidence:** `docs/ARCHITECTURE.md:97-100` still marks latency instrumentation unbuilt. Dirty `agent/brain-core/brain/latency.py` keeps latest samples, not distributions. Voice lane notes report fresh Fish first-audio seconds and stress fallback gaps; cache hits are much faster.

**Impact:** A latest-value snapshot cannot prove p50/p95 or the end-to-end “near-instant” target. Batching and pre-roll improve continuity but may add first-audio delay.

**Action:** Define stage boundaries and SLOs, record bounded value-blind histograms, measure fresh/cache/STT/LLM/tool paths under realistic load, and report tradeoffs rather than claiming a single-sample target.

#### AUD-30 — P2: Orb IPC/security posture needs production hardening

**Evidence:** `body/orb/package.json:8-10` starts with `--no-sandbox --disable-gpu-sandbox`; `body/orb/src/main/main.js:306-331` sets `sandbox:false`. Context isolation is enabled and Node integration disabled, which are good. Main has no `will-navigate`/window-open restriction found; exposed IPC handlers at `:576-620` do not validate sender/origin. Electron 30.5.1 is pinned in `package.json:19-22`, outside Electron’s latest-three-major support policy.

**Impact:** A renderer compromise has fewer OS/process protections and broad access to the preload bridge; unsupported Chromium/Electron receives no current security fixes.

**Action:** Upgrade to a supported Electron version, restore sandboxing, prohibit navigation/window creation except explicit safe handlers, validate IPC sender and payloads, and keep the bridge minimal. Review WSL-only flags separately and do not weaken production builds to satisfy test harnesses.

#### AUD-31 — P2: Build/run portability and integration claims drift

**Evidence:** `scripts/setup.sh` points to absent `brain/requirements.txt` and emits a stale unit example. Fish build hardcodes a developer path. `body/orb/package.json` defines `lint` as an echo. The lane worktrees contain fixes not present in main; their own reports include different test baselines.

**Impact:** Installation, lint, and “green lane” status can be mistaken for reproducible integrated validation.

**Action:** Correct docs/scripts from one canonical config/lock source; make lint/type/security commands real; require a CI run ID on `wave_done`; report merged-tree CI evidence only.

#### AUD-32 — P2: Voice/Body/Fish subprocess lifecycle and environment require least-privilege review

**Evidence:** `brain/voice/tts.py:390-425` launches Fish from an ignored vendor checkout, inherits `os.environ`, logs to a non-rotated file, and can wait up to 240 seconds for startup (`:438-476`). The build script has floating dependency ranges. The Body’s runtime-pip changes are only on lane branches.

**Impact:** Supply-chain drift, credential inheritance, large logs, and long first-request delays can affect privacy and responsiveness.

**Action:** Pin vendor revision/dependencies; minimize Fish environment; rotate/cap logs; test stop/restart/orphan behavior and startup latency. Integrate the Body no-runtime-pip work and make installer consume its verified lockfile.

## Positive controls worth preserving

- `brain/run.py` defaults to `127.0.0.1`; relay listeners avoid wildcard binds.
- Token comparison uses `hmac.compare_digest`; the Brain refuses missing tokens.
- Body actions reject extra arguments and validate values before dispatch.
- The computer-use screenshot path has pre-send checks, and the journal summarizes screenshot base64 instead of storing it.
- Private mode has router-level zero-egress tests; keep those strict as config loaders converge.
- CI/test harnesses mostly use mock providers and temporary tokens/DBs; preserve the no-live-stack contract.

## Integrator acceptance checklist

1. Preserve both dirty worktrees and inspect current lane heads before assigning duplicate work.
2. Treat AUD-01, AUD-02, AUD-03, AUD-05, AUD-06, and AUD-07 as blockers before claiming privacy/security closure.
3. Integrate lane fixes only in merge order, with a green CI run ID and strict regression tests on the merged tree.
4. Keep the scheduled task and root WSLg unit disabled; no paid/live/provider tests, elevated operations, or secret reads during remediation without separate user approval.
5. Route repo visibility/history, media licensing, service installation, and any destructive migration to the human; do not make those decisions silently.
6. Update `docs/AUDIT-2026-10-07.md` only with evidence and the exact main/branch status after integration.

## Reference links

- Electron supported release policy: <https://electronjs.org/docs/latest/tutorial/electron-timelines> and <https://releases.electronjs.org/schedule>.
- Electron security checklist: <https://electronjs.org/docs/latest/tutorial/security>.

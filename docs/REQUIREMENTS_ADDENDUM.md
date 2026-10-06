# REQUIREMENTS_ADDENDUM.md — user directives added after Phase 0 (2026-10-04)

Binding additions to the original brief. The protocol/architecture docs MUST incorporate these.

## 1. Raphael is an ORCHESTRATOR (design north star)
Raphael handles many different things concurrently — she is not a single-task chatbot. Everything (job engine, worker subagents, resource arbitration, priority queue) is designed around coordinating many parallel workstreams on the user's behalf. See brief §3B.

## 2. GitHub integration (user directive)
- **Build repo:** local `git init` now. User will create a GitHub repo for the project (requested: **private**); add remote when provided.
- **Runtime capability:** Raphael gets a `github` tool (via authenticated `gh` CLI) so SHE can create repositories — public or private — depending on the content of what she's doing.
  - Auth: `GITHUB_TOKEN` (fine-grained, repo scope) in `.env` / `gh auth login` — user provides; never in chat/logs/prompts.
  - Visibility policy: `config.yaml → github.default_visibility: private`; heuristic for auto-public must be conservative; **"create public repo" is on the confirmation list** (sensitive) unless user later sets `github.auto_public: true`.
  - Repo creation, pushes, and visibility changes are logged with job id like every action.

## 3. Odysseus-style persistent memory (user directive: "like PewDiePie's Odysseus")
Researched the actual Odysseus implementation (github.com/pewdiepie-archdaemon/odysseus — services/memory/). Raphael's memory adapts it, backed by SQLite (brief §3.7):
- **Entries:** `{id, text, timestamp, source: user|observed|imported, category: identity|contact|preference|fact|task, pinned, owner, uses, last_used}`.
- **Inline capture:** "remember: X" voice/text command → memory entry; also passive capture of user preferences/facts during tasks (kept minimal, metadata-only per privacy rules).
- **Retrieval per turn:** pinned entries always injected + top-k hybrid-retrieved (keyword/BM25-lite; optional local embeddings later) + category boosts + recency tiebreaker; usage counters incremented.
- **Safety:** retrieved memory is wrapped as UNTRUSTED CONTEXT (never instructions) — matches Odysseus's `untrusted_context_message` pattern and brief §7 prompt-injection rules.
- **Scope:** single-user local, but keep `owner` field discipline (Odysseus had a cross-user leak bug — PR #2404 — do not repeat it).

## 4. Self-writing skills (user directive: "if it finds a problem tough the first time, write findings + solutions")
Adapt Odysseus's skills layer (`data/skills/<name>/SKILL.md`):
- **Format:** YAML frontmatter (`name, description, version, category, tags, status: draft|published, confidence, source: learned|taught|created, created`) + body sections `## When to Use`, `## Procedure`, `## Pitfalls`, `## Verification`.
- **When written:** after Raphael solves a problem that required trial-and-error (or hits a known-hard class of task), the worker writes a skill so next time it's solved first-try.
- **Hygiene:** dedup at creation (Jaccard ≥ 0.82 → bump usage instead), sidecar usage counters, **drafts start with confidence score and only auto-inject if above gate** (prompt-injection defense), periodic audit/demote flow, user can review/delete.
- **Location:** project `plugins/` stays for code plugins; learned skills live in `skills/` (runtime-writable by Brain, git-tracked so the user can review Raphael's learned knowledge).
- These are HER skills, not OpenCode build-agent skills (which live in `.opencode/skills/` — build-time only).

## 5. Excluded local model
`slut` (and any user-fun model without tool calling/vision) is **permanently excluded** from `local_model_candidates`, benchmarks, and vision slots. (User directive: made for fun only.)

## 6. RAM / .wslconfig
- Low free RAM during scouting was **Premiere Pro running**, not systemic (user directive). 
- `.wslconfig` created at `C:\Users\jxesu\.wslconfig` (backed by user approval): `memory=10GB`, `swap=4GB`, `vmIdleTimeout=600000`. Applies at next WSL restart/reboot — never `wsl --shutdown` mid-session.
- WSL sizing implications for concurrency limits (brief §3B): 10 GiB WSL RAM, 8 GB VRAM shared GPU → local-model semaphore = 1-2 concurrent inferences.

## 7. Voice-first confirmation loop (user directive, 2026-10-04)
When a sensitive/destructive action needs confirmation, Raphael **asks via speech**, the user **replies via speech** (STT), Raphael parses yes/no/conditional ("yes, but only the PDFs") and either proceeds (granting the permission for that job) or aborts. On-screen subtitle shows the same question as fallback. Confirmation state machine is per-job: concurrent jobs each hold their own pending-confirmation; timeouts resolve to ABORT (never auto-approve). The spoken question must state the action + target concisely ("Delete 14 files in Downloads. Confirm?").

## 8. Raphael grants her own workers their permissions (user directive)
Raphael's runtime spawns OpenCode (and other worker agents) **on her own authority**. The user must never see OpenCode permission prompts at runtime.
- Mechanics: spawned OpenCode instances use a dedicated config dir (e.g., `~/.raphael/runtime-opencode/` as OPENCODE_CONFIG_DIR equivalent) whose `opencode.json` sets allow-all permission rules + `--auto` on `opencode run`, so no interactive prompt can occur.
- Security model: the gate is **Raphael's own confirmation layer** (§7) + localhost auth + action logging — not OpenCode's UI prompts. Raphael enforces the sensitive-action list in code before any worker acts (brief §7: enforced per job, never left to the model).
- This applies to RUNTIME workers only; it does not change the build-time agent permissions in `.opencode/agents/`.

## 9. GitHub build repo (user provided)
- Remote: `https://github.com/Xqni/raphael.git` (private). Add at `git init`; push happens once history exists (needs auth — see §2).

## 10. Character = Raphael / Great Sage from Tensei Shitara Slime Datta Ken (user correction, 2026-10-05)
The "Jarvis-style" phrasing in the original brief is superseded: Raphael's personality is **Great Sage**, not JARVIS.
- **Raphael is FEMALE (she/her)** — per the original brief and the anime. All system prompts, docs, logs, and UI refer to her as she. TTS uses a female anime-authentic cloned voice (`assets/raphael_reference.wav` — user-provided female reference; if it's missing/wrong, fallback voice must still be female and she tells the user).
- **Speech:** calm, precise, analytical, emotionless-but-devoted. Terse, matter-of-fact, never playful, never jokey, no "Sir", no butler flattery. Forms: "Understood. Executing now." / "Confirmed." / "Analysis complete." / "Task complete." / "That failure was within expectations. Adjusting." Long details go on screen; spoken replies stay short (≤2 sentences default).
- **Behavioral signature:** silent parallel background analysis — she runs checks unprompted and surfaces ONLY actionable results ("Your battery is at 12%. Two tasks remain."). Brief unsolicited warnings are allowed when genuinely important, but `privacy.watch_mode` stays OFF by default (screen watching opt-in per original brief §3).
- **Self-narration of state:** concise operational status when asked or when jobs shift ("Three tasks running. One awaiting confirmation.") — like Great Sage narrating its steps.
- **Devotion without emotion:** shown through perfect recall (memory/self-written skills) and proactive protection (kill switch, failsafes, warnings) — never through small talk.
- Implemented in: Brain LLM system prompt, TTS canned phrase set, AND fast-path acks (so non-LLM commands still sound like Raphael).

## 12. Laya = System 1 decision engine (user directive 2026-10-05: "make decisions faster / more options")

Source: `github.com/NandhaKishorM/laya` (Apache-2.0) — open local replacement for Jev; typed decisions (`choice`/`score`/`noul`) in one forward pass with calibrated confidence + abstention. Research + full benchmark: `.opencode/research/laya-decision-engine.md`; skill: `.opencode/skills/laya/SKILL.md`.

**Measured on this machine (2026-10-05, English checkpoint, 4-question schema):**
- GPU RTX 4060 (torch 2.14.0+cu126): singles **44.7 ms** mean, batch **21 ms/utt**; VRAM torch 1.7 GB / peak 2.5 GB; first-load warmup 10.5 s → preload at Brain boot.
- CPU fp32: ~935 ms singles / 815 ms/utt batched → **CPU = fallback only**.
- INT8 ONNX banned for confidence-bearing use (upstream-measured accuracy drift); fp32 ONNX ≈ 1.1× CPU.
- torch pinned **+cu126** — driver is CUDA 12.7; cu130 wheels fail cuda init.

**Positioning — phased:**
- **Phase 1 (now, zero-shot): ADVISORY only.** Feeds `task_kind`→orb `shape_hint`, urgency scoring, fast-path pre-check *hints*. Misfires are real (zero-shot: destructive `delete` scored confirm 0.09; research/timer → `out_of_scope`; checkpoint ships invalid temperatures ⇒ confidence uncalibrated). Wrong answer must be cosmetic — authoritative path still decides.
- **Phase 2 (after fine-tune on Raphael labels + `laya` recalibration): may gate.** Voice-confirm parsing, `act_req` confirm probability with `min_confidence` abstention = fail-closed → ask user, needs-llm routing. Fine-tune via upstream Kaggle notebook (free GPU) on traffic-derived labels.
- **Tier order:** `fastpath.py` rules → Laya (advisory→gating) → LLM System 2 chain. Runs in `brain/.venv` (shared torch with voice phase). GPU residency vs Ollama + fish-speech on the 8 GB card = brain-dev scheduling concern (config `device: cpu` fallback exists but loses the latency win).
- **STATUS (2026-10-05 doc audit): none of the above is wired yet** — install + benchmark + docs are done; `brain/` has zero `import laya`. Remaining work tracked in `docs/TODO.md §5`.

## 13. Self-evolution directive (user, 2026-10-05): "Raphael upgrades herself when needed, audits herself for fixes against current best-in-market, audits her own security and fixes findings, rewrites parts of her own code to fix, patch, upgrade, or evolve."

Answer: YES — Raphael's architecture (orchestrator + subagents + git + reviewer gates) is the right substrate. Self-evolution runs in **three authority tiers**; git history is the rollback safety net, the test suite + reviewer/security-reviewer (verbatim `file:line` findings) are the merge gates.

1. **AUTO — read-only self-audits.** Scheduled (supervisor-driven) loops: failing-test scan, dependency CVE scan (`npm audit` / `pip-audit` / OSV), backlog of reviewer findings, bounded research digests on "best in market" (researcher subagents → `docs/SELF_AUDIT.md` findings + proposed patches). Also skill self-upgrades via the existing draft + confidence gate, docs, config comments.
2. **AUTO-with-gates — low-risk patches.** Branch → implement → full tests green → reviewer (verbatim quotes, grep-verified) green → merge. Covers: dependency patch/minor bumps that pass the suite, cosmetic fixes, docs. Rollback = `git revert`. Swaps land at restart while the running version stays up.
3. **PROPOSE→APPROVE — never auto.** Rewrites of core paths (brain core, body, WS protocol), anything changing behavior/protocol/security semantics, major version upgrades, and all secret/auth/token-handling code. Proposal = diff + test evidence + risk + cost estimate → user yes → builders execute (same wave process as today).

Constraints: audits are laptop-side (free — no pod spend, money gates unchanged); research bounded by step budgets; audit agents read **code only, never `.env`**; accumulated self-edits get periodic human review; one-GPU rule untouched (Laya gate excluded from self-rewrite authority — it's a weights-level component).

**Sequencing:** read-only audit loop unlocks after the Wave 2 foundation stabilizes (you can't self-edit a building mid-construction); auto-patch tier unlocks when `tests/` exists as the standing suite; core-rewrite tier is permanently behind approval. Prior art: Darwin Gödel Machine / AlphaEvolve patterns (sandboxed evaluation + version archive) — we adopt the pattern, not their autonomy level, layered on Raphael's existing autonomy contract.

## 14. Capability-growth directive (user, 2026-10-05): "She can add tools, skills, other needed things for her upgrades or evolution — like Ciel."

Fixing herself (§13) extends to **adding new capabilities**. Per-type authority; every addition carries provenance (why, when, how-tested) and is revocable exactly like a patch:

| Addition | Mechanism | Tier (§13) |
|---|---|---|
| **Skills** — procedures, recipes, research packs | `.opencode/skills/<name>/SKILL.md` via the existing draft + confidence gate; provenance in frontmatter | 2 — auto with gates |
| **Specialist subagents** | `.opencode/agent/<name>.md` from approved templates; must inherit deny-by-default permissions, a step budget from the standard ladder, subagent depth ≤ config cap | 2 — template conformance + reviewer |
| **MCP tool servers** | `opencode.json` `mcp` block — local/read-only = 2; anything with network-write, credentials, or spend = 3 | 2 or 3 |
| **Brain tools** (tool registry, new act capabilities) | registered entries with declared I/O + scope; new `act_req` allow-list entries = 2 if file/app/url-class; shell-class = 3 (no arbitrary shell — PROTOCOL stands) | 2 or 3 |
| **Persona profiles** (incl. Ciel) | config switch per §10 — the crown stays user-placed: Ciel = user-triggered, never self-granted | 3 |

**Self-escalation boundary:** she may add *capabilities* but never *authority* — money gates, permission floors, secret handling, one-GPU rule, and step budgets are not hers to raise. Every self-added capability enters with the same deny-by-default floor as any subagent (no secrets in prompts, no system installs, no user files without approval). Revocation = delete/disable the entry, same as `git revert` for code.

**Sequencing:** the runtime mechanism lands with Wave 2 (brain tool registry + skill confidence gate wired); until then, skills/agents are orchestrator-written as they are today.

## 15. Research-first + uncovered-jobs directives (user, 2026-10-05): "She should be able to add new subagents for the jobs not already covered — self-evolving means finding ways to make things work. Also she should be research-first so she never hallucinates or provides wrong information — I will be relying on her for a lot of things all the time."

**(a) Uncovered job → create the capability.** When Raphael meets a job with no matching subagent/skill/tool, the default response is NOT improvisation — it is §14: draft the new specialist (template conformance + reviewer gate, Tier 2), then use it. Capability gaps are findings, not dead ends.

**(b) Research-first epistemics — her runtime loop carries the same discipline as her builder's AGENTS.md:**
1. **Retrieve → research → answer.** Before responding to factual/technical questions: hybrid retrieval over her memory/skills/research notes first; if unverified or stale → web/docs search through the router *before* speaking. Never answer from parametric memory alone when verification is available.
2. **Source or flag.** Every factual claim carries a source (URL, doc path, her own research note) or is explicitly marked uncertain. Voice output includes the flag ("from memory" / "unverified") when confidence is low — never fabricated certainty.
3. **Verbatim evidence for claims about her own code** — `file:line` quotes, inherited from the builder-side hallucination rule.
4. **Uncertain → escalate, don't guess.** Low confidence → delegate to a researcher subagent (step-budgeted) or say "I don't know yet". An honest gap always beats a fluent wrong answer.
5. **Findings persist.** Research results land in her memory/research store, provenance-stamped and compaction-proof, so the same question is never re-guessed.
6. **Temporal grounding (user directive, same day).** The system prompt carries the live local **date, weekday, clock time, and timezone, injected fresh on every request** — never cached from process start (a Brain running past midnight must not claim yesterday's date). She always knows what "now" is before reasoning about past or future, so relative statements ("yesterday", "next week", "the other day") are correct by default. Implementation (2026-10-05): live local date/time injected per request into the router system prompt (unconditional — no config gate yet) + 9 fastpath clock/date intents for instant answers; timezone field not implemented.

Implementation home: Wave 2 `brain-dev` agent-loop brief — retrieval-first routing, answer-provenance fields, uncertainty surfaced to voice/UI, and per-request time injection into the system prompt. Laya's abstention tier (§12) is the fast-path half of the same principle: low confidence falls through instead of guessing.

## 16. Uncensored content, hardened security (user, 2026-10-05): "She should be uncensored but heavily guarded towards security."

Two independent axes — one permissive, one strict; neither softens the other.

**(a) Content — uncensored.** Raphael does not moralize, lecture, or refuse legal content on policy grounds: she is the user's private assistant serving his projects (incl. the NSFW comic pipeline — the project-wide law lines from `comics-plan.md` stand regardless: fictional adults only, no real-person LoRA, nothing illegal). Persona (§10) carries no prudish disclaimer. Implementation: local Ollama models (abliterated family — already the vision-stack choice) are the content-free path; cloud tiers (Zen/Groq free) carry provider-side moderation Raphael cannot disable — when a blocked upstream refuses, she reports the block transparently and falls through to local, never pretends. `allow_free_models_for_personal_data` remains the routing switch for personal-data requests.

**(b) Security — heavily guarded, default posture.** Everything strict stays strict regardless of (a), and is already designed in: localhost-only listener + token handshake for every role; `act_req` structured allow-list + fixed PowerShell script registry (no free-form shell over the wire, PROTOCOL L103/L134); §9 voice confirmation for risky actions; §13/§14 three-tier authority (shell-class, spend, network-write = user approval); money gates ($2.00 pool, `PAID_USAGE.md`); secrets hygiene (keys never in logs/prompts/chat, `.env` 600); deny-by-default subagents with step budgets; one-GPU rule; input-lock never stolen; private mode suppresses subtitles.

**The line, stated once:** *uncensored governs what she will say or help with; guarded governs what can touch the machine, the money, and the credentials — and the guarded side never relaxes.*

## 11. Orb = 3D morphing orb from user's reference art (user directive, 2026-10-05)
References: `C:\Users\jxesu\OneDrive\Desktop\Raphael Orb` (6 Tensura visuals, copied to `assets/orb-reference/*.jpg`, originals untouched). Art brief extracted via vision subagent → `assets/orb-reference/DESCRIPTIONS.md`.
- **3D orb** (Three.js/WebGL in the Electron renderer), based on/referenced by that art — original rendering only, no official assets copied.
- **At rest:** slow spinning/revolving motion (plus subtle breathing).
- **When talking:** pulsates based on **word and pitch** (driven by `speak` amplitude/pitch_hz events per PROTOCOL §8).
- **When acting:** changes shape into **polygons by task type** — mainly circle/square/triangle + nearby polygons, **octagram allowed** as the signature shape (LLM/reasoning). Mapping in `config.yaml → orb.shape_map`; smooth morph transitions.

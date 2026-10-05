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

## 13. Self-evolution directive (user, 2026-10-05): "Raphael upgrades herself when needed, audits herself for fixes against current best-in-market, audits her own security and fixes findings, rewrites parts of her own code to fix, patch, upgrade, or evolve."

Answer: YES — Raphael's architecture (orchestrator + subagents + git + reviewer gates) is the right substrate. Self-evolution runs in **three authority tiers**; git history is the rollback safety net, the test suite + reviewer/security-reviewer (verbatim `file:line` findings) are the merge gates.

1. **AUTO — read-only self-audits.** Scheduled (supervisor-driven) loops: failing-test scan, dependency CVE scan (`npm audit` / `pip-audit` / OSV), backlog of reviewer findings, bounded research digests on "best in market" (researcher subagents → `docs/SELF_AUDIT.md` findings + proposed patches). Also skill self-upgrades via the existing draft + confidence gate, docs, config comments.
2. **AUTO-with-gates — low-risk patches.** Branch → implement → full tests green → reviewer (verbatim quotes, grep-verified) green → merge. Covers: dependency patch/minor bumps that pass the suite, cosmetic fixes, docs. Rollback = `git revert`. Swaps land at restart while the running version stays up.
3. **PROPOSE→APPROVE — never auto.** Rewrites of core paths (brain core, body, WS protocol), anything changing behavior/protocol/security semantics, major version upgrades, and all secret/auth/token-handling code. Proposal = diff + test evidence + risk + cost estimate → user yes → builders execute (same wave process as today).

Constraints: audits are laptop-side (free — no pod spend, money gates unchanged); research bounded by step budgets; audit agents read **code only, never `.env`**; accumulated self-edits get periodic human review; one-GPU rule untouched (Laya gate excluded from self-rewrite authority — it's a weights-level component).

**Sequencing:** read-only audit loop unlocks after the Wave 2 foundation stabilizes (you can't self-edit a building mid-construction); auto-patch tier unlocks when `tests/` exists as the standing suite; core-rewrite tier is permanently behind approval. Prior art: Darwin Gödel Machine / AlphaEvolve patterns (sandboxed evaluation + version archive) — we adopt the pattern, not their autonomy level, layered on Raphael's existing autonomy contract.

## 11. Orb = 3D morphing orb from user's reference art (user directive, 2026-10-05)
References: `C:\Users\jxesu\OneDrive\Desktop\Raphael Orb` (6 Tensura visuals, copied to `assets/orb-reference/*.jpg`, originals untouched). Art brief extracted via vision subagent → `assets/orb-reference/DESCRIPTIONS.md`.
- **3D orb** (Three.js/WebGL in the Electron renderer), based on/referenced by that art — original rendering only, no official assets copied.
- **At rest:** slow spinning/revolving motion (plus subtle breathing).
- **When talking:** pulsates based on **word and pitch** (driven by `speak` amplitude/pitch_hz events per PROTOCOL §8).
- **When acting:** changes shape into **polygons by task type** — mainly circle/square/triangle + nearby polygons, **octagram allowed** as the signature shape (LLM/reasoning). Mapping in `config.yaml → orb.shape_map`; smooth morph transitions.

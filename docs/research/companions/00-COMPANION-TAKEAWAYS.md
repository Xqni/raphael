# 00 — COMPANION TAKEAWAYS (what we can take from Grok bots / OpenAI Dots / Meta Muse)

**Date:** 2026-10-09 · **Author:** integrator · **Inputs:** `01-grok-bots.md`, `02-openai-dots.md`, `03-meta-muse.md` (all three verified-sourced), cross-checked against our persona canon (`../persona/00-CONSOLIDATED-BRIEF.md`) and the R4/R5 gap/decision set.

**Verdict up front:** the market has converged on our exact shape — always-on, voice-first, small animated orb, persistent memory, act-with-confirmation. Six of the "obvious takeaways" are things we already ship (called out below as validation). The genuinely NEW and worth-adopting list is short: **context slots, clarify-on-ambiguity, user-editable confirmation policy, and a memory-privacy affordance pass**. Everything else is context we chose against, on record.

## 1. Already shipped — market validation (do NOT re-build)

| Market pattern | Where it already lives in Raphael |
|---|---|
| Small animated orb with idle/thinking/speaking/working states (Dots, Muse avatar) | Orb cage + 8 states + speaking pulse (wave-2/3 gates; `docs/orb/`), deliberately text-free per the user's directive |
| Voice-first with instant response | fastpath acts at 0.0–0.55 s; chat on go/mimo; STT close→subtitle ~550 ms (measured floor recorded) |
| Persistent per-user memory | `brain/memory/**` (retrieval, reports, conversation; owner-scoped) |
| Confirm-before-impactful-action ("Should I send that?", Muse's explicit dialogs) | confirm system: `risky` registry, AUD-11 gui_submission gates, voice-confirm parsing (in progress), Core Guard |
| Proactive-with-confirmation (Grok suggestions, Muse always-on) | proactive Notice events (PROTOCOL §3), pending the AUD-06 consent-vs-PTT human gate |
| Usage/budget tiering (Grok pricing tiers, Dots paid tiers) | SEC-8 budget ledger: daily $1 + $10 total caps, `E_BUDGET` fail-closed (wave-5H) |
| Multimodal "drop a screenshot" (Grok vision) | `see_screen`/screenshot + cloud vision behind the blocklist/redaction gate + foreground egress gate |
| Cross-session continuity (Muse, Dots) | multi-turn context + memory injection per turn (`brain/loop.py` `_external_context`) |

## 2. Genuinely new — ADOPT candidates (S/M, wave-6 eligible after the user says go)

| # | Takeaway | Source | Why it fits Raphael | Effort | Note |
|---|---|---|---|---|---|
| A1 | **Clarify-on-ambiguity** — when a voice command is ambiguous, ask one short clarifying question instead of guessing | Muse | Canon service model: she defers when intent is unclear; reduces wrong-window/wrong-file acts | **S** (prompt-layer + fastpath miss path) | Voice lane + brain-core |
| A2 | **User-editable confirmation policy** ("auto-review rules" in Dots) — let the user declare which action classes auto-run vs always-confirm, config-driven, no code change | Dots | Directly extends the R1 finding (hard-coded risk regex → config) and R5's `config-confirm-categories` BUILD CUSTOM item; makes her confirm behavior *the user's* policy | **S/M** | Config (`safety.*`, Core-Guard-adjacent) + confirm.py |
| A3 | **Named context slots** ("side-chats": shopping, travel, work) — short-term topic memory the user can switch between without losing context | Muse | Our jobs are global; slots give task-scoped context cheaply; maps onto memory `kind=` awareness | **M** | tools-memory + brain-core |
| A4 | **Memory-privacy affordance pass** — one spoken command for "what do you remember about X / forget X" with a user-facing wipe | Muse (Library + wipe), Dots (memory reset) | Trust surface; private mode exists but memory inspection/wipe by voice is the visible version | **S** | verify against existing memory export/delete first (TODO wave-4 item) |

## 3. DEFER — real but gated

| Takeaway | Gate |
|---|---|
| Background proactive suggestions (Muse always-on, Grok idle prompts) | AUD-06 consent-vs-PTT is a standing HUMAN decision; Notice events already exist as the substrate |
| Cross-device preference sync | Privacy/local-first stance: sync via the vault for persona/docs only; never secrets. Revisit with the user |
| Grok-style multi-agent internal chatter ("bot as team member") | L-effort, speculative; our lanes already do coordination *outside* the runtime |

## 4. Explicitly NOT taken (with reasons)

- **Social-timeline integration, marketplace app stores, mobile/chat UIs, AR/glasses holograms** — wrong product shape for a personal desktop agent.
- **Cloud-VM-only execution (Dots)** — the opposite of our design: Raphael's OS control stays **local** for privacy and latency; cloud is for LLM/vision/STT compute only (project mandate).
- **Enterprise bot licensing** — personal tool.
- **Mouth/avatar anthropomorphism on the orb** — user's aesthetic is the abstract cage with pulse states; a mouth/holo direction was rejected by design history (2D/rings feedback).

## 5. Priority if the user opens wave 6

1. A2 confirmation policy (rides the existing R5 "confirm categories" item — biggest trust win, S/M).
2. A1 clarify-on-ambiguity (S — instant quality-of-interaction gain).
3. A4 memory-privacy spoken affordance (S — verify existing delete/export first).
4. A3 context slots (M — the only genuinely new subsystem).

## Honesty notes

- "OpenAI Dots" and "Meta Muse" were confirmed to be real products (Dots: always-on persistent agents with orb states and custom auto-review rules; Muse: Meta's personal agent launched 2026-09-08) — verified in the scout reports with URLs, not assumed.
- Effort bands are the scouts' estimates cross-checked by me against our codebase; treat A-bands as ±1 step until a lane sizes them.
- No code, dependencies, or runtime state changed; lanes remain paused.

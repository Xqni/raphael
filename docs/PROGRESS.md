# PROGRESS — Wave 5U (USEFUL-NOW sprint)

Owner plan: `docs/USEFUL-NOW-PLAN.md`. This log records real, run results only.

---

## Wave A — P0 foundations & safety — MERGED (all 8 lanes), demo run 2026-10-10

### Merge log (fixed 5U order, each with ownership + battery + guard + gitleaks)
| # | Lane | Head | Result |
|---|---|---|---|
| 1 | brain-core | c5e131f | P1 tier runtime, navigate pairing, P3 confirm policy LIVE, P0 batch (typed_confirm, needs_confirm fields, admission input-lock, foreground legibility, derived latency) |
| 2 | pc-control | (merge) | navigate_url in-place act + confirm-class tags on all pc tools |
| 3 | voice | 81cd030 | Synth seam + Kokoro-82M, tier warmth, wake-loop regression, P0-urgent grace |
| 4 | orb | 4b86c3b | ORB CONFIRM CARD (pre-approval 3) |
| 5 | infra | 5adfb9d | helper zombie-guard + supervisor watchdog + bind self-check + one-command start + CLI verbs |
| 6 | qa-security | e0d4cd5 | Wave-A gate tests A-D + personal-routing + mutations |
| 7 | tools-memory | 2420160 | P5/P6/P7 (slots, memory privacy, journal) + confirm-class tags on 6 namespaces |
| 8 | evolution-persona | 1bc641a | 5P-P1 tier prompts + debunk lint + fragment tier sync |

Final battery after batch: **brain 1231 green, root 220 green, Core Guard OK, gitleaks no leaks.**
Main pushed. Integration collisions fixed en route: registry re-discovery glue (pc × brain-core); two qa transitional tests (comment-aware gate scan, P3 class wording).

### Owner call applied 2026-10-10
- **Kokoro = default TTS engine** (`voice.tts_engine: kokoro`, preset `af_heart`); fish = optional JP-clone tier only.
- `agent.speak_batch_sentences: 1` / `speak_batch_wait_s: 0` (kokoro speaks first sentence ASAP) — set in the brain-core fragment (INTERFACES §c knob home).

### Wave A live demo — PARTIAL PASS (2026-10-10)
Stack brought up one command (supervisor via scheduled task + brain + body + orb/WSLg + relay). Relay watchdog **respawned a dropped helper live** (finding-3 verified).

| Check | Result |
|---|---|
| High-risk delete fires confirm gate | ✅ `raphael say "delete /tmp/notes.txt"` → `jobs_pending_confirm 1` |
| File survives until approved | ✅ `/tmp/notes.txt` intact pre-confirm |
| Terminal cancel clears pending | ✅ job → cancelled, `jobs_pending_confirm 0` |
| needs_confirm frame fields | ⚠️ not captured live (WS capture + CLI verb both hit handshake bug); fields pinned by qa golden + brain-core tests |
| voice "yes" rejected on HIGH | ⚠️ enforced in `Confirmer.resolve_ex` (test-covered), not demonstrated live (no voice input) |
| **Orb confirm card usable** | ❌ **BROKEN** — buttons unclickable (window is click-through), giant yellow X overlay, card covers orb centre, stale on cancel. Orb lane dispatched (urgent). |
| **`raphael confirm` CLI** | ❌ **BROKEN** — WS handshake `bad Sec-WebSocket-Accept` (hand-rolled client in `scripts/raphael_ws.py`; `websockets` lib connects fine). Infra lane dispatched. |
| `raphael latency` prints stages | ⚠️ verb works; no samples yet (needs voice turns) |
| Kokoro default + weights | ✅ engine kokoro live, weights+samples present, voice suite 188 green |

**Verdict:** the P0 safety layer works end-to-end at the brain (gate fires, no premature delete, cancel clears). The two user-facing surfaces (orb card, CLI confirm) have real bugs — both dispatched. Demo is NOT a full pass until those land.

---

## Wave B — OPENED 2026-10-10 (dispatched, in flight)
| Lane | Task | State |
|---|---|---|
| pc-control | §5.2 browser worker over CDP (same-tab) | dispatched |
| brain-core | §5.1 world-state + background task runtime + /history + speak:false | dispatched |
| voice | §5.3 local faster-whisper STT + verify kokoro speak-soon + ≤2.5s target | dispatched |
| orb | urgent confirm-card bug → then §5.6 Raphael Chat (PWA+Tailscale later) | dispatched |
| infra | confirm-verb WS bug (use websockets lib) + tasks/chat verbs | dispatched |
| computer-use | browser-act runner coordination (after pc worker) | queued |
| tools-memory | §5.4 persistent memory (P2) | queued |
| qa-security | guard Wave B landings | queued |

Deferred to owner presence: Kokoro voice pick (samples rendered), §4b live acceptance lines needing voice/memory/calendar.

## Human-only (unchanged — ATTENTION register)
Repo private, PAT rotation, history rewrite, branch protection, OAuth for mail/calendar (§4b lines 7-8), Node-on-Windows for orb ARCH-1, RAM upgrade (Wave 6 gate).

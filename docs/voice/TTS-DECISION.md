# TTS-DECISION — fish-speech vs PocketTTS (F-5 close-out)

**Decision: KEEP fish-speech as the default TTS.** (User's word, 2026-10-07;
record written for the Wave-5H audit — F-5.) Reopen PocketTTS **only after the
RAM upgrade + the user's explicit word** (criteria below). Owner: voice lane.
Status: **CLOSED — no code change to the default.**

## Measured numbers (same hardware: RTX 4060 / 8 GB RAM laptop, 2026-10-07)

| metric | **fish-speech 1.5 (live)** | PocketTTS fp32 | PocketTTS int8 |
|---|---|---|---|
| ask → first audio (fresh, 1 sentence) | **2.49 – 9.76 s** (whole-request; A/B log `gen 2.49/3.45/4.81/4.99/8.39 s`) | **79 ms** first stream chunk (full sentence 0.56–0.96 s) | 48 ms (0.30–0.60 s) |
| ask → first audio (cached phrase) | **0.015 s** (phrase-cache hit, `p0_gap_probe.json`) | n/a (separate cache) | n/a |
| real-time factor (audio-sec / wall-sec) | **×0.5** (slower than realtime) | ×3.0 mean | ×4.4 mean |
| memory | **2.88 GB VRAM** during gen (`fish_server.log`: "GPU Memory used: 2.88 GB"); CPU RSS not captured (stack down at record time — reopen this cell if the user wants it) | **1.45 GB peak RSS**, CPU-only (frees the GPU) | 1.45 GB peak RSS |
| voice cloning from our JP ref | **yes — live**, `sha1=f64bd512ea1e` proof line every synthesis | **BLOCKED** — `kyutai/pocket-tts` is HF-gated (`gated:auto` + prohibited-use form); our token only receives `pocket-tts-without-voice-cloning` | same block |
| EN intelligibility of output (whisper proxy) | 0.14 – 0.96 (the approved JP accent defeats EN-ASR — expected, not a quality verdict) | 1.00 on all 5 lines | — |
| maintenance / license | Apache-2.0 code; actively used | MIT / CC-BY-4.0, pushed same-day; **needs user HF terms acceptance** | — |

Full evidence: `brain/voice/EVAL-pockettts.md` (scripts:
`brain/voice/scripts/eval_pockettts.py`, `eval_ab_compare.py`).

## Blind A/B protocol (samples for the user)

- Files: `~/.raphael/voice/eval/decision_ab/` — `line01..05_{A,B}.wav`
  (same 5 canonical lines, same machine, same text; A/B labels randomized by
  coin flip), `README.txt` (judging guide), `KEY.txt` (**sealed** — open only
  after listening).
- Judges score per pair: (1) likeness to the approved great-sage voice
  (`assets/reference/samples/01_jp_slime_ref.wav`), (2) naturalness/prosody,
  (3) English intelligibility. The user's ear is the deciding vote — this
  record never overrides it in either direction.
- Un-blinded reference material: `~/.raphael/voice/eval/fish/` (engine=fish)
  and `~/.raphael/voice/eval/fp32/` (engine=PocketTTS).

## Latency threshold (Rule 15)

- **Threshold: spoken reply ask→first audio ≤ 3.0 s** for a fresh (uncached)
  sentence; cached acknowledgements effectively instant.
- fish today: meets it on most sentences (2.5–3.5 s typical), misses on long
  or contended ones (up to 9.8 s; fish serializes requests — measured 11.81 s
  for a 145-token sentence and 26.4 s when another client queued ahead).
  Mitigations already shipped: phrase cache, pre-roll/burst gapless delivery,
  mid-speak recovery; the gap probe shows **max inter-chunk gap 1.0 ms,
  zero holes >350 ms** post-fix.
- PocketTTS candidate: **79 ms** first chunk (int8: 48 ms) — comfortably
  inside the threshold (the reason to reopen, not to switch today).

### Rule 15 before/after (ask → first audio, fresh line)
- **Before (fish, live):** 2.49 – 9.76 s (first sentence), ≈0 s when cached.
- **After (PocketTTS candidate, measured):** 0.079 s first stream chunk /
  0.56 s first full sentence (fp32), CPU-only.
- Delta: **≈30–120× faster to first audio**, at the cost of an unproven voice
  (cloning gated) — hence KEEP fish.

## Reopen criteria (all must hold; then the user decides again)

1. **RAM upgrade installed** (PocketTTS costs ~1.45 GB RSS on an 8 GB box —
   the same RAM pressure that forced `cloud_temp`);
2. **HF gate accepted by the user** for `kyutai/pocket-tts` so the JP great-sage
   reference can be cloned (≈10 min rerun: `eval_pockettts.py` →
   `great-sage.safetensors` → our-voice A/B);
3. **Blind A/B judged acceptable by the user** (the sealed KEY above);
4. **The user's explicit word** — no default switch without it (F-5 rule).

Until then: fish stays the engine; PocketTTS eval artifacts stay on disk;
cost is not a factor (paid policy) — speed favors PocketTTS, voice fidelity
and readiness favor fish.

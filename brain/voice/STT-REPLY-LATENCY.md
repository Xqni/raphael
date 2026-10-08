# STT → reply latency — measurement + proposed cut (Wave 5H, voice lane)

Prompt: user — *"can we not make the STT real time"*. Verify-first: numbers
below are MEASURED on this box (2026-10-08) with the production-shaped path;
probe: `brain/voice/scripts/stt_reply_latency.py` (real Groq Whisper via
`router.transcribe`, real `to_thread` handoff, real wake gate, real
`engine.submit` + fastpath → first `subtitle` frame; TTS stubbed because the
subtitle fires synchronously BEFORE any speak event). Raw JSON:
`~/.raphael/voice/eval/stt_reply_latency.json`.

## 1. Current latency (5 runs, live cloud STT)

| stage | median | range | who owns |
|---|---:|---:|---|
| **S1 body VAD hangover** (last voiced chunk → `audio_end` sent) | **2 500 ms** | fixed (`SILENCE_CLOSE=25` × 100 ms frames) | voice (`body/win/audio_in.py`) |
| **S2 cloud STT** (`audio_end` → transcript, Groq whisper) | **576 ms** | 493–621 ms | router (RTT + model) |
| S3a wake gate | 0.1 ms | — | voice |
| S3b `engine.submit` | 2.5 ms | — | brain-core |
| S3c fastpath intent → `subtitle` | 0 ms | — | brain-core |
| **segment-close → subtitle (S2+S3)** | **578 ms** | 496–624 ms | — |
| **perceived: user stops speaking → subtitle (S1+S2+S3)** | **≈3 078 ms** | — | — |

Interpretation: **S1 is 71 % of the perceived wait, S2 is 19 %, everything
else is noise (≤1 %).** The brain-side handoff (gate/submit/fastpath) is
already effectively instant — there is nothing meaningful to cut there.

## 2. The cut, ranked

### Cut A — reduce the VAD hangover WITH continuation merge (saves up to ~1.3 s; needs brain-core)
- `SILENCE_CLOSE 25 → 12` (2.5 s → 1.2 s) so STT starts ~1.3 s sooner.
- Why plain reduction was REVERTED before: at 1.5 s it split live utterances
  (`PROGRESS.md`: *"split = wake in seg1 + command in seg2 → gate rejects
  BOTH — proven live"*).
- The split is fixed by treating a resume inside a grace window as a
  CONTINUATION of the same utterance:
  - **body (voice lane, ready to implement):** on close, if speech resumes
    within `GRACE_S` (1.5 s), send `audio_start` with
    `reason='continuation'` instead of a fresh `wake` segment (the mic keeps
    its buffer; no `audio_end` is sent until the utterance really ends).
  - **brain (brain-core, `brain/ws.py::_on_audio_start/_on_audio_end`):**
    `reason='continuation'` must APPEND to the previous buffer (not clear it)
    and `audio_end` transcribes the merged text once. Exact snippet in
    `docs/requests/voice__to__brain-core__utt-continuation-merge.md`.
- Net: close→STT starts at 1.2 s (was 2.5 s) with NO split regression,
  perceived ≈ **1.8 s** (was 3.1 s).

### Cut B — S2: ask router for the fastest Groq STT model (saves ~200–300 ms)
- S2 is pure provider RTT (493–621 ms with `rtf≈0.23` measured on a 3.7 s
  clip). `purpose="transcribe"` could target Groq's fastest Whisper-class
  model (e.g. `whisper-large-v3-turbo`) instead of the default — router owns
  model selection → request filed
  `docs/requests/voice__to__router__turbo-stt-for-purpose-transcribe.md`.
  Expected S2 ≈ 300–400 ms → close→subtitle ≈ **0.3–0.4 s** (with Cut A:
  perceived ≈ 1.5–1.6 s).

### Considered and REJECTED
- **Speculative partial STT** (transcribe the first ~1.5 s of speech while
  the user is still talking, submit early): rejected — a pause mid-command
  would submit a TRUNCATED command (same failure class as the 1.5 s split),
  and every utterance pays a 2× cloud cost for a prefetch that cannot safely
  trigger action.
- **Cutting S3**: measured 0.1/2.5/0 ms — nothing to cut.
- **Local STT for latency**: forbidden under `cloud_temp` (no local models),
  and faster-whisper would not beat 576 ms end-to-end anyway while costing
  ~1 GB RAM (the P0 that forced cloud_temp).

## 3. What lands now vs after sign-off
- NOW: this measurement + the two requests (brain-core continuation merge,
  router turbo model). No code change yet — Cut A's body half is only safe
  WITH brain-core's half (landing it alone would reintroduce the proven
  split), and Cut B is router's file.
- After sign-off: body `SILENCE_CLOSE`/continuation implementation (voice),
  ws.py append logic (brain-core), STT model choice (router). Re-run this
  probe + a live utterance split-test to verify: target
  close→subtitle ≤ 400 ms, perceived ≤ 1.7 s, zero split regressions.

---

## DECIDED (conductor, 2026-10-08) + final measured numbers

**Decision: ACCEPT THE FLOOR.** close→subtitle ~550 ms median (floor 396–477 ms =
Groq RTT + ASR for a 3.7 s clip; brain handoff ≤3 ms). ≤400 ms median is
unreachable on this link without a **closer STT provider** (standing option,
needs a human key) or the **speculative-partial path (stays rejected)**.
Cut A body half landed (SILENCE_CLOSE 12 + CONTINUATION_GRACE 13 = the old 25 →
zero split regressions proven by construction); Cut B landed neutral
(turbo median 643 ms vs v3 604 ms, usage-log A/B).

### Metric precision (so the numbers cannot be misread later)
| metric | value | definition |
|---|---|---|
| audio_end → subtitle | **554 ms median** (477–793; floor 396) | probe S2+S3 — the decided floor |
| VAD-close → subtitle | **≈1.85 s** | 1.2 s close + 1.3 s grace + 0.55 s STT |
| stop-speaking → subtitle | **≈3.05 s** (was 3.08 s) | close fires1.2 s after last speech, audio_end fires at close+grace (2.5 s — unchanged worst case, by design) |

**Arithmetic tension flagged (conductor's "~1.8 s perceived, ~45% better"):**
1.2 + 0.55 ≈ 1.8 assumes `audio_end` fires AT the 1.2 s close; the grace hold
(13 chunks) defers it to 2.5 s — which is exactly what keeps the merge
contract (`brain/tests/test_sec3_cloud_stt_gate.py`: no end between parts)
and the zero-split-regression proof intact. **Reaching stop→subtitle ≈1.8 s
WITH zero splits** requires the end-at-close variant where the brain's
AUD-17 audio worker transcribes immediately at close but HOLDS the result for
the merge window (discard the partial if a continuation arrives, else submit) —
that is brain-core's file; offered here as an optional follow-up (their call,
not started). With the accepted floor and the landed grace design, the honest
end-to-end numbers are: **audio_end→subtitle 0.55 s (floor accepted), stop→
subtitle ≈3.05 s (split-safe by construction)**.

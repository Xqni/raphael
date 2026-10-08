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

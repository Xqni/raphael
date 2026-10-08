# EVAL — PocketTTS (Kyutai) vs fish-speech · voice lane · 2026-10-07

Task: `docs/lanes/voice.md` "## TASK 2026-10-07". Research winner per
`.opencode/research/lightweight-tts-options.md` (KittenTTS disqualified — no
voice cloning; Voicebox not installable — weights never released).

**Rule 14 compliance:** offline in-process inference only — no second server
was ever started while the live fish server was up; both eval processes exited
by themselves (orphan check after every run: zero). HF token used presence-only.

Artifacts (outside the repo, nothing git-tracked):
```
~/.raphael/voice/eval/fp32/            # 15 renders + pockettts_eval.json
~/.raphael/voice/eval/q_int8/          # 10 renders + pockettts_eval.json
~/.raphael/voice/eval/fish/            # 5 renders (real fish payload)
~/.raphael/voice/eval/ab_report.json   # A/B table
~/.raphael/voice/eval/.venv-pockettts  # isolated venv (torch CPU intent; see caveat)
scripts: brain/voice/scripts/eval_pockettts.py, eval_ab_compare.py
```

## (a) Measured RSS on this box (8 GB laptop)

| stage | fp32 | int8 (`--quantize`) |
|---|---:|---:|
| after `import torch` (see caveat) | 546 MB | 546 MB |
| after `import pocket_tts` | 788 MB | 788 MB |
| **after `load_model`** | **1.23 GB** | **1.24 GB** |
| after 15 / 10 renders | 1.32 GB | 1.31 GB |
| **peak (VmHWM)** | **1.45 GB** | **1.45 GB** |

- **Cold first load (incl. HF download): 16.1 s** → 1.48 GB; warm load **0.87 s**.
- **No memory balloon**: RSS +89 MB over 15 renders (early `serve` 32 GB leak NOT
  reproduced on v3.2.x in-process; long-session retest still recommended before
  unattended use — 15 renders ≠ 24 h).
- **int8 did NOT reduce RSS materially** (weights are not the dominant term;
  torch runtime is). Its real lever is **speed**: mean RTF ×3.0 → ×4.4.
- Caveat: uv resolved `torch 2.14.1+cu130` (mirror index quirk, CPU index
  rejected `+cpu`), so the numbers above INCLUDE a CUDA torch build used on
  `device=cpu`. A pure `+cpu` wheel would trim the torch share — unmeasured,
  do not treat as fact.

## (b) Cloned reference state — **BLOCKED (user action required)**

`get_state_for_audio_prompt(assets/raphael_reference_jp.wav)` raises:

> We could not download the weights for the model with voice cloning … go to
> https://huggingface.co/kyutai/pocket-tts and accept the terms

- Repo is `gated: auto` with an extra prohibited-use form (verified via HF API,
  token presence-only). Our token only received
  **`kyutai/pocket-tts-without-voice-cloning`** (the cached repo).
- We did **not** accept terms on the user's behalf. **Ask: user accepts the HF
  gate once → rerun `eval_pockettts.py` → clone + `export_model_state` →
  `great-sage.safetensors` persisted + our-voice A/B** (≈10 min).
- Fallback used for metrics: catalog voice `alba` (recorded in JSON as
  `state.voice_used`). Clone/persist/reload path therefore UNVERIFIED so far.

## (c) A/B — exact live-stack sentences (`voice_personality.speech_forms`)

fish side = real `FishSpeechServer.synthesize()` payload (JP reference,
`use_memory_cache: off`) against the running server; PocketTTS side = fp32,
catalog voice. Transcript similarity = difflib ratio on faster-whisper-small
(EN) transcripts — a coarse intelligibility proxy, not strict WER.

| # | sentence | fish sim | pocket sim | fish pitch | pocket pitch | pocket auto-lang |
|---|---|---:|---:|---:|---:|---|
| 1 | Understood. Executing now. | 0.80 | **1.00** | — | 240 Hz | en |
| 2 | Confirmed. | 0.14 | **1.00** | 315 Hz | 190 Hz | en |
| 3 | Analysis complete. | 0.84 | **1.00** | — | 220 Hz | en |
| 4 | Task complete. | 0.96 | **1.00** | — | 290 Hz | en |
| 5 | That failure was within expectations. Adjusting. | 0.40 | **1.00** | — | 275 Hz | en |

**Reading it honestly:**
- PocketTTS (native-EN catalog voice): **perfect intelligibility**, auto-lang
  `en` everywhere → no accent drift (expected — not our JP reference yet).
- fish's low scores are the **JP accent the user loves** defeating EN-ASR
  (hyp for #2: *"Here we need not to sit for a saint."*). This is an ASR
  artifact, NOT proof fish is worse to human ears — the accent-transfer caveat
  in the research is symmetric: whichever voice is cloned from the JP reference
  will read as accented to Whisper.
- **The decisive number (our cloned voice vs fish) cannot exist until (b)
  unblocks** — that is the switch gate.

### Speed (same sentences, this box)

| engine | gen time / sentence | RTF (audio-sec per wall-sec) | first audio |
|---|---|---|---|
| fish (GPU, JP ref) | 2.5 – 8.4 s | **×0.5** (slower than realtime) | whole-sentence wait |
| PocketTTS fp32 (CPU) | 0.33 – 1.0 s | **×3.0** mean (2.46–3.25) | **79 ms** first stream chunk |
| PocketTTS int8 (CPU) | 0.30 – 0.6 s | **×4.4** mean (4.21–4.64) | **48 ms** first stream chunk |

PocketTTS is **~6–9× faster than fish here** and lands first audio in <100 ms
vs fish's multi-second sentence wait — this directly attacks the known
`TTS latency 13.4s/phrase` pain point (PROGRESS §6), while **freeing the RTX
4060 entirely** (fish holds ~2 GB VRAM; PocketTTS is CPU-only by design).

## (d) Streaming integration map → `brain/voice/tts.py`

`generate_audio_stream(state, text)` yields ~80 ms tensor chunks at **24 000 Hz**
— bit-identical to what `_chunk_events()` / `encode_binary_frame(2, …)` expect
today. Everything DOWNSTREAM of `synthesize(text) -> wav bytes` (PhraseCache
namespacing, amplitude/pitch, sentence cap, echo registry, one-time notices,
mid-speak recovery, reference proof line) is untouched.

| my seam (fish today) | PocketTTS equivalent | effort |
|---|---|---|
| `health()` | `GET /v1/health` on official `pocket-tts serve` (FastAPI) | same shape |
| `ensure_started()` / `stop()` | copy FishSpeechServer lifecycle (spawn/health/kill-pg; instance-derived port — **NOT 8777**, Rule 14 one-server rule + pre-spawn `pgrep` check) | ~1:1 port |
| `synthesize(text) -> wav` + `_references()` (fish payload `references:[{audio,text}]`) | `voice = <exported great-sage.safetensors>` (or WAV) + pocket payload; **community OpenAI-compat servers do NOT speak fish's `references[]`**, so the research's "zero-change drop-in" holds only at the *endpoint* level — realistically a **40–60 line adapter** replacing payload + URL | small |
| CPU/GPU | CPU-only (GPU optional/unofficial) | frees the 4060 |
| in-process option | `TTSModel` in brain: no server at all (no Rule-14 conflict) but **+1.2–1.4 GB RSS inside brain** — likely too much on this 8 GB box | reject for now |

## (e) Others (research §Summary, restated)

- **KittenTTS** — disqualified: 8 fixed voices, no reference-audio cloning (hard
  requirement = the Great Sage voice). Apache-2.0, ~300–600 MB (est.).
- **Voicebox (Meta)** — not installable: weights/code never released; public
  repos are untrained re-implementations.

## Recommendation: **HYBRID now → SWITCH after the clone gate + user's ear**

1. **Keep fish live** (unchanged): its voice is user-approved; we do not swap
   the user's voice without their ear — the same rule as the JP A/B.
2. **PocketTTS wins every measured dimension**: peak RSS 1.45 GB vs fish ~2 GB
   VRAM+RAM · RTF ×3.0/×4.4 vs ×0.5 · first audio 79 ms vs 2.5–8.4 s ·
   EN intelligibility 1.00 · native 24 kHz streaming · CPU-only (frees the
   4060) · MIT/CC-BY · actively maintained · **no memory balloon observed**.
3. **Gate (user action, one time):** accept
   https://huggingface.co/kyutai/pocket-tts terms → I rerun the clone →
   `great-sage.safetensors` + our-voice A/B renders → **user listens** →
   switch/no-switch decision.
4. Integration when green: official `pocket-tts serve` on an instance-derived
   port with the FishSpeechServer lifecycle + a small adapter (see (d)); the
   phrase cache/echo/notice/recovery machinery carries over unchanged.
5. If RAM proves tighter than measured in live duty: `--quantize` buys speed
   (×4.4) not RAM (measured); the ONNX/C++ runtimes (research §1.1) are the
   RAM lever — separate spike, not needed for the decision.

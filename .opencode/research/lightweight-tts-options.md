# Lightweight TTS Replacements for fish-speech-1.5 (Raphael)

**Context:** Raphael runs on a local Windows/WSL2 box with an 8GB RTX 4060 and **only 8GB system RAM total**. LLMs are cloud-only until a RAM upgrade, so the TTS must be local, small, and ideally CPU-friendly. fish-speech-1.5 currently eats ~2GB VRAM + local RAM. Current integration: `brain/voice/tts.py` POSTs `/v1/tts` to fish-speech's OpenAI-compatible server and streams 24kHz PCM chunks (sentence-streamed playback). We need **English speech + zero-shot voice cloning from a reference audio** (a specific Japanese-accented anime-girl "Great Sage" voice).

**Research date:** 2026-10-07. All facts verified against GitHub API, HuggingFace API, official docs/READMEs, and community reports.

---

## Summary

| Candidate | Verdict |
|---|---|
| **Pocket TTS (Kyutai)** | ✅ **WINNER.** 100M params, CPU-first, native streaming at 24kHz, **zero-shot voice cloning from a WAV reference**, actively maintained (last push: today). ~1.1GB RAM via PyTorch serve; ~0.5GB via ONNX/int8 routes. |
| **KittenTTS (KittenML)** | ⚠️ Smallest footprint (25–80MB, ONNX CPU) but **NO voice cloning — 8 fixed built-in voices only.** Disqualifies it for the Great Sage character voice. Fine as a fallback if cloning is ever dropped. |
| **Voicebox (Meta)** | ❌ **Not viable — Meta never released the weights or code** (research announcement only, June 2023). The only public "voicebox" repos are untrained re-implementations with no checkpoints. Nothing to install. |

---

## 1. Pocket TTS — Kyutai (kyutai-labs/pocket-tts) ⭐ RECOMMENDED

**What it is:** A 100M-parameter TTS by Kyutai (the Moshi team), purpose-built to run on CPUs. Released Jan 2026 (repo created 2026-01-07), tech report 2026-01-13, arXiv 2509.06926. Training code released Aug 2026.

### 1.1 Size & runtime memory (criterion #1)
- **Params:** 100M total (90M causal-transformer generative model + 10M codec decoder; plus an 18M codec *encoder* used once per cloned voice).
- **Disk weights:** ~200–400MB per language model (safetensors; the HF repo `kyutai/pocket-tts` hosts many language variants, gated).
- **Runtime RAM (measured, community):** **~1.1GB** after model load (user report on Reddit r/LocalLLaMA, Ryzen 5950X, PyTorch serve). The model + voice state stay resident between requests.
- **Reduction levers:**
  - `--quantize` (int8 dynamic quantization) → materially lower RAM, "minimal impact on audio quality" per docs.
  - **ONNX route:** community `pocket-tts-onnx` (single self-contained `.onnx`, no torch, first audio ~80ms on CPU) and **`PocketTTS.cpp`** (single-file C++ runtime, ONNX Runtime, with **built-in HTTP server + FFI C API**), plus **sherpa-onnx** official support (Windows/macOS/Linux/RPi, bindings for 12 languages incl. Python/C++). These cut the PyTorch runtime tax (~300–500MB) entirely → realistic **~400–600MB total process RAM**.
  - **Caveat:** an early Reddit report flagged that the original `serve` didn't clear memory between generations and ballooned to 32GB over a long session. Worth re-testing on current v3.2.x; the Python API has an internal LRU voice-state cache (default size 2) and recommends pre-computing/persisting voice states (`export_model_state` → safetensors). **On an 8GB box this must be validated before unattended use.**

### 1.2 CPU vs GPU
- **Designed for CPU.** Official numbers: ~6× real-time on a MacBook Air M4 CPU, **only 2 CPU cores**, ~200ms to first audio chunk.
- x86 CPU reference (cloud VM, 4 vCPUs): **RTF ~2.3–2.5×** real-time on CPU (Tesla T4 GPU: ~6.3×). An 8GB-RAM laptop/desktop x86 CPU should land at 2–5× real-time — comfortably fast enough for sentence streaming.
- GPU is optional and *not officially supported* in `serve` (CPU-only); `generate --device cuda` exists, and `TTSModel.to("cuda")` works unofficially. **CPU-only is the intended mode — perfect for us** (frees the 4060 entirely).

### 1.3 Quality, cloning, languages (criterion #3)
- **Quality (tech report, blind ELO):** WER 1.84 (best-tie), Audio Quality ELO 2016 (beats ground-truth F5-TTS 1949), Speaker Similarity ELO 1898 (on par with ground truth; slightly below Chatterbox 2012). For a 100M model this is at/near large-model quality — **very likely ≥ fish-speech-1.5 in naturalness**, certainly better than any other sub-1GB option found.
- **Voice cloning: YES — zero-shot from reference audio.** `--voice` accepts a plain local WAV, an HTTP URL, or an HF path. A 18M-parameter codec encoder embeds the voice once; the embedding (a KV-cache "voice state") can be **exported to a `.safetensors` file and loaded instantly thereafter** — exactly what we want for a permanent "Great Sage" voice preset. Kyutai recommends cleaning the sample first (e.g. Adobe Enhance) because sample quality is reproduced.
- **Caveat for our use case:** cloning transfers *timbre/style*; cross-lingual accent transfer (Japanese-accented EN reference → English text) is partial — English phonetics with cloned timbre. The model was trained on audiobook-style speech; a stylized anime voice may degrade more than a natural one. **This needs a 10-minute local A/B test with the actual Great Sage clips before committing.**
- **Languages:** English (default, `english` = `english_2026-04`/`2026-09` latest), French, German, Portuguese, Italian, Spanish, Dutch. Community fine-tunes exist for Czech, Hindi, Korean, Farsi, Persian, Indonesian, Estonian, Welsh, Polish, Greek, Russian, Turkish, Telugu — and **training code is released** if we ever needed a custom Japanese-accented English variant.
- **Consent policy:** model is gated on HF with a use policy prohibiting "voice impersonation or cloning without explicit and lawful consent." Cloning a fictional character voice from clips we hold for personal use is within bounds; if we ever *publish* Raphael output with that voice, re-check the policy.

### 1.4 License & maintenance
- **Code:** MIT. **Model weights:** CC-BY-4.0 (+ gated-use prompt). Both fine for personal and commercial use with attribution.
- **Maintenance:** extremely active — GitHub `pushed_at: 2026-10-07` (same day), PyPI v3.2.0, HF model last modified 2026-10-01, 9.8k stars, 1k forks. No abandonment risk.

### 1.5 Integration difficulty
- **Python API:** `TTSModel.load_model()` → `get_state_for_audio_prompt("great-sage.wav" | "state.safetensors")` → `generate_audio(voice_state, text)` returns a 1D PCM tensor at `model.sample_rate`. **24kHz — bit-identical to what `brain/voice/tts.py` expects today.**
- **Native chunk streaming:** the library exposes a streaming generator yielding ~80ms chunks at 24kHz (one latent frame ≈ 1920 samples) — a direct drop-in match for fish-speech's chunked PCM streaming.
- **Ready HTTP servers (multiple):**
  - Official `pocket-tts serve` → FastAPI server on `localhost:8000` (web UI + HTTP API; CPU-only; model kept resident; supports `--language`, `--default-voice` (can be a URL/HF path), `--quantize`).
  - **Community OpenAI-compatible streaming servers:** `pocket-tts-openai_streaming_server` (dockerized, **.exe release for Windows**), `pocket-tts-server` (OpenAI-compatible API + voice cloning, "clone with 20s of audio"), `openclaw-pockettts` (Docker exposing OpenAI TTS API). An OpenAI-compatible `/v1/tts` endpoint means **`brain/voice/tts.py` may need zero changes** beyond pointing at the new URL — this is the cheapest integration path of anything researched.
  - `pocket-tts-wyoming` (Home Assistant Wyoming protocol), ComfyUI node, Unity, macOS/Windows/iOS apps, Rust/C#/Deno ports.
- **Effort estimate:** swap the URL + verify chunk format = **hours, not days**. Fallback: ~50-line FastAPI wrapper around the Python API if we want exact PCM-chunk semantics ourselves.

### 1.6 Speed
- 2.3–2.5× real-time on a modest x86 CPU (official); ~200ms first-chunk latency; streaming throughout. Even at the pessimistic end, sentence-level playback keeps up easily.

---

## 2. KittenTTS — KittenML (KittenML/KittenTTS)

**What it is:** ONNX-based ultra-lightweight TTS (v0.8 family), Aug 2025 origin, 15.5k stars.

### 2.1 Size & runtime memory
- **Params/disk:** `kitten-tts-mini` 80M/80MB · `micro` 40M/41MB · `nano` 15M/56MB fp32 or **25MB int8**. HF storage ~81MB for the mini repo. By far the smallest of all candidates.
- **Runtime RAM:** not officially published. Python deps install to ~670MB on disk (onnxruntime, spacy, espeakng-loader, num2words); weights ≤80MB. **Estimated resident RAM ~300–600MB** (estimate, not measured — validate locally). Note the Python wheel drags spacy/espeak; the Rust `ort` port measured ~224MB total binary.

### 2.2 CPU vs GPU
- **CPU-only by design** — no CUDA required; ONNX Runtime. GPU optional via `requirements_gpu.txt`/`backend="cuda"` but community measured **no meaningful speedup on a 3080**. ~1.5× real-time on an Intel i7-9700 with the 80M model (official community report). Fine on any CPU.

### 2.3 Quality, cloning, languages
- **Quality:** good-for-size; HN consensus: prosody improved a lot in v0.8 ("best among <25MB models"); developer acknowledges **Kokoro still beats it**. Below pocket-tts/fish-speech tier, and voices are described as "not bad but not loved." 24kHz output.
- **Voice cloning: ❌ NO.** **8 fixed built-in voices** (Bella, Jasper, Luna, Bruno, Rosie, Hugo, Kiki, Leo) via precomputed `voices.npz` style embeddings. There is **no reference-audio API** — you cannot condition on a Great Sage clip. This is the deal-breaker for Raphael.
- **Languages:** English only (multilingual was "coming soon" on the roadmap; v0.8 docs still English-only).

### 2.4 License & maintenance
- **Apache-2.0** for both code and model weights (verified via HF API `license:apache-2.0` and GitHub API) — fully permissive, commercial OK.
- **Maintenance:** active — GitHub `pushed_at: 2026-10-06`, HF mini-0.8 modified 2026-02-19, v0.8.1 release, mobile SDK + custom inference engine on roadmap.

### 2.5 Integration
- Simple Python API (`KittenTTS(model_id)` → `.generate(text)` → numpy PCM 24kHz). **No official HTTP server** — community Spaces exist (`UnchartedDuty/kittentts-server`), but we'd write a trivial FastAPI wrapper (~30 lines). No native streaming API (batch per text; fine for short sentences, add chunking ourselves). Easy.

### 2.6 Speed
- ~1.5× real-time CPU (80M, i7-9700); nano faster. Real-time OK for short assistant sentences.

---

## 3. Voicebox — Meta

**Finding: ELIMINATED AT STEP 1.** Meta announced Voicebox (June 2023) as research-only and **deliberately did NOT release model weights or code** due to misuse risk (deepfake cloning). No official checkpoint exists on HuggingFace or anywhere else. What exists publicly:
- `lucidrains/voicebox-pytorch` — an MIT-licensed *untrained architecture re-implementation* (no pretrained weights; last push Oct 2024, stale). Not a TTS you can run.
- The paper (330M-param flow-matching model + duration model) and a dead demo site. 6 languages (EN/FR/DE/ES/PL/PT) — no Japanese-adjacent accent story anyway.
- **Possibly the user meant "MetaVoice-1B"** (metavoiceio, Apache-2.0, 1.2B params, zero-shot cloning) — but at ~2GB+ VRAM it is **no lighter than fish-speech** and effectively unmaintained since early 2024 (4.2k stars, dead repo). Also not a candidate.
- There is no cloud "Voicebox API" either — pricing N/A.

**Conclusion: skip Voicebox entirely.**

---

## Other sub-500MB local TTS worth a glance (one line each)

- **Kokoro-82M** — Apache-2.0, 82M params, ~300MB CPU runtime, excellent quality (best-in-class ≤100M), but **fixed 54 voices, NO cloning**; the standard pick if cloning weren't required.
- **Sesame CSM (CSM-1B)** — Apache-2.0, zero-shot cloning, but ~1B params → ~2GB VRAM; **not lighter than fish-speech**.
- **F5-TTS** — 336M params, Apache-2.0, zero-shot cloning, strong quality; runtime ~1.5–2GB VRAM, no native streaming; heavier than pocket-tts on every axis we care about.
- **Parler-TTS** — voice chosen by *text description* ("a calm female voice…"), not reference-audio cloning; DiT-scale models (~1GB-class), heavy; doesn't meet the cloning requirement.
- **StyleTTS2** — ~140M, MIT, superb English quality, but **no zero-shot cloning** (needs per-speaker fine-tuning — a GPU training project, out of scope for a RAM-mandated lighter replacement).
- **XTTS-v2** — cloning yes, but 1.8GB weights and Coqui is defunct; rejected.
- **Moshi/CSM/moshi-TTS** — Moshi is a full speech-LLM (1–7B), far too heavy; not a drop-in TTS.
- **sherpa-onnx** — not a model but the best *runtime* for pocket-tts on Windows if we want to avoid Python/torch on the brain side.

---

## Recommendation Table

Ranked by (1) RAM footprint, (2) voice-cloning-from-reference, (3) quality.

| Rank | Engine | Params / Disk | Runtime RAM | CPU-only OK? | Voice cloning from reference | Quality vs fish-speech-1.5 | License | Maintained | Integration | Speed (RTF) |
|---|---|---|---|---|---|---|---|---|---|---|
| **1** | **Pocket TTS** | 100M / ~200–400MB | **~1.1GB** PyTorch serve (measured); **~0.5–0.6GB** via int8/ONNX/C++ (est.) | ✅ designed for it | ✅ **YES** — zero-shot from WAV; export embedding to safetensors | **≥ fish-speech** (blind ELO ≥ F5-TTS GT; WER best-tie) | Code MIT / weights CC-BY-4.0 (+consent policy) | ✅ pushed 2026-10-07 | ✅ official FastAPI `serve` + **community OpenAI-compatible streaming servers (.exe/Docker)**; 24kHz PCM chunks match `brain/voice/tts.py` | 2.3–2.5× CPU (x86); 200ms first chunk |
| **2** | **KittenTTS** | 15–80M / **25–80MB** | **~300–600MB** (est.; deps ~670MB on disk) | ✅ ONNX, no GPU ever | ❌ **NO** — 8 fixed built-in voices | Below (good-for-size; < Kokoro) | Apache-2.0 | ✅ pushed 2026-10-06 | ⚠️ Python API, no official server (write ~30-line wrapper); no native streaming | ~1.5× CPU |
| — | Voicebox (Meta) | 330M (paper) | n/a | n/a | (paper says yes) | n/a | **Weights never released** | ❌ dead demo, untrained reimpl only | **Not installable** | n/a |

**If RAM is the ONLY criterion:** KittenTTS wins on paper — but it **cannot do the Great Sage voice at all**, which is a hard requirement. Ranking by the full criteria, **Pocket TTS is the only candidate that satisfies every requirement**, and it offers legitimate levers (int8 quantize, ONNX/C++ runtime) to approach KittenTTS-level footprints if 1.1GB proves too much on the 8GB box.

## Final recommendation

1. **Adopt Pocket TTS (Kyutai)** as the fish-speech replacement. Start with the official `pocket-tts serve --quantize` or the community **OpenAI-compatible streaming server** so `brain/voice/tts.py` keeps its current POST-`/v1/tts`-stream-PCM shape. Precompute the Great Sage voice once via `export-voice` → `.safetensors`, keep the state resident.
2. **Validate three things on the actual box before deleting fish-speech:** (a) resident RAM stays flat over a long session on v3.2.x (early serve leaked to 32GB — retest); (b) Japanese-accented anime reference clones acceptably (accent transfer is partial by design); (c) CPU real-time factor ≥2× on the laptop CPU.
3. **Keep Kokoro-82M as the no-cloning fallback** and **KittenTTS as the ultra-low-RAM fallback** if the character voice ever gets dropped. Ignore Voicebox — nothing exists to install.

## Sources
- [kyutai-labs/pocket-tts (GitHub)](https://github.com/kyutai-labs/pocket-tts) — README, serve/CLI, GPU notes, community projects (verified via GitHub API: MIT, pushed 2026-10-07)
- [kyutai/pocket-tts (HuggingFace)](https://huggingface.co/kyutai/pocket-tts) — CC-BY-4.0, gated use policy, language variants (verified via HF API)
- [Pocket TTS technical report](https://kyutai.org/pocket-tts-technical-report/) — 100M params, quality/clone ELO table, CPU RTF
- [Pocket TTS docs — serve / Python API](https://kyutai-labs.github.io/pocket-tts/) — 24kHz sample rate, streaming chunks, `export-voice`, quantize
- [Reddit r/LocalLLaMA — Pocket TTS RAM report](https://www.reddit.com/r/LocalLLaMA/comments/1qbpz5l/) — ~1.1GB model-load RAM; serve memory-balloon caveat
- [pocket-tts-onnx (community)](https://github.com/thewh1teagle/pocket-tts-onnx) / [PocketTTS.cpp](https://github.com/VolgaGerm/PocketTTS.cpp) / [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) — torch-free Windows-friendly runtimes with HTTP servers
- [pocket-tts-openai_streaming_server](https://github.com/teddybear082/pocket-tts-openai_streaming_server) — OpenAI-compatible streaming, Windows .exe
- [KittenML/KittenTTS (GitHub)](https://github.com/KittenML/KittenTTS) — Apache-2.0, v0.8 model table, pushed 2026-10-06 (verified via GitHub API)
- [KittenML/kitten-tts-mini-0.8 (HuggingFace)](https://huggingface.co/KittenML/kitten-tts-mini-0.8) — license apache-2.0, 80MB (verified via HF API)
- [HN: Three new Kitten TTS models](https://news.ycombinator.com/item?id=47441546) — CPU RTF measurements, dep sizes, quality consensus vs Kokoro
- [Meta Voicebox announcement](https://ai.meta.com/blog/voicebox-generative-ai-model-speech/) — weights/code withheld
- [lucidrains/voicebox-pytorch](https://github.com/lucidrains/voicebox-pytorch) — untrained reimplementation, last push 2024-10

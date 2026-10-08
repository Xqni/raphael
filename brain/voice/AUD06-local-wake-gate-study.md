# AUD-06 study — cheapest PRE-STT local wake gate (voice lane, Wave 5H)

Prepared for the human's **consent-vs-PTT** decision (attention posted by the
conductor). All numbers measured on THIS laptop (7.8 GB RAM, RTX 4060),
2026-10-07/08. Artifacts: `~/.raphael/voice/kws/`
(`fixtures/` = synthesized wake + 3 non-wake clips, `oww_measured.json`,
`sherpa_measured.json`, isolated venvs, model tarballs).

## 1. Confirmed finding (the gap this closes)

- `body/win/audio_in.py:302` — `"encoding": "pcm_s16le", "reason": "wake"}`:
  **every** VAD segment is marked `wake`.
- `brain/ws.py:776` — `asyncio.to_thread(voice.transcribe_result, buf, reason=reason),`
  happens **before** `brain/ws.py:807` — `match = voice.wake.gate(res.text, reason=reason)`.
- ⇒ with `always_listen: true`, background conversations ARE uploaded to cloud
  STT before any wake-word check. (SEC-3's fail-closed fix only covers
  *undecided/unknown* reasons — a valid `wake` verdict still uploads; hence
  this study.)

## 2. Candidates — measured

### A. openWakeWord — ❌ REJECTED (cannot hear "Raphael")
- Install: `~/.raphael/voice/kws/.venv-oww`, **278 MB** on disk.
- RSS: process baseline 141 MB → import+5 pretrained models loaded
  **228 MB** → inference peak **240 MB** (**≈ +100 MB** for the stack).
- Load: **0.27 s**; inference **43–67 ms per 2.4–3.7 s clip** (≈ 50× realtime).
- Pretrained models (`Model().models` keys): **`{'alexa', 'hey_mycroft',
  'hey_jarvis', 'timer', 'weather'}`** — no "raphael"; `predict()` on our wake
  fixture returned **zero scores > 0.01** (empirically deaf to our word).
- Custom-keyword capability (grepped installed source): only
  `custom_verifier_model.py` (false-positive verifier for EXISTING models);
  no `keyphrase`/`audio_prompt` path — custom words need their training
  pipeline + recordings of the user, which we do not have (and would be new
  personal data).
- Verdict: cheapest *code*, wrong *ear* — rejected for our wake word.

### B. sherpa-onnx KWS (zipformer-gigaspeech-3.3M, English) — ⚠️ COSTS GREAT, DETECTION UNPROVEN (BLOCKED)
- Install: **43 MB** venv (sherpa-onnx 1.13.8 core) → **51 MB** with the
  CLI's helpers (`click`, `sentencepiece`, `pypinyin`) + numpy.
- RSS: baseline 43 MB → loaded **83 MB** (model load **0.53–0.63 s**) →
  final **92 MB** (**≈ +40–49 MB**, CPU-only, `num_threads=1`).
- Decode speed: **33–62 ms per 2.4–3.7 s clip ≈ 60× realtime**.
- Model: 17.6 MB tarball (encoder/decoder/joiner int8+fp32, tokens, bpe).
- **Custom keyword WORKS at the tokenization level**: official recipe
  (`sherpa-onnx-cli text2token --tokens-type bpe --bpe-model bpe.model`) on
  `RAPHAEL` produced `keywords.txt` = `▁RA P HA EL` (CLI deps: click +
  sentencepiece + pypinyin).
- **BLOCKER — end-to-end detection not achieved**, even on the model's OWN
  shipped `keywords.txt` + shipped `test_wavs/0.wav`: four usage variants
  tried, all returned no hits:
  1. encoder/decoder chunk mismatch (fixed to chunk-16 trio) — still empty;
  2. canonical loop from `sherpa_onnx/keyword_spotter.py` (0.66 s tail
     padding + `input_finished()` + `get_result()` inside the decode loop) —
     still empty;
  3. raw-vs-tokenized keyword file (raw = fatal `Cannot find ID for token`
     at init — tokenized form IS required and loads cleanly);
  4. **verbatim upstream example flow** (fp32 trio, native sample rate) on
     the official sample — **HITS: []**.
  ⇒ consistent with a sherpa-onnx==1.13.8 wheel/model behavior issue rather
  than usage; adoption is BLOCKED until an integration spike finds a working
  combo (next tries: upstream CLI binary `sherpa-onnx-cli keyword-spotter`,
  pin another sherpa-onnx version, wenetspeech-model sanity, or the
  `keywords_score`/threshold pair from their CI). One spike session, not
  more blind iteration.

### C. PTT-only mode (no model at all) — ✅ ALREADY-DONE, zero cost
Quotes:
- `config.yaml:76` `ptt_hotkey: "ctrl+alt+space"             # used only when always_listen: false`
- `config.yaml:77` `always_listen: true                      # wake-word streaming ("Raphael, ..."); false = push-to-talk`
- `body/win/ws_client.py:239` `always = bool((cfg.get('voice', {}) or {}).get('always_listen', True))`
  → `:245` `wake = audio_in.WakeStream(...)` when true, `:257` `elif ptt_hk:` otherwise
  ⇒ **with `always_listen: false` the Body never opens the always-on stream:
  no VAD segment exists → nothing can reach cloud STT** (strongest posture).
- Backstop: `brain/voice/activation.py:159` `if not self.cfg.always_listen:` →
  wake-reason segments dropped pre-STT (`ptt_only`), and SEC-3's fail-closed
  gate covers undecided states.
- Toggle = one config flip or env var (`brain/voice/config.py:346`
  `cfg.always_listen = _env("RAPHAEL_ALWAYS_LISTEN", …)`) — no code change.
- Note (not my file): `ws_client.py:239` defaults to `True` when the key is
  missing — the fail-open default lives there (pc-control's file).

## 3. Recommendation (decision belongs to the human)

| option | cost (measured) | blocks cloud upload before wake check? | status |
|---|---|---|---|
| **PTT-only** (`always_listen: false`) | **0 MB / 0 ms** | **YES — no stream at all** | ready today |
| sherpa-onnx local gate | +40–49 MB RSS, 0.55 s load, ~50 ms/segment CPU | yes (would) | **BLOCKED** (detection unproven — spike needed) |
| openWakeWord | +100 MB RSS, 43–67 ms/clip | no (wrong word) | rejected |

1. **If consent/privacy wins → flip PTT-only now** (config + restart; hotkey
   `ctrl+alt+space`). Nothing leaves the machine until the key is held.
2. **If always-listen must stay → keep the current cloud path + echo guard
   until the sherpa-onnx spike unblocks** (then a pre-STT local gate drops
   non-wake segments before any provider call); openWakeWord stays rejected.
3. Either way, SEC-3's fail-closed gate (undecided ⇒ discard) remains the
   last line before any provider call.

Fixtures for any future tripwire: `~/.raphael/voice/kws/fixtures/wake.wav`
("Raphael, open YouTube…") + `nonwake1..3.wav` (canonical lines).

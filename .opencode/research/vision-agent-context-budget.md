# Vision subagent context budget — root cause & verified fix

Discovered & fixed 2026-10-05 while analyzing 6 orb reference images (Raphael build).

## Root cause (measured, exact)
`vision` agent = `ollama/huihui_ai/qwen3-vl-abliterated:4b-instruct`.

Token accounting per call (from 4 observed `exceed_context_size_error` payloads):

| Invocation | images | n_prompt_tokens |
|---|---|---|
| A (full-size) | 3 | 19,343 |
| B (560px downscaled) | 3 | 19,326 |
| C | 2 | 18,231 |
| D | 1 | 17,088 |

- **Fixed overhead ≈ 16,000 tokens** — AGENTS.md instruction file + opencode tool schemas + agent prompt. This is the dominant term.
- **Image ≈ 1,100 tokens each** (Ollama's Qwen-VL preprocessing resizes to a fixed grid → **downscaling does NOT reduce tokens**: 736→560px changed the count by 17 tokens).
- With server ctx **16384, even ONE image could never fit** (17,088 > 16,384) → the vision agent was structurally broken, not misused.

## The fix (applied & verified)
`/etc/systemd/system/ollama.service.d/override.conf` held the real knob:
```
Environment="OLLAMA_CONTEXT_LENGTH=16384"   →   32768
sudo systemctl daemon-reload && sudo systemctl restart ollama
```
Verified after restart: fresh `llama-server` spawns with `-c 32768`.
`~/opencode.json` `"context": 32768` entries are UI metadata only — they never reach Ollama.

## Budget table at ctx 32768
- overhead 16k + 1 image ≈ 17.1k ✓ | 2 imgs ≈ 18.2k ✓ | 3 imgs ≈ 19.3k ✓ | 6 imgs ≈ 22.6k ✓
- Practical recipe: **2-3 images per vision invocation** (comfortable margin), all 6 in a single agent also fits.
- To downsize later (user: "increase for a while"): same sed reversed + restart.

## Known failure mode: generic-fluff reply
The very first attempt (6 full-size images) returned "I am ready to assist you" with zero
analysis instead of an error — silent overflow on the batch made the model flail.
**Symptom → diagnosis:** vision prose with no image observations = token overflow, not model willingness.
Strict prompts ("MANDATORY: call Read on each path, numbered sections, no greetings") reduce
fluff-mode but do NOT fix overflow.

## Unrelated but useful
- Ollama here = WSL systemd service (`/etc/systemd/system/ollama.service` + drop-in override),
  runs as user `ollama`; my shell's `OLLAMA_CONTEXT_LENGTH=8192` never reaches it.
- KV already `q4_0` + flash-attn → 32k ctx costs little VRAM (~1 GB worst case on the 8 GB 4060).

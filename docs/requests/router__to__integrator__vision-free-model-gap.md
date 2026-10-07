# router → integrator: vision-free-model-gap
Status: OPEN

## What
`vision()` (INTERFACES §a, Wave-2 exit criterion 3: *"What am I looking at" returns a real vision answer*) cannot pick a model under today's free chain — live discovery run 2026-10-06 from this worktree:

- **Groq** `GET https://api.groq.com/openai/v1/models` → 200, 11 models:
  `canopylabs/orpheus-v1-english`, `openai/gpt-oss-120b`, `meta-llama/llama-prompt-guard-2-22m`, `allam-2-7b`, `openai/gpt-oss-20b`, `qwen/qwen3.8-27b`, `whisper-large-v3-turbo`, `canopylabs/orpheus-arabic-saudi`, `meta-llama/llama-prompt-guard-2-86m`, `whisper-large-v3`, `openai/gpt-oss-safeguard-20b`
  → **no vision-capable model** (the old llama-4-scout/maverick and llama-3.2-vision ids are gone from the account's list). Whisper (STT) and chat slots are fine.
- **Zen free** `GET https://opencode.ai/zen/v1/models` → 200, 88 models, **no capability or `free` metadata** (`data[] = {id, object, created, owned_by}` only). 14 ids carry `-free`; none of them is a vision model by name. Zen's only `-vision-` id (`deepseek-v4-flash-vision-exp`) has no `-free` suffix → by the money gate it is treated as **paid** and is never selected (`allow_paid_runtime: false`).

Router behaviour today (correct, but it means exit criterion 3 cannot pass): `vision()` raises `RouterError(code="E_OFFLINE", reason="no_model", detail="No model available for this request.")` — no image is ever sent to a model that never claimed the capability (roles.py rule 4).

## Why
Wave 2 exit criterion 3 (docs/WAVES.md) needs a real cloud vision answer under profile `cloud_temp`; computer-use's "see my screen" path calls `router.vision()`.

## Proposed change (integrator decides — options)
1. **Confirm/enable a free vision endpoint** on Zen or Groq (e.g. verify whether `deepseek-v4-flash-vision-exp` is billable, or add a known-free vision id to `router.zen_free_hints` in `config.d/router.yaml`) and tell me the id to hint on — I never hardcode ids, I only need the capability word.
2. **Approve one specific vision-capable paid/preview model** for the vision slot only, and flip `providers.allow_paid_runtime` (or a narrower vision-only gate) with a spend cap — needs your sign-off per AGENT_RULES §7.
3. If neither exists today, **defer criterion 3 to the Wave 6 local cutover** (local vision) and note it as a known gap in WAVES.md.

Also blocked-on-you (small): the router needs a refusal code for "cloud is off by a gate" that is distinguishable from "network is down". Today both are `E_OFFLINE` with `reason` (`private_mode` / `blocked_window` / `cloud_vision_disabled` / `chain_exhausted`). If you want a dedicated PROTOCOL §10 code (e.g. `E_BLOCKED`), I'll adopt it in one commit — request only if you agree; otherwise `reason` stays the discriminator.

## Impact
No code outside `brain/router/**` changes for option 1/2 (config + a hint line). Option 3 is a docs-only WAVES.md note. Consumers (brain-core `llm.py`, computer-use) already handle `E_OFFLINE` as a job error, so nothing crashes in the meantime.

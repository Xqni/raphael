# Laya decision engine — research + benchmark record (2026-10-05)

## What it is
github.com/NandhaKishorM/laya — Apache-2.0, 30.8k★, open local replacement for Jev
(TypeSafe's $40M closed "System One"). Non-autoregressive **typed-decision** engine:
state + questions (`choice` / `score` / `noul`) → answers in ONE forward pass, no text
generation (nothing to parse/hallucinate). Calibrated confidence + abstention gate
(`min_confidence` → low_confidence / decide()→None). Checkpoints: English 421M
(ModernBERT-large), multilingual 322M (mmBERT, 100+ langs, "2x faster"), typed-decisions
421M. Jev-compatible wire (`/v1/systemone`) = future swap possible. Fine-tune notebook
(base 0.36 → 0.77 accuracy on typed-decisions bench).

## Benchmark — this machine (Raphael repo, 2026-10-05)
Environment: `brain/.venv` CPython 3.12.8, laya 0.3.27, torch **2.14.0+cu126**
(driver 12.7 — cu130 wheel FAILS cuda init: "driver too old (12070)"), RTX 4060 Laptop
8GB, WSL2. 4-question schema (intent/task_kind/urgency/needs_confirm), 6 utterances.

| Path | Result |
|---|---|
| GPU singles (cuda sync timers) | **mean 44.7ms**, p50 44.5, min 42.1, max 48.1 |
| GPU batch (correct dict API) | 135.2/125.9 ms for 6 → **21–22.5 ms/utt** |
| CPU fp32 eager singles | mean 934–938ms |
| CPU dict-batch | 4889ms/6 = **815 ms/utt** (batching does NOT rescue CPU) |
| VRAM | torch alloc 1694MB, max alloc 2508MB; smi total ~3.3–3.5/8.2GB (w/ Ollama) |
| Host RSS | peak 3621MB |
| Startup | Router lazy; first GPU predict 10.48s (VRAM load) → preload at Brain boot |

Accuracy (zero-shot English checkpoint — identical on GPU/CPU):
- "delete my downloads folder" → needs_confirm **0.09** ← safety miss
- "research …cool a 4060" → intent **out_of_scope** ← wrong (core duty)
- "remind me in 20 minutes" → intent **out_of_scope** ← wrong (fast-path duty)
- "open youtube" → task_kind **none** (cosmetic miss)
- Checkpoint warning: *"ships invalid temperatures … treat confidence as uncalibrated"*
→ matches upstream 0.36 zero-shot number; **fine-tune + recalibrate before gate trust.**

## API gotchas (verified)
- `predict_batch(requests)` = ONE list of `{"state": str, "questions": {...}}` dicts —
  NOT `(states, questions)` (else TypeError "request N must be a dict, got str").
- GPU timing requires `torch.cuda.synchronize()` around timers or numbers lie.
- Warmup prints triton `_POSIX_C_SOURCE` warnings — harmless.
- `laya[onnx]` extra installs onnxruntime; ONNXAgent requires `scripts/export_onnx.py`
  from the GitHub repo (not shipped in wheel) — sparse clone:
  `git clone --depth 1 --filter=blob:none --sparse … && git sparse-checkout set scripts`.

## INT8/ONNX verdict (from upstream export_onnx.py docstring — binding)
INT8 ≈ 2x faster than eager on CPU but **"do not use it where the calibrated probability
or confidence matters"** (English 31/96 vs 64/96 agreement per-channel; multilingual 40%
vs 83%). fp32 ONNX ≈ only ~1.1x eager. → **INT8 banned for Raphael's confirm/gate use.**

## Decision (addendum §12)
Adopt as the fast-path MIDDLE tier (fastpath.py rules → Laya → LLM System 2), GPU device,
phased: Phase 1 advisory (orb task_kind/shape_hint, urgency, pre-check hints) →
Phase 2 authoritative gates ONLY after fine-tune on Raphael labels + calibration.
CPU device = fallback only. torch pinned +cu126 until a driver update.

## Install/bench commands
```
uv venv brain/.venv --python 3.12
uv pip install --python brain/.venv/bin/python laya
uv pip install --python brain/.venv/bin/python "torch==2.14.0" --torch-backend cu126
brain/.venv/bin/python /tmp/opencode/bench_laya.py    # round1 CPU
brain/.venv/bin/python /tmp/opencode/bench_laya2.py   # round2 GPU+CPU+batch
```

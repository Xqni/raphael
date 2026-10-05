---
name: laya
description: Laya System 1 decision engine in brain/.venv — typed decisions (choice/score/noul) for Raphael's fast path. Use when wiring intent/task_kind/urgency/confirm decisions, benchmarking Laya, fixing its batch API/device, or when a task involves fast classification instead of LLM generation.
---

# Laya — Raphael's System 1 decision tier

## What/where
- Package: `laya` 0.3.27 in `brain/.venv` (CPython 3.12.8, torch **2.14.0+cu126**).
- Role: fast-path MIDDLE tier — `fastpath.py` rules → **Laya** → LLM System 2.
- Docs: addendum §12, ARCHITECTURE fast-path section, `.opencode/research/laya-decision-engine.md`.

## Measured performance (this machine, 2026-10-05)
- **GPU (4060): 44.7ms singles / 21ms batched** ← production path; VRAM ~1.7–2.5GB
- CPU: ~935ms — fallback only. INT8 ONNX **banned** for confidence-bearing decisions.
- Warmup (VRAM load) 10.5s once → preload at Brain boot.

## Usage
```python
import laya
router = laya.Router(device="cuda")            # cpu fallback = config flag
result = router.predict(state_str, questions)  # questions = {id: {type: choice|score|noul, ...}}
# batch: router.predict_batch([{"state": s, "questions": q}, ...])  ← dicts, one list arg
```
- GPU timing: `torch.cuda.synchronize()` before/after `time.time()`.
- Abstention: `min_confidence=` → `low_confidence` flag / `decide()` returns None (fail-closed).

## Rules
1. **Phase 1 = ADVISORY** (orb shape_hint, urgency, hints). Zero-shot misfires are real
   (delete→confirm 0.09, research→out_of_scope). Never gate safety on it yet.
2. Phase 2 (gates, voice-confirm) requires fine-tune on Raphael labels + recalibration
   (checkpoint ships invalid temperatures → confidence uncalibrated).
3. torch MUST stay `+cu126` (driver 12.7); cu130 = cuda init failure. To check:
   `brain/.venv/bin/python -c "import torch; print(torch.__version__, torch.cuda.is_available())"`
4. Export tooling: `scripts/export_onnx.py` only in GitHub repo (sparse clone), not wheel.

## Re-benchmark
`brain/.venv/bin/python /tmp/opencode/bench_laya2.py` (round-2 script; recreate from
research file if tmp was cleaned).

# Laya bring-up test — 2026-10-09 (user: "bring her up to test her out")

Engine: laya 0.3.27 + torch 2.14.0+cu126, device=cuda (RTX 4060 8GB). Process exited
after the test (VRAM released). No production wiring touched — advisory bring-up only.

## API schema discovered (was undocumented in our notes — now the reference)
- `router.predict(state: str, questions: dict)`; `predict_batch([{state, questions}, ...])`.
- Each question needs **`instructions`** (natural-language text the model answers) AND
  **`criteria`**:
  - choice: `criteria = {label: short-description, ...}`
  - score: `criteria = ["level0", "level1", ...]` (index 0 = first/lowest level)
- Missing either → ValueError from `_check_question` (verified twice, fail-loud).

## Measured (matches the 2026-10-05 benchmark)
- load+warmup: 5.1s (lazy; the10.5s first-predict in bench — preload at boot when wired)
- singles: mean **47.6ms** (41–68) · batch(6): **15.7ms/utt** · VRAM alloc 1694MB / max2475MB

## Zero-shot predictions (4-question schema: intent/task_kind/urgency/needs_confirm)
| utterance | intent | task_kind | needs_confirm | verdict |
|---|---|---|---|---|
| open youtube and search lofi | command | web | no | CORRECT |
| delete my downloads folder | command | files | **yes** | CORRECT (safety axis works with instruction phrasing — the old bench's 0.09 miss was WITH the bare schema) |
| what time is it | out_of_scope | none | yes | WRONG (intent) |
| remind me in 20 minutes | conversation | none | no | WRONG (old bench: out_of_scope) |
| what am I looking at | conversation | web | yes | WRONG (kind), confirm defensible |
| write me a poem about storms | out_of_scope | none | no | WRONG (should be llm) |

- urgency score axis returns raw unnormalized values (1.2–2.1) — consistent with the
  checkpoint's "invalid temperatures / uncalibrated confidence" warning.

## Verdict
Engine works, speed confirmed, zero-shot intent quality is the known ~0.36 class.
**Confirms the standing decision: Phase 1 = ADVISORY ONLY** (cosmetic hints), and
**fine-tune on Raphael labels + recalibration before any gating trust**. Notable new
fact: needs_confirm DOES work zero-shot with explicit instruction phrasing — the
confirm axis may become useful sooner than the intent axis.

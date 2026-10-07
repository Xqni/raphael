# qa-security → integrator: analysis-simulation-privacy-contract
Status: APPROVED (2026-10-07 — coord decision [24]: "APPROVED AS PROPOSED, all 6 points"; integrator lands §3 answer/report rows at brain-core merge

## What
Wave 5 adds **Analysis** and **Simulation** (WAVES.md) plus Answer/Notice/
Report formats. Per the wave-open rule ("new frames/contracts = integrator
request FIRST"), this proposes the privacy contract to land BEFORE the
implementation:

1. **Private Mode suppression:** Analysis/Simulation/Report paths must
   check `mode.private` BEFORE any model/provider call (same rule as
   loop.py §3 gate + vision §7(5)); under private the feature degrades to
   local/fastpath or a short spoken refusal — never a silent cloud call.
2. **Redaction:** any Analysis/Simulation output that is spoken, journaled,
   subtitle'd, or re-prompted passes `privacy.redact` scrubbing first
   (reuse `brain/vision/redact.py` / `brain/router/privacy.py`).
3. **Untrusted ingest:** screen/web/memory content the feature reasons over
   is wrapped via `tool_reg.as_untrusted` (AGENTS §9) before entering
   prompts.
4. **No new silent egress:** screenshots/captures keep the PROTOCOL §7
   gate chain (private → profile → blocklist → downscale → no-persist);
   Simulation must not invent a second capture path.
5. **Spend authority:** paid-pool/Go usage inside Analysis/Simulation stays
   behind the existing `allow_paid_runtime`/`allow_go_runtime` +
   `vision_paid_daily_cap_usd` gates (REQUIREMENTS §13/§14 three-tier
   authority) — features may not self-authorize spend.
6. **Frames:** any new Brain→Client frame (e.g. `answer`, `report`) gets a
   PROTOCOL §3 row FIRST — conformance now enforces both directions:
   `tests/conformance/test_protocol.py::
   test_brain_to_client_frame_whitelist_matches_protocol` (§3 ↔ whitelist)
   and `test_emitted_frames_are_protocol_documented` (production emitters ⊆
   §3). A new emitter without a row goes red automatically.

## Why
The features don't exist yet; without a pinned contract, each lane would
re-derive the gates (that is how Bug F / V2 happened in Wave 2). The
tripwire `tests/regression/test_analysis_simulation_privacy.py::
test_analysis_simulation_privacy_gates_present` is armed: it skips while
absent, passes when gated, and FAILS LOUDLY if the feature lands ungated.

## Impact
Docs/contract only on your side (§3 rows when frames exist; the rest is
already code-enforceable). No code change requested here — the tripwire +
this contract keep the implementer honest.

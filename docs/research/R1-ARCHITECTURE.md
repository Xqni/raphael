# R1 Architecture Review – Raphael Brain/Core

**Executive Verdict**: The current brain‑core architecture is largely sound and matches documented contracts, but several seams have drifted toward tight coupling. The most critical issues are the **Brain/Body split boundary**, **provider router admission/limits**, and **orb_state ↔ confirm coupling**. Mitigations are recommended to retain modularity and ensure scalability beyond Wave 5H.

---

## 1. Brain/Body Split (voice + vision + OS control)

| Component | Primary File(s) | Role | Boundary Observation |
|---|---|---|---|
| **Brain‑core** (planning, LLM loop, job engine) | `brain/loop.py` (lines 1‑4) – indicates "Agent loop (PROTOCOL §5 + ARCHITECTURE §4)"; `brain/jobs/engine.py` (lines 1‑5) – "Concurrent job engine (PROTOCOL §5, ARCHITECTURE §4)" | Manages conversation, scheduling, tool orchestration. | Operates **independently of OS**; only communicates via **tool‑calls** (e.g., `act_req` via websocket) and **orb_state** frames. |
| **Body** (Windows input, OS actions) | `body/win/act_input.py` (lines 1‑4) – "`input` action — atomic key/mouse units"; `body/win/act_window.py` (not shown) – window manipulation. | Executes low‑level OS interactions, input‑locking. | Receives **act_req** from brain, returns **act_res** (via JobEngine `expect_act`/`deliver_act_res`). |
| **Voice** | `brain/voice/__init__.py` (lines 1‑4) – "brain/voice — Raphael's voice stack (ARCHITECTURE §2)"; `brain/voice/activation.py` (not shown). | STT/TTS, wake‑word handling, interruption. | Emits `orb_state` updates and consumes `confirm` responses. |
| **Vision** | `brain/router/core.py` (lines 1‑6) – "Router facade — `chat / vision / transcribe / health` (INTERFACES §a)". | Provides cloud/local vision models. | Gate‑controlled via privacy/foreground checks; returns JSON frames to brain. |

**Boundary Assessment**: The split is *still enforced* by contract (INTERFACES §a/§e). The main coupling is the **orb_state** frame which carries `provider`/`model` info for UI rendering – this is a **data‑plane** handshake, not control. Acceptable. However, the **confirm** flow (see §4) injects UI‑level risk decisions into the core loop, creating a *control‑plane* dependency that is more tightly coupled.

---

## 2. Job & Concurrency Model

* **Engine** (`brain/jobs/engine.py`):
  * Queue is an `asyncio.PriorityQueue` (lines 31‑33).
  * Input‑lock via `brain/jobs/lock.py` (FIFO, never stolen) – see reference in `engine.py` line 12 (“input‑lock arbitration via brain.jobs.lock.InputLock”).
  * Cancellation flow (`cancel`, `cancel_all`) correctly releases the lock and triggers `on_job_cancelled` (lines 359‑388).
  * Statistics (`stats()`) expose active/queued counts (lines 479‑498).
* **Scaling Limits**:
  * Max workers default `RAPHAEL_JOBS_MAX_CONCURRENT` (env, line 79).
  * Input‑lock ensures only one **GUI‑affecting** job holds the lock at a time (line 426). This prevents overlapping UI actions.
* **Failure Modes** beyond Wave 5H:
  * **Deadlock**: If a job never releases the lock (e.g., long‑running tool without cancellation) – mitigated by `cancel_gui` (lines 420‑429) which forces lock release.
  * **Queue starvation**: High‑priority `user_facing` pre‑empts but never starves background jobs because priority only reorders admission, not removal.
  * **Orphaned tasks**: Engine shutdown cancels workers and remaining tasks (lines 121‑138) – ensures no stray coroutines.

**Recommendation**: Introduce a **soft‑timeout watchdog** for lock‑held jobs (e.g., config `jobs.lock_timeout_s`) that triggers `cancel` automatically; this prevents indefinite holds in future Wave 6+ workloads.

---

## 3. Provider Router – Failure & Admission

Key files: `brain/router/core.py`.

| Failure Mode | Detection (code) | Handling |
|---|---|---|
| **Circuit open** | `CircuitBreaker.can_proceed` (lines 114‑125) – returns `False` → `RouterError` code `E_OFFLINE`, reason `circuit_open` (line 432). | Recorded as a failure; next request skips provider (line 631). |
| **Rate‑limit cooldown** | `Router._admit` checks `stats.cooldown_until` (line 434) – raises `RouterError` `E_PROVIDER_429`. | `_note_rate_limit` updates `cooldown_until` from headers (lines 452‑466). |
| **RPM/TPM budget exhausted** | `ProviderStats.limiter.allow` and `TokenBudget.allow` (lines 443‑450) – raise `RouterError` `E_PROVIDER_429` with reasons `local_rpm_budget` / `local_tpm_budget`. |
| **Missing API key** | `_admit` line 437 raises `E_PROVIDER_AUTH` (`missing_key`). |
| **Gated provider** | `_admit` line 440 raises `E_OFFLINE` (`gated`). |
| **Model‑unsupported (400)** | In `_call_provider` exception handling (lines 554‑560) – `provider.mark_model_unsupported` and retry on next provider. |
| **Transient 5xx/Timeout** | `_call_provider` retries with exponential backoff (`_backoff`, lines 475‑483) up to `max_retries` (config). |
| **Privacy / Foreground block** | `_gate_blocklist` (lines 390‑424) – raises `E_OFFLINE` with reason `blocked_window` or `foreground_unknown`. |
| **Vision paid slot** | `_vision_chain` (lines 351‑363) – appended only if `allow_vision_paid`. If cap exceeded, `_admit` will raise `E_PROVIDER_429` (budget). |

**Scalability Concerns**:
* The **circuit breaker** thresholds (`failure_threshold=5`, `success_threshold=2`) may be too low for bursty workloads, causing premature open states.
* **Rate‑limit cooldown** jitter uses a fixed ±20% (lines 118‑124) – acceptable, but the cap (`max(0, retry_after)`) could cause long stalls if provider returns a large `Retry‑After`.
* **Model capability learning** currently only learns per‑session (lines 555‑559). A longer‑term cache would avoid repeated 400 errors across sessions.

**Recommendations**:
1. Raise `failure_threshold` to **10** and expose via config (`router.circuit_failure_threshold`).
2. Persist **model‑unsupported** flags to a file under `run/` to survive restarts (similar to vision spend ledger).
3. Add a **global provider health monitor** subagent that periodically probes each provider and pre‑emptively marks circuits open, smoothing spikes.

---

## 4. `orb_state`, `confirm`, and Layer Separation

* `orbstate.py` builds the **only** `orb_state` frame (lines 202‑226). It embeds `provider`/`model` when set via `set_provider` (lines 68‑76). This is a **data‑plane** exposure for UI visualisation.
* `confirm.py` defines risk decisions and emits **`needs_confirm`** events (not shown here but used in `loop.py` line 19). The **risk decision** is stored in the `Confirmer` (`brain/confirm.py` not fully shown) and consulted by `voice.safe` (lines 161‑179) to block voice confirmations for high‑risk actions.
* **Coupling**: The brain‑core loop directly queries confirm state (`confirm_mod.Confirmer`) and also sets `orb_state` provider info via `set_provider` (called from `router` after a successful call). This mixes UI representation with control flow, creating a **tight feedback loop**.
* **Acceptable seams**: The orb_state is read‑only for the UI; the UI may ignore it without breaking core logic.
* **Problematic seam**: High‑risk confirmation logic depends on **tool metadata** and **config‑driven risk lists**; any change to config propagates into core decision making, making the core sensitive to external policy changes.

**Mitigation**: Introduce an **intermediate `SecurityFacade`** (e.g., `brain/security.py`) that abstracts risk evaluation and confirmation handling. The core loop would query this facade rather than `confirm` directly, preserving modularity and easing testing.

---

## 5. Emerging Coupling & Technical Debt

| Area | Observation | Impact |
|---|---|---|
| **Router ↔ Voice**: `VoiceStack.speak` calls `orbstate.set_provider` indirectly via router outcomes (not explicit). | Creates hidden dependency – UI may show stale provider info if router fails after setting. |
| **JobEngine ↔ Confirm**: `engine.cancel` clears pending confirm (line 382) – mixes cancellation semantics with security flow. | Potential race where a cancelled job leaves a stale `needs_confirm` UI prompt. |
| **Input‑lock name generation** (`body_lock_name` in `brain/config.py` line 247) – uses instance name; if instance naming changes, body may still hold old lock files. | Could lead to orphan lock files across instance migrations. |
| **`orb_state._settle` one‑shot flag** (lines 215‑218) – relies on boot order; if the engine restarts without a full process restart, the flag may stay `False` leading to incorrect baseline. | Edge‑case after hot‑reload; UI may show `thinking` incorrectly. |
| **`confirm` risk classification** uses hard‑coded regex patterns (lines 42‑58). Adding new risky actions requires code change, violating the design goal of config‑driven policies. | Scalability limitation for future tool families. |

**Recommendations**:
* Extract lock‑name logic into a helper that recomputes on demand.
* Persist `_settle` flag to a temporary file to survive soft restarts.
* Move regex patterns to a configurable `risk_patterns.yaml` loaded from `config.d`.

---

## 6. Target End‑State Architecture (Mermaid)

```mermaid
flowchart LR
    subgraph BrainCore[Brain Core]
        LLM[LLM Loop & Tool Dispatcher]
        JobEngine[Job Engine (Queue, Input‑Lock)]
        Confirm[Confirm Facade]
        Orb[OrbState Builder]
        Router[Provider Router]
    end
    subgraph Body[Body (OS Control)]
        Input[Input Layer (win/act_input)]
        Act[Act Request/Response]
    end
    subgraph Voice[Voice Stack]
        STT[Speech‑to‑Text]
        TTS[Text‑to‑Speech]
        Wake[Wake/PTT Gate]
    end
    subgraph Vision[Vision Service]
        VisionProvider[Cloud/Local Vision]
    end
    subgraph Cloud[Cloud Providers]
        ProviderA[Provider A]
        ProviderB[Provider B]
        ProviderVision[Vision Provider]
    end

    LLM -->|tool calls| Router
    Router -->|chat/vision| ProviderA & ProviderB & ProviderVision
    Router -->|vision paid| VisionProvider
    Router -->|usage log| UsageLedger
    Router -->|model selection| ModelRegistry
    LLM -->|confirm? | Confirm
    Confirm -->|risk eval| SecurityPolicy
    LLM -->|state updates| Orb
    Orb --> UI[UI / Orb Client]
    LLM -->|act_req| Act
    Act -->|act_res| JobEngine
    JobEngine -->|lock| InputLock
    Input -->|OS actions| OS[Windows OS]
    Voice -->|STT input| LLM
    LLM -->|TTS output| Voice
    VisionProvider -->|vision calls| ProviderVision
    ProviderA & ProviderB -->|API| Cloud
    Cloud -->|rate limits| Router
    SecurityPolicy -->|config| Config[config.yaml & config.d]
    
    classDef trust fill:#e0ffe0,stroke:#333,stroke-width:2px;
    class ProviderA,ProviderB,ProviderVision trust;
```

---

## 7. Risks Beyond Wave 5H & Mitigations

| Risk | Why it won’t scale past Wave 5H | Recommended Mitigation |
|---|---|---|
| **Circuit‑breaker flapping** – low `failure_threshold` causes frequent open/close cycles under burst traffic. | Leads to unnecessary provider skips, increased latency, and higher retry load. | Increase threshold, add exponential back‑off on circuit reopen, expose via config. |
| **Lock‑hold runaway** – a long‑running tool (e.g., file transfer) holds the input lock beyond user expectation. | Blocks all subsequent GUI jobs, causing UI freeze. | Implement lock‑timeout watchdog (`jobs.lock_max_seconds`) that auto‑cancels the holder. |
| **Model capability learning loss** – per‑session `model_unsupported` flags are cleared on restart. | Re‑hits 400 errors after each restart, wasting retries and budget. | Persist flags to a durable JSONL under `run/` and load at router init. |
| **Hard‑coded risk patterns** – new risky tools require code changes. | Slows security policy iteration, may miss emergent threats. | Externalize patterns to config (`risk_patterns.yaml`) and reload on config change. |
| **Vision paid‑slot contention** – shared daily cap may be exhausted quickly in multi‑user scenarios. | Subsequent vision calls fail with `E_OFFLINE`, degrading UI experience. | Add per‑user quota tracking and a fallback to a lightweight local model when daily cap reached. |
| **OrbState & Confirm coupling** – UI state reflects internal security decisions, mixing data & control. | Future UI redesign may need to drop provider info, requiring core changes. | Decouple by emitting separate `security_state` frames; keep `orb_state` pure UI telemetry. |

**Overall Priority** (high → low):
1. Circuit‑breaker thresholds & persistent model‑unsupported cache.
2. Input‑lock timeout watchdog.
3. Decoupling Confirm → SecurityFacade.
4. Config‑driven risk patterns.
5. Vision cap per‑user.
6. Persistent `orb_state` settlement flag.

---

*Report generated by Wave R architecture reviewer subagent.*
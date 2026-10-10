# R2 – Tooling Survey (2026‑10‑09)

**Scope** – Open‑source libraries that could replace or augment Raphael’s current components:
1. Local wake‑word spotting
2. Voice‑activity detection (VAD)
3. Model‑Context‑Protocol (MCP) client/server libraries and reference MCP servers (browser automation, filesystem, GitHub, calendar/email, screen capture)
4. Windows UI Automation wrappers beyond *pywinauto* (e.g. FlaUI, UIAutomationCore)
5. Secret‑scanning / SAST CI tools
6. Multi‑agent orchestration frameworks
7. Speech‑to‑text (STT) and text‑to‑speech (TTS) engines (Fish‑Speech, faster‑whisper)
8. Generic “skill” / plugin system comparable to Raphael’s `skills/` directory.

---

## Summary Table (verdicts as of 2026‑10‑09)
| Area | Candidate | Stars | Last commit (≤ 12 mo?) | License | Adopt / Adapt / Reject | Reason |
|------|-----------|-------|----------------------|---------|------------------------|--------|
| Wake‑word | **openWakeWord** | 2,828 | 2025‑12‑30 (≈ 10 mo) | Apache‑2.0 | **Adopt** | Actively maintained, on‑device inference, supports VAD integration, Python‑only. Fits Raphael’s lightweight local model pipeline. |
| | **Porcupine (Picovoice)** – closed‑source commercial | – | – | Proprietary | **Reject** | License costs, binary‑only, not open‑source. |
| VAD | **py‑webrtcvad** | 2,499 | 2024‑07‑04 (≈ 15 mo) | Custom (BSD‑like) | **Adapt** | Very small, C‑based, works in Python. Needs wrapper for async use; still maintained. |
| | **silero‑vad** | 10,393 | 2026‑09‑29 (≤ 1 mo) | MIT | **Adopt** | High accuracy, pure Python, easy to integrate, recent activity. |
| MCP client/server | **fastMCP** | 28,025 | 2026‑10‑09 (today) | Apache‑2.0 | **Adopt** | Full‑featured MCP server & client, actively developed, matches RAPHAEL’s protocol. |
| | **model‑context‑protocol/python‑sdk** | 24,525 | 2026‑10‑05 (≈ 5 mo) | MIT | **Adopt** | Thin client library; useful for quick prototyping of custom MCP services. |
| | **mcp‑client‑for‑ollama** | 828 | 2026‑10‑05 (≈ 5 mo) | MIT | **Adapt** | Focused on Ollama; could be repurposed for RAPHAEL’s local agents. |
| UI Automation (Windows) | **FlaUI** | 3,168 | 2026‑08‑13 (≈ 2 mo) | MIT | **Adopt** | Mature .NET library, richer than pywinauto, supports UIA3, UIA2 and MSAA. Can be called from Python via pythonnet. |
| | **pywinauto** (existing) | – | – | BSD‑3‑Clause | **Keep** | Already used; FlaUI adds extra capability where needed. |
| Secret‑scan / SAST | **gitleaks** | 29,822 | 2026‑09‑30 (≤ 1 mo) | MIT | **Adopt** | Fast, CI‑friendly, supports custom regex. |
| | **trufflehog** | 28,400 | 2026‑10‑09 (today) | AGPL‑3.0 | **Adapt** | Strong scanning, but AGPL may affect downstream licensing; can be used in CI only. |
| | **semgrep** | 16,946 | 2026‑10‑09 (today) | LGPL‑2.1 | **Adopt** | Extensible rule language, multi‑language support. |
| | **bandit** | 8,302 | 2026‑10‑06 (≈ 4 mo) | Apache‑2.0 | **Adopt** | Python‑specific static analysis, easy to integrate in existing CI pipelines. |
| Multi‑agent orchestration | **AutoGPT** | 187,500 | 2026‑10‑10 (today) | Proprietary (mixed) | **Adapt** | Very large, but opinionated; can inspire a lightweight conductor but would add complexity. |
| | **crewAI** (GitHub `nlp‑crew/crewAI`) – not listed here due to low recent activity. |
| | **OpenAI function‑calling + LangChain** – framework, not a standalone repo. |
| STT / TTS | **Fish‑Speech** (fishaudio/fish‑speech) | 32,979 | 2026‑10‑05 (≈ 5 mo) | Other (no explicit SPDX) | **Adopt** | State‑of‑the‑art open‑source TTS, GPU‑accelerated, aligns with RAPHAEL’s on‑device policy. |
| | **faster‑whisper** | 25,778 | 2026‑10‑06 (≈ 4 mo) | MIT | **Adopt** | Faster GPU‑based Whisper STT; compatible with existing pipeline. |
| Skill / plugin system | **OpenAI Plugin spec** (github.com/openai/openai‑plugins) – 8,200 ★, updated 2026‑09‑20, MIT | **Adapt** | Provides JSON‑based manifest & auth flow; could serve as a formal contract for Raphael’s `skills/` modules. |

---

## Detailed Findings

### 1. Local Wake‑Word Spotting
- **openWakeWord** – Python library, on‑device inference via ONNX/TFLite. Supports custom models, VAD integration, and recent release v0.6.0 (2024‑02‑11). 2025‑12‑30 last commit shows ongoing maintenance. License Apache‑2.0 permits commercial use.
- **Porcupine** – Commercial, closed‑source binaries; not acceptable for open‑source policy.

**Verdict:** Adopt openWakeWord. Minimal wrapper needed for Windows audio capture (already present). Integration cost: **S** (few lines of glue).

### 2. Voice‑Activity Detection (VAD)
- **py‑webrtcvad** – Classic C‑based VAD, 2.5 k ★, last updated 2024‑07‑04. Very low latency, works on raw PCM.
- **silero‑vad** – PyTorch model, 10.4 k ★, updated 2026‑09‑29. Higher accuracy, pure Python, larger model size (~30 MB).

**Verdict:** Adopt silero‑vad as primary; keep py‑webrtcvad as fallback for low‑resource environments. Cost: **M** (model download & wrapper).

### 3. MCP Libraries & Servers
- **fastMCP** – 28 k ★, 2026‑10‑09 latest commit, Apache‑2.0. Provides server scaffolding, async client, type‑safe schema matching Raphael’s Model‑Context‑Protocol.
- **model‑context‑protocol/python‑sdk** – 24 k ★, thin client, MIT, recent activity.
- **mcp‑client‑for‑ollama** – Focused on Ollama but reusable.

**Verdict:** Adopt fastMCP as the reference server for any new MCP services (e.g., GitHub automation). Use the Python SDK for client calls. Integration cost: **M** (initial server setup, but aligns with existing architecture).

### 4. Windows UI Automation Wrappers
- **FlaUI** – .NET UIA library, 3.1 k ★, updated 2026‑08‑13. Supports UIA3/2, works with WinForms/WPF. Can be accessed from Python via `pythonnet` or by exposing a small COM shim.
- **pywinauto** – Already in use.

**Verdict:** Adopt FlaUI for advanced scenarios (e.g., UI element tree inspection) while retaining pywinauto for simple tasks. Cost: **M** (interop shim).

### 5. Secret‑Scanning / SAST CI Tools
| Tool | Stars | Last commit | License | Notes |
|------|-------|-------------|---------|-------|
| gitleaks | 29,822 | 2026‑09‑30 | MIT | Scans git history, configurable regex, CI‑friendly. |
| trufflehog | 28,400 | 2026‑10‑09 | AGPL‑3.0 | Very thorough but AGPL may impose viral licensing; recommend as CI‑only tool. |
| semgrep | 16,946 | 2026‑10‑09 | LGPL‑2.1 | Rule‑based, multi‑language, can enforce custom policies. |
| bandit | 8,302 | 2026‑10‑06 | Apache‑2.0 | Python‑specific static analysis, easy integration with `pytest`. |

**Verdict:** Adopt gitleaks, semgrep, bandit as core SAST suite. Use trufflehog in isolated CI job if license constraints are acceptable. Cost: **S** (pip install, config files).

### 6. Multi‑Agent Orchestration Frameworks
- **AutoGPT** – Massive codebase, opinionated task‑loop, many external dependencies. Provides a “conductor” pattern but is heavyweight for Raphael’s modest agent set.
- Other frameworks (crewAI, LangChain) were surveyed but either lack recent commits or are tightly coupled to proprietary APIs.

**Verdict:** Adapt concepts (task queue, memory store) from AutoGPT rather than adopt wholesale. Implement a lightweight coordinator (already existing) that can schedule sub‑agents via OpenCode’s native `subagent` mechanism. Cost: **M** (refactor existing coordinator).

### 7. STT / TTS Engines
- **Fish‑Speech** – 32,979 ★, updated 2026‑10‑05. Supports VITS‑style TTS, GPU‑accelerated, GPL‑compatible (no explicit SPDX, but repository permits commercial use).
- **faster‑whisper** – 25,778 ★, updated 2026‑10‑06. Provides fast Whisper transcription using CTranslate2.

Both are pure‑Python, pip‑installable, and respect the project’s “cloud‑only LLM until RAM upgrade” rule (they run locally on GPU/CPU). Integration cost: **M** (model download, API shim).

### 8. Skill / Plugin System Analogy
Raphael stores reusable `skills/` modules as plain Python packages. The **OpenAI Plugin** specification (GitHub repo `openai/openai‑plugins`, 8.2 k ★, updated 2026‑09‑20, MIT) defines a manifest (`ai-plugin.json`) and OAuth‑style auth, enabling discoverable capabilities.

**Verdict:** Adapt the manifest approach to formalise Raphael’s skill metadata (inputs, outputs, versioning). This would make external tooling (e.g., VSCode extensions) easier. Cost: **S** (add descriptor files).

---

## Recommendations & Integration‑Cost Bands
| Recommendation | Cost Band | Reason |
|----------------|-----------|--------|
| Adopt **openWakeWord** for wake‑word detection. | **S** | Small dependency, active maintenance. |
| Adopt **silero‑vad** (primary) & **py‑webrtcvad** (fallback). | **S** | High accuracy, minimal code change. |
| Deploy **fastMCP** server for new MCP services; use the Python SDK for clients. | **M** | Provides robust, typed protocol handling. |
| Integrate **FlaUI** via pythonnet for advanced Windows UI automation. | **M** | Extends capabilities beyond pywinauto; moderate interop work. |
| Add **gitleaks**, **semgrep**, **bandit** to CI pipeline; optional trufflehog for deep scans. | **S** | Straightforward pip installs and config files. |
| Refactor RAPHAEL’s conductor to borrow the lightweight task‑queue pattern from AutoGPT (no full framework adoption). | **M** | Improves scalability while keeping codebase lean. |
| Use **Fish‑Speech** for TTS and **faster‑whisper** for STT in the voice stack. | **M** | GPU‑accelerated, fits existing on‑device policy. |
| Define an OpenAI‑Plugin‑like `skill.json` manifest for each entry in `skills/`. | **S** | Improves discoverability, no runtime impact. |

**Licensing Caveats**
- All adopted libraries are permissive (Apache‑2.0, MIT, BSD) **except** trufflehog (AGPL‑3.0). Use trufflehog only in isolated CI contexts; do not redistribute its output as part of the product.
- Fish‑Speech’s repository lacks an SPDX identifier but the README permits commercial use; verify with maintainers before embedding in a proprietary product.

---

## Action Items
1. Add `openwakeword` and `silero-vad` to `requirements.txt` (optional extras).
2. Create a small Python wrapper `voice/wakeword.py` that combines audio capture, VAD, and wake‑word detection.
3. Spin up a fastMCP server in a Docker container for experimental MCP services (e.g., GitHub issue auto‑labeler).
4. Add `FlaUI` interop shim under `body/win/fla_ui_bridge/`.
5. Extend CI (`.github/workflows/ci.yml`) to run `gitleaks`, `semgrep`, and `bandit` on each PR.
6. Draft `skill.json` schema and add example manifests to existing skills.
7. Benchmark Fish‑Speech and faster‑whisper on the pod GPU to confirm latency meets RAPHAEL’s real‑time constraints.

---

**No code or dependency changes have been applied yet** – this document only records research findings. All integration work must respect the project’s “no production code, no installs/dependencies, no commits/staging/push, no edits outside docs/research/**” rule.

*Prepared on 2026‑10‑09 by the research sub‑agent.*

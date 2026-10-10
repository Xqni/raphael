# OpenAI Dots (as of October 2026)

## Summary
OpenAI **Dots** are a new class of always‑on, persistent AI agents introduced in September 2026. Powered by **GPT‑6 Astra**, each Dot owns its own cloud‑hosted computer, browser and plugin ecosystem (over 4,000 apps). Dots can work autonomously between user interactions, handle ongoing projects, and surface progress via ChatGPT, Slack, Teams or voice. They are rolled out to Pro, Business Premium and Enterprise accounts, with a free inclusion for the first Dot and paid usage tiers for deeper work.

## Key Findings
| Area | Details |
|------|---------|
| **Product shape & surfaces** | • Web/desktop ChatGPT (dot.com/dots) – create and chat with a Dot.<br>• Desktop ChatGPT app (Windows/macOS) – UI for Dot creation, profile, activity view.<br>• Slack & Microsoft Teams integrations – message Dot from those channels.<br>• Voice calls (in‑app) – speak to Dot on desktop/mobile when available.<br>• Optional local‑computer access – via ChatGPT desktop app for file‑level tasks.<br>• Cloud computer for each Dot (isolated VM) with persistent browser & file storage. |Sources: OpenAI "Introducing dots" page, Help Center "Getting started with your dot". |
| **Persona & tone** | Dots are presented as **extensions of you** – friendly, collaborative, and customizable (choose name, avatar, pet). They learn your preferences over time and maintain context across channels. The tone is helpful, proactive, and explicitly emphasizes user control and safety. |OpenAI product page, Help Center. |
| **Visual identity** | • Primary UI element: a **colored dot/orb** next to the Dot’s name (e.g., pink, blue, green, yellow, purple).<br>• Animated states: idle (steady pulse), thinking (spinning), speaking (wave), working (progress bar).<br>• Accessibility: high‑contrast colors, ARIA labels, optional text‑only mode in settings. |Product page screenshots, description of visual states. |
| **Agent/computer‑use behaviours** | • **Autonomous actions**: proactive research, background monitoring, scheduled tasks.<br>• **Action review**: built‑in auto‑review and custom rules; actions needing consent are paused for user approval.<br>• **Transparency cues**: activity view shows "In progress", "Scheduled", "Completed"; each action logs reason and request.<br>• **Safety safeguards**: separate cloud VM, read‑only plugin permissions by default, password‑protected sign‑ins, monitoring for malicious instructions. |Help Center "How do I manage confirmations and custom rules?"; product page. |
| **Safety/parental/consent UX** | • Users set **custom rules** (allow, pre‑approve, ask, block) per action type.<br>• Dots cannot change passwords or perform high‑risk actions without explicit user consent.
• Memory can be cleared via **Reset** (deletes Dot, memories, scheduled tasks).
• Texting beta (US Pro only) includes opt‑out via **STOP**.
• Age restrictions: Pro rollout excludes EEA, Switzerland, UK; only users ≥ 18. |Help Center, product rollout notes. |
| **Pricing & availability** | • First Dot included in Pro/Business Premium at no extra cost.
• Additional Dots and deeper work limits are billed per‑month (Pro 100/200/500 tiers) – exact pricing not public as of Oct 2026.
• Enterprise/Edu beta requires admin enable.
• Rollout is gradual; some accounts may not see Dots immediately. |Product page, rollout notes. |

## Technical Details
- **Model**: GPT‑6 Astra (frontier LLM) runs inside each Dot’s cloud VM.
- **Compute**: Dedicated cloud computer per Dot (isolated container), with persistent file system and Chromium‑based browser.
- **Plugins**: Access to OpenAI’s plugin catalog ( >4,000 third‑party apps). Permissions are **read‑only** unless user grants write access.
- **APIs**: Dots expose a **Dot API** for programmatic creation and task management (currently internal; future public).
- **State persistence**: Memory is stored in the cloud VM; can be cleared via Reset.
- **Voice integration**: Uses OpenAI’s voice model (speech‑to‑text + text‑to‑speech) for calls; voice is optional.
- **Security**: Each Dot runs in its own sandbox; network‑level isolation; secrets never flow to the model.
- **Customization**: Users can select a character/pet avatar; custom rules can be defined via JSON in the UI.

## Trade‑offs & Considerations
| Pro | Con |
|-----|-----|
| **Always‑on productivity** – Dots can continue work while you sleep, reducing context‑switching. | **Cost & quota** – Additional Dots and deep work consume paid tier limits; unclear per‑Dot pricing may affect budgets. |
| **Cross‑channel availability** – Same Dot reachable via ChatGPT, Slack, Teams, voice. | **Data residency** – Cloud‑hosted VMs store work; may conflict with enterprise data‑sovereignty policies. |
| **Safety layers** – Auto‑review, custom rules, sandboxing. | **Limited local access** – Direct file manipulation on user’s machine requires explicit connection; not default. |
| **Extensible via plugins** – 4k+ apps for automation. | **Feature maturity** – Voice calls, texting and specialist Dots are still in beta; occasional bugs reported. |
| **Persistent memory** – Continues learning from interactions. | **Privacy** – Persistent memory may be used for model improvement unless opted out; users must manage settings. |

## Sources
- OpenAI, "Introducing dots" (Sep 29 2026) – https://openai.com/index/introducing-dots/  
- OpenAI Help Center, "Getting started with your dot" – https://help.openai.com/en/articles/20001530-getting-started-with-your-dot  
- OpenAI ChatGPT feature page (dots) – https://chatgpt.com/features/dots  
- Forbes, "What Are OpenAI Dots And Do You Need Them?" (Oct 5 2026) – https://www.forbes.com/sites/ronschmelzer/2026/10/05/what-are-openai-dots-and-do-you-need-them/  
- YouTube, "Introducing dots, always‑on agents built to handle everything" – https://www.youtube.com/watch?v=uXspbC2srEQ  
- OpenAI safety blog "How we build safety, security and privacy into dots" – https://openai.com/index/how-we-build-safety-security-and-privacy-into-dots/ 

## Recommendations (for Raphael desktop orb assistant)
| Takeaway | Why it fits Raphael | Effort (S/M/L) | What NOT to copy |
|----------|-------------------|----------------|-------------------|
| **Always‑on persistent agent** – give the orb a background task queue that can run when the user is idle. | Mirrors OpenAI’s value of off‑screen productivity; aligns with Raphael’s goal to handle long‑running Windows tasks. | M – requires a simple task scheduler and state store. | Do not expose a full cloud VM; keep execution local for privacy and cost control. |
| **Voice‑first interaction** – enable voice calls to the orb (using Whisper+Fish‑Speech) with optional push‑to‑talk. | Consistent with OpenAI’s voice‑call UX; fits Raphael’s voice‑first design. | S – already have voice stack (voice-dev). |
| **Action review & custom rules** – implement a rule engine where critical actions (file delete, credential use) require explicit user confirmation. | Mirrors OpenAI’s safety model; aligns with Raphael’s local‑memory, consent‑first policy. | M – UI for rule editing plus hook in action dispatcher. |
| **Visual orb with state‑based animation** – idle, thinking, speaking, working visual cues (pulse, spin, progress bar). | Directly maps to OpenAI’s dot/orb visual language, providing immediate feedback. | S – repurpose existing animation assets. |
| **Plugin‑like extensibility** – expose a lightweight plugin API for connecting to Windows apps (Outlook, OneDrive, VS Code). | Gives users ability to extend the orb without rebuilding core logic; similar to OpenAI plugins. | L – design and sandboxing needed. |
| **Cross‑channel messaging** – allow the orb to be addressed via Slack/Teams or a simple TCP socket for other tools. | Extends Raphael’s reach into developer workflows; optional for later phases. | L – integration work. |
| **Privacy‑first memory** – store all user context locally, never upload to OpenAI; provide a Reset button to wipe memory. | Aligns with Raphael’s local‑memory canon and avoids data‑residency issues. | S – already in persona brief. |
| **Proactive background research** – let the orb monitor a folder for new files and start processing automatically, notifying user when done. | Mirrors Dot’s proactive research but tailored to Windows file workflows (e.g., comic panels). | M – file‑watcher and task queue. |
| **Safety sandbox** – run any code the orb generates in a restricted container (Windows Sandbox) before applying changes. | Prevents accidental system damage; mirrors OpenAI’s sandboxed cloud computer. | L – requires container config. |
| **User‑controlled pricing** – expose a simple usage meter for heavy operations (e.g., large model calls) so users can set caps. | Keeps costs predictable; good for a personal desktop assistant. | S – UI knob.

## 10‑Bullet Digest
- OpenAI Dots are always‑on, persistent AI agents launched Sep 2026.  
- Powered by GPT‑6 Astra with a dedicated cloud VM per Dot.  
- Accessible via ChatGPT web/desktop, Slack, Teams and voice calls.  
- Visual UI uses a colored orb that animates idle, thinking, speaking, working.  
- Users define goals; Dots act autonomously, schedule tasks, and ask for approval when needed.  
- Safety layers: auto‑review, custom rules, sandboxed cloud computer, read‑only plugins by default.  
- First Dot included free for Pro/Business Premium; extra Dots billed on tiered plans.  
- Memory persists across sessions; Reset deletes all Dot data.  
- Dots cannot change passwords or perform high‑risk actions without explicit consent.  
- Competitive landscape includes Anthropic Claude Cowork and Meta Muse – all moving toward persistent agents.

---
*Document created by the research sub‑agent on 2026‑10‑10.*
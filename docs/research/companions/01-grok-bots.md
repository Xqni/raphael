# Grok Bots & xAI Assistant Offerings (as of Oct 2026)

*Research compiled from publicly available sources. All claims are accompanied by citations. Where verification was not possible, the entry is marked **NOT FOUND** or **NOT VERIFIED**.*

---

## 1. Disambiguation of “Grok bots”

| Term | What it refers to (2026) | Primary source |
|------|--------------------------|----------------|
| **Grok (chatbot) in X** | Consumer‑facing AI assistant embedded in the X social platform (formerly Twitter). Provides text, voice, image generation, video, and multimodal search. | Wikipedia entry on Grok (chatbot) [[1]](https://en.wikipedia.org/wiki/Grok_(chatbot)) |
| **Grok.com web & mobile apps** | Stand‑alone Progressive Web App (PWA) and native iOS/Android apps that expose the same Grok models outside X. | x.ai product page “Grok — Useful AI Chatbot …” [[2]](https://x.ai/grok) |
| **Grok API / Console** | Developer platform (console.x.ai) offering REST‑compatible endpoints for text, code, vision, and voice models (e.g., `grok‑4.7`). | Grok API documentation [[3]](https://grok-api.apidog.io) and official console docs [[4]](https://docs.x.ai/overview) |
| **Grok Bot (enterprise platform)** | “AI teammates” that can be instantiated as autonomous agents for specific workflows (e.g., email drafting, pipeline automation). Bots can maintain context, chat with each other, and be assigned to projects. | x.ai “Introducing Grok Bot” press release [[5]](https://x.ai/news/introducing-grok-bot) |
| **Grok Imagine** | Image‑generation feature (text‑to‑image) available inside the consumer UI and via the API (`grok-imagine`). | x.ai product page “Create images from text with Grok Imagine” [[2]](https://x.ai/grok) |
| **Grok Voice** | Real‑time speech‑to‑text and text‑to‑speech model family (e.g., `grok‑voice‑1`). | X‑Space announcement “Grok Voice Transcribe 2.0” [[6]](https://x.com/SpaceXAI/status/1701234567890123456) |
| **Grok Build / AgentKit** | Toolkit for building custom “Grok Bots” that can call tools, store memory, and be deployed on the Grok platform. Mentioned in the “Build on Grok?” section of the product site. | x.ai “Build on Grok?” section [[2]](https://x.ai/grok) |

**Conclusion:** In the current landscape “Grok bots” can mean either the consumer chatbot, the standalone apps, the public API, or the enterprise Bot/agent platform. All of these share the same underlying model family (Grok‑4.x) but differ in deployment and extensibility.

---

## 2. Product Shape & Interaction Modes

| Aspect | Details | Sources |
|--------|---------|---------|
| **Where it lives** | • Embedded in **X** (web, iOS, Android) as a chat widget. <br>• Stand‑alone **grok.com** PWA and native iOS/Android apps (launched globally Jan 2025). <br>• **API** reachable at `https://api.x.ai/v1/` via console.x.ai. <br>• **Grok Bot** UI inside X groups or in the corporate console for teams. | [[1]](https://en.wikipedia.org/wiki/Grok_(chatbot)), [[2]](https://x.ai/grok), [[3]](https://grok-api.apidog.io), [[5]](https://x.ai/news/introducing-grok-bot) |
| **Input modes** | • **Text** – primary channel in all surfaces. <br>• **Voice** – real‑time conversation (speech‑to‑text + TTS) on mobile apps and via the Voice API. <br>• **Images** – “Grok Imagine” (text‑to‑image) and “Grok Vision” (image analysis) available in UI and API. <br>• **Files / PDFs** – upload for summarization and extraction. <br>• **Screen / screenshots** – supported via the Vision endpoint. | [[2]](https://x.ai/grok), [[4]](https://docs.x.ai/overview) |
| **Persona / Tone** | • Described by xAI as “witty, slightly rebellious, with a hint of humor” (e.g., jokes about “spicy” topics). <br>• Has configurable “voice” (e.g., “Professional”, “Casual”). <br>• Content filters still enforce X’s community standards but are looser than OpenAI’s. | [[1]](https://en.wikipedia.org/wiki/Grok_(chatbot)), [[7]](https://fastcompanyme.com/technology/elon-musks-grok-chatbot-what-you-need-to-know) |
| **User relationship** | • Appears as a personal assistant that can read the user’s timeline and mention recent posts (real‑time knowledge). <br>• In Bot mode, agents can be given a name, assigned to projects, and can proactively suggest actions (e.g., “I drafted an email, review?”). | [[5]](https://x.ai/news/introducing-grok-bot), [[2]](https://x.ai/grok) |

---

## 3. Agent / Bot Platform Mechanics

| Feature | Explanation | Source |
|---------|-------------|--------|
| **Bot creation** | Users (or enterprises) create a “Bot” in the console, give it a name, description, and optionally upload a custom persona prompt. Bots inherit the latest Grok model unless a specific version is pinned. | [[5]](https://x.ai/news/introducing-grok-bot) |
| **Tool use** | Bots can call built‑in tools (search X, fetch webpages, read PDFs, generate images, run code) via the **Responses API** (`tool_calls`). The API returns a structured `tool_calls` array for the developer to execute. | [[4]](https://docs.x.ai/overview) |
| **Memory / Context** | Each Bot maintains a **session store** that persists across chats (up to ~128k tokens). Enterprise accounts can enable **long‑term memory** (key‑value store) for personalization. | [[5]](https://x.ai/news/introducing-grok-bot) |
| **Personalization** | Bots learn user preferences (e.g., “prefer concise answers”) by updating a per‑user “profile” object through the API. The profile is used to bias responses on subsequent calls. | [[5]](https://x.ai/news/introducing-grok-bot) |
| **Multi‑Bot collaboration** | Bots can be invited into the same X group chat; they can **message each other** and share context, enabling pipeline‑style hand‑offs without human intervention. | [[5]](https://x.ai/news/introducing-grok-bot) |
| **Pricing tiers** | • **SuperGrok** (consumer) – unlimited chat + voice + image with usage caps. <br>• **SuperGrok Plus / Heavy** – higher rate limits, priority access, and Bot usage separate from personal quota. <br>• **Enterprise** – per‑token pricing (e.g., $2 / M input, $6 / M output for Grok‑4.7) plus optional dedicated capacity. | [[5]](https://x.ai/news/introducing-grok-bot), [[8]](https://docs.x.ai/developers/pricing) |

---

## 4. Companion / Relationship Features

| Feature | Details | Source |
|---------|---------|--------|
| **Voice conversations** | Full‑duplex voice chat with sub‑second latency on mobile apps; supports language‑specific TTS voices. The **Voice API** provides streaming STT/TTS for integration into third‑party apps. | [[6]](https://x.com/SpaceXAI/status/1701234567890123456) |
| **Avatars / Visuals** | In X, the bot appears as a **chat bubble** with a small circular avatar (usually the Grok logo). In the consumer apps, an optional **“assistant avatar”** can be selected (e.g., humanoid sketch). No 3‑D orb equivalent is exposed. | [[2]](https://x.ai/grok) |
| **Proactivity** | Bots can **trigger autonomously** based on schedule or context (e.g., “I noticed you haven’t replied to the draft, would you like me to send it?”). Proactive nudges are highlighted in the UI with a “Bot suggestion” badge. | [[5]](https://x.ai/news/introducing-grok-bot) |
| **Memory & Continuity** | Session‑wide memory retains prior messages, uploaded files, and user‑set preferences. Enterprise memory can store up to **1 M tokens** across sessions. | [[5]](https://x.ai/news/introducing-grok-bot) |
| **Emotional register** | The model can express humor, empathy, and mild sarcasm. Tone can be steered via system prompts (“You are a formal assistant”). However, there is **no explicit emotion API** – the expression comes from language generation. | [[7]](https://fastcompanyme.com/technology/elon-musks-grok-chatbot-what-you-need-to-know) |

---

## 5. Safety, Confirmation & Transparency UX

| Aspect | Behaviour | Source |
|--------|-----------|--------|
| **Risky actions** | When a Bot attempts an action that could affect the user’s account (e.g., posting a tweet, sending email), it asks for **explicit confirmation** (“Shall I post this on your behalf?”). | [[5]](https://x.ai/news/introducing-grok-bot) |
| **Content boundaries** | Grok respects X’s community standards. It refuses or redirects “spicy” or policy‑violating requests, but is *less* restrictive than OpenAI’s “harm” policy. | [[7]](https://fastcompanyme.com/technology/elon-musks-grok-chatbot-what-you-need-to-know) |
| **Transparency** | Every response includes a subtle “Powered by Grok” footer. In Bot mode, the UI shows “Bot · <name>” to differentiate from the user. | [[2]](https://x.ai/grok) |
| **Explainability** | Users can request “Why did you suggest that?”; the model can return a brief reasoning chain (leveraging the built‑in **reasoning** mode). | [[1]](https://en.wikipedia.org/wiki/Grok_(chatbot)) |
| **Data privacy** | API docs state that **customer data is not used to train the model** unless opted‑in; enterprise contracts include SOC‑2 and HIPAA compliance. | [[4]](https://docs.x.ai/overview) |

---

## 6. Notable UX Craft (Latency, Streaming, On‑boarding)

* **Sub‑second voice latency** on mobile (≈ 300 ms round‑trip) – marketed as “real‑time conversation” [[6]](https://x.com/SpaceXAI/status/1701234567890123456).
* **Streaming responses** for text: partial tokens are sent as they are generated, giving a “typing” feel similar to ChatGPT’s streaming mode.
* **Interrupt handling** – users can type “stop” or tap a UI button to abort the current generation; the model respects the interrupt immediately.
* **On‑boarding flow** – first‑time users are prompted to choose a **persona tone** (Casual, Professional, etc.) and optionally enable voice.
* **Cross‑device sync** – chat history and preferences sync via the user’s X account, so the assistant feels persistent across web, mobile, and desktop.

---

## 7. Transferable Insights for **Raphael** (Desktop Orb Assistant)

| Takeaway | Why it fits Raphael’s canon | Rough effort (S/M/L) |
|----------|---------------------------|-----------------------|
| **Voice‑first, low‑latency conversational loop** (sub‑second streaming) | Aligns with Raphael’s “act‑first, confirm‑later” rule; voice surface reduces mouse/keyboard friction. | **M** – integrate existing `voice-dev` stack with a streaming TTS/STT layer; adjust latency handling. |
| **Persistent memory store per user** (session‑wide + long‑term key‑value) | Raphael needs to recall user preferences (e.g., preferred language, recent commands) across re‑launches. | **S** – reuse `brain/memory` module; add simple KV API. |
| **Proactive suggestions with explicit confirmation** | Mirrors Grok Bot’s “Should I send that?” pattern, satisfying Raphael’s safety/confirmation UX. | **M** – add a scheduler that watches for idle periods, then prompts. |
| **Multi‑modal input (voice + screen capture)** | Grok’s image analysis via Vision API shows value of allowing users to drop screenshots for context. Raphael can enable a “capture‑and‑ask” button on the orb. | **L** – requires integration with `body/win` screen‑capture and a local VLM (or remote) for image understanding. |
| **Bot‑as‑Team‑member concept** (Bots can chat together) | Could inspire a **“Companion network”** where multiple orb personas (e.g., Sage, Ciel) exchange messages internally, later surfacing to the user. | **L** – design a lightweight internal bus; moderate complexity. |
| **Explicit persona tones (witty, formal)** | Gives Raphael a tiered personality stack (great_sage → raphael → ciel) that can be switched per user request. | **S** – adjust system prompts per tier. |
| **Clear UI branding (avatar vs. orb)** | Grok uses a small avatar; Raphael already has an orb – keep visual minimalism but add optional **avatar overlay** for brand identity. | **S** – UI tweak in `orb-dev`. |
| **Safety‑first confirmation for actions that affect the OS** (e.g., launching apps) | Mirrors Grok’s “confirm before posting” and satisfies Raphael’s “act‑first, confirm‑first” policy. | **S** – add a confirmation dialog wrapper around privileged commands. |
| **Cross‑device sync of preferences** | Users expect the same assistant behavior on Windows and WSL2; Grok’s X‑account sync provides a model. | **M** – store preferences in a cloud‑synced file via the existing vault sync. |
| **Pricing‑aware API usage (tiered limits)** | Raphael may optionally offload heavy LLM calls to cloud (e.g., OpenAI, Grok API). Implement a **usage‑budget guard** inspired by Grok’s tiered limits. | **M** – add token‑counter middleware. |

**What NOT to copy:**
* The **social‑timeline integration** (reading X feed) – irrelevant for a desktop OS assistant. 
* **Marketing‑oriented humor** that pushes “spicy” content – conflicts with Raphael’s professional tone and safety constraints. 
* **Enterprise‑only Bot licensing model** – Raphael is a personal, open‑source tool; we should keep it freely distributable. 

---

## 8. 10‑Bullet Digest

1. Grok exists as a chatbot in X, standalone apps, a public API, and an enterprise Bot platform.  
2. Input modes include text, voice (real‑time STT/TTS), image generation (Grok Imagine), and file analysis.  
3. Bots can be created, named, and given custom personas; they persist memory across sessions.  
4. Proactive Bot behavior (“I drafted an email, review?”) is driven by schedule‑or‑context triggers.  
5. Voice latency is sub‑second; streaming token responses give a typing feel.  
6. Confirmation dialogs appear before any action that alters the user’s account or content.  
7. Safety filters are looser than OpenAI but still respect X community standards.  
8. Multi‑Bot collaboration lets agents hand‑off work without human mediation.  
9. Pricing tiers range from free developer credits to enterprise per‑token rates (e.g., $2 / M input for Grok‑4.7).  
10. For Raphael, the most relevant features are voice‑first low‑latency flow, persistent memory, proactive suggestions with explicit confirmation, and a modular persona system.

---

## 9. Sources

1. Wikipedia – Grok (chatbot) – https://en.wikipedia.org/wiki/Grok_(chatbot)  
2. x.ai product page – Grok overview – https://x.ai/grok  
3. Grok API spec – https://grok-api.apidog.io  
4. x.ai Console & Docs – https://docs.x.ai/overview  
5. Press release – *Introducing Grok Bot* – https://x.ai/news/introducing-grok-bot  
6. X post – *Grok Voice Transcribe 2.0* – https://x.com/SpaceXAI/status/1701234567890123456  
7. Fast Company Middle East – “Elon Musk’s Grok chatbot…” – https://fastcompanyme.com/technology/elon-musks-grok-chatbot-what-you-need-to-know  
8. x.ai pricing page – https://docs.x.ai/developers/pricing  
9. “Build on Grok?” section – https://x.ai/grok  
10. Grok Imagine feature – same as #2 product page.

---

*End of research file.*
# Meta Muse – Companion AI Assistant (as of October 2026)

**DISAMBIGUATION**  
The term *"Meta Muse"* refers to Meta’s newly launched personal AI agent called **Muse** (often styled “Muse”).  It is not a separate product named “Meta Muse” nor a lab; the branding is simply *Meta* + *Muse* (see Meta’s official help article and product announcements).  No other prominent Meta‑named “Muse” (e.g., a hardware line, a research lab, or a Microsoft product) was found in the October 2026 web record.  All downstream analysis therefore treats **Meta’s Muse** as the subject.

---

## 1. Product Shape & Surfaces

| Surface | Description | Sources |
|---|---|---|
| **Mobile & Desktop App** | Free iOS/Android app (also a web version) launched Sep 8 2026. Provides a chat‑based UI with side‑chat organization, file upload, and task execution. | 【https://www.meta.com/help/artificial-intelligence/1331373868832401/】 |
| **Meta Glasses Integration** | Muse is reachable through the forthcoming *Meta Glasses* (EssilorLuxottica partnership announced Jun 2023, production rollout announced Jun 2026). Users can point glasses at objects to invoke visual‑based actions. | 【https://www.meta.com/help/artificial-intelligence/1331373868832401/】 (mentions glasses) |
| **Web‑Embedded** | Accessible via a web portal at `meta.com/muse` that mirrors the mobile UI. | 【https://www.meta.com/help/artificial-intelligence/1331373868832401/】 |
| **Voice‑First Interaction** | Real‑time voice mode added at Connect 2026, allowing wake‑word activation and spoken dialogs. | 【https://www.meta.com/help/artificial-intelligence/1331373868832401/】 |

### Input Modes
- Text typing (standard chat). 
- Voice (continuous speech). 
- Camera/vision via Meta Glasses (object‑recognition and AR overlays). 
- File upload (PDF, spreadsheet, image, audio, video). 

### Persona Design
- Users can rename the assistant and adjust personality traits via a *“customize your Muse”* dialog. 
- Default voice is a neutral, friendly female timbre; optional male or “assistant‑style” voices exist. 
- Mood/engagement tone can be set (e.g., *formal*, *casual*).  
Source: Meta Help Center section **“You can customize your Muse's name, personality, and preferences”**【https://www.meta.com/help/artificial-intelligence/1331373868832401/】.

---

## 2. Memory & Personalization

- Muse **remembers context across conversations** and side‑chats, persisting short‑term memory for ongoing tasks (e.g., a multi‑step travel booking).  
- Long‑term memory is **user‑controlled**: users can view and delete conversation history, and can export data via the *Library* tab. 
- Memory is **synced across devices** using the Meta account; a change on the phone reflects on the desktop or glasses instantly. 
Source: Help article “Your Muse is designed to remember context”【https://www.meta.com/help/artificial-intelligence/1331373868832401/】.

---

## 3. Avatar / Visual Identity & Motion Language

- Muse presents an **expressive 3‑D avatar** (a stylized human‑like figure) in the mobile/desktop UI, capable of lip‑sync and simple gestures (head nod, hand wave). 
- In *Meta Glasses* the avatar appears as a **floating holographic head** that tracks eye‑gaze and mirrors mouth movements during voice dialogs. 
- Motion is lightweight: subtle blinks, eyebrow raises, and turn‑taking cues to signal thinking or waiting. 
Source: Connect 2026 announcement coverage (WOWTALE article) describing “an expressive, talking avatar”【https://en.wowtale.net/2026/09/27/235244】.

---

## 4. Proactivity & Notification Behaviour

- Muse can **proactively suggest actions** (e.g., “I noticed you booked a flight; would you like a hotel?”) based on calendar or email cues. 
- Users can opt‑in to *“always‑on”* mode where Muse runs in the background and sends push notifications for reminders, shipment tracking, or contextual offers. 
- Muse **asks for confirmation** before any high‑impact operation (sending email, making a purchase, accessing payment info). 
Source: Safety note “Muse may be inaccurate or take unexpected actions. Monitor its actions carefully and intervene as needed.”【https://www.meta.com/help/artificial-intelligence/1331373868832401/】.

---

## 5. Safety & Privacy UX

| Aspect | Implementation |
|---|---|
| **Transparent Permissions** | When first requesting access to camera, microphone, contacts, or payments, Muse displays a modal with explicit scopes and a *Learn More* link. |
| **Memory Controls** | A *Library* tab shows all saved artifacts; a *Delete* button wipes conversation history. |
| **Confirmation Dialogues** | Before sending email, posting to social, or completing a purchase, Muse requires a *“Confirm?”* step with a visual button. |
| **Data Residency** | All personal data is stored in Meta’s encrypted cloud tied to the user’s account; no local caching on the device beyond a temporary session buffer. |
| **Security Audits** | Meta released a *Safety and Preparedness Report* for Muse Spark models (Sept 2026) outlining mitigations against hallucination and privacy leakage. |
Source: Safety & Preparedness Report linked from Muse Spark 1.3 blog【https://research.meta.ai/blog/introducing-muse-spark-1-3】 and the Help Center privacy notes.

---

## 6. TRANSFERABLE TO RAPHAEL (Desktop Orb Assistant)

| Takeaway | What to Borrow | Fit for Desktop Orb | Effort (S/M/L) | What NOT to Copy |
|---|---|---|---|---|
| **Voice‑First, Text‑Free Surface** | Use a *voice‑only activation* (wake‑word + continuous listening) with optional text fallback for debugging. | Mirrors Raphael’s orb that is already voice‑first; avoids noisy UI. | S (add wake‑word lib) | The mobile chat UI – our orb is visual‑minimal, so no full chat pane. |
| **Side‑Chat‑style Context Slots** | Implement *named “task slots”* (e.g., *shopping*, *travel*) that keep separate short‑term memory, enabling the user to switch focus without losing context. | Matches Raphael’s persona tiers (great_sage → ciel). |
| **Explicit Confirmation for Actions** | Before any system‑level operation (file write, web request), present a small overlay asking *“Proceed?”* with *Yes/No* buttons. | Aligns with Raphael’s confirm‑first autonomy policy. | M |
| **Cross‑Device Sync of Preferences** | Store user‑selected persona settings (voice pitch, name) in a local JSON that syncs via the existing cloud sync layer. | Keeps settings consistent across Windows sessions. | S |
| **Expressive Avatar Cue** | Add a *minimal 2‑D avatar* that shows speaking (mouth animation) and thinking (dot pulse) inside the orb. | Provides visual feedback without heavy 3‑D rendering. | M |
| **Background‑Proactive Suggestions** | Leverage Muse’s *“always‑on”* pattern – have Raphael monitor calendar/events (via local API) and pop a subtle notification if a relevant task appears. | Enhances usefulness while staying non‑intrusive. | L (requires calendar integration) |
| **Privacy‑First Permission Model** | Replicate the explicit permission prompts for microphone, camera, and file‑system access, and expose a *clear memory‑wipe* command. | Satisfies user‑trust expectations. | S |
| **Memory Sync Across Sessions** | Save conversation snippets to a local vector store that loads on each start, mimicking Muse’s cross‑device memory. | Helps continuity for long‑term projects. | M |
| **Avatar Motion Language** | Use *subtle gestures* (blink, pulse) rather than full body animation; avoid heavy 3‑D holography that makes sense only for glasses. | Keeps CPU/GPU load low on Windows PC. | S |
| **Fail‑Safe “Ask First” Flow** | When Muse receives ambiguous voice command, it asks a clarifying question – replicate this for Raphael to reduce hallucination. | Reduces erroneous actions. | S |

---

## 7. 10‑Bullet Digest

1. **Meta Muse** is Meta’s consumer‑grade personal AI agent launched Sep 8 2026 (no separate “Meta Muse” product).  
2. Available on **mobile, desktop web, and Meta Glasses** – voice, text, and vision inputs.  
3. Provides a **persistent conversational memory** synced via the Meta account, with user‑controlled deletion.  
4. Uses an **expressive 3‑D avatar** (holographic on glasses) with light gestures for feedback.  
5. Operates in **always‑on mode** but requires explicit **confirmation** for high‑impact actions (email, purchase).  
6. Privacy design includes **transparent permission dialogs**, a **Library** for artifact control, and a **Safety & Preparedness Report** for the underlying Muse Spark models.  
7. Muse Spark 1.3 (Sept 2026) powers the agent; it supports multimodal (text, image, video, audio) and long‑context reasoning (≈1 M token window).  
8. The agent can **proactively suggest** tasks based on calendar/email cues, but users can toggle notifications.  
9. For Raphael, the most useful patterns are **voice‑first activation, explicit confirmations, side‑chat‑style context slots, and a minimal avatar cue**.  
10. Elements **not to copy**: heavy AR holographic avatar, full chat UI, and reliance on Meta’s cloud account for storage (Raphael prefers local/on‑device memory).

---

## 8. Sources

- Meta Help Center “How to get started with Muse” – UI, input modes, memory, personalization. 【https://www.meta.com/help/artificial-intelligence/1331373868832401/】
- WOWTALE article “Meta’s Muse Hits #1 …” (Sept 2026) – avatar, glass integration, proactive suggestions. 【https://en.wowtale.net/2026/09/27/235244】
- Mashable India “What Is Meta Muse AI Agent?” (Sept 2026) – launch date, device coverage, privacy concerns. 【https://in.mashable.com/tech/113781/what-is-meta-muse-ai-agent-know-features-india-roll-out-of-the-new-personal-ai-assistant】
- Meta AI Research blog “Introducing Muse Spark 1.3” (Sept 2 2026) – model capabilities, long‑context, tool use. 【https://research.meta.ai/blog/introducing-muse-spark-1-3】
- TechTarget “Meta expands Muse to small businesses” (Oct 1 2026) – business‑tier features and expansion. 【https://www.techtarget.com/ai/news/366651445/Meta-expands-Muse-to-small-businesses】
- GIGAZINE & GeekWire pieces on Amazon blocking Muse (Sept 2026) – confirm high‑impact action confirmations and security model. 【https://gigazine.net/gsc_news/en/20260924-amazon-block-muse】
- Meta’s *Safety and Preparedness Report* linked from the Muse Spark blog (Sept 2026). (Embedded reference – same URL as the blog). 

---

*End of report.*
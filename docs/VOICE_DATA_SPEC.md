# VOICE_DATA_SPEC.md — Raphael voice reference requirements (researched 2026-10-05)

Verified against current Fish-Speech docs (fish.audio + github.com/fishaudio/fish-speech).

**STATUS (2026-10-05):** v1 voice shipped with a SYNTHESIZED reference instead of anime clips — `scripts/win/make-ref-voice.ps1` (Microsoft Zira SAPI, 22 s @ 24 kHz → `assets/raphael_reference.wav` + `.txt` transcript). The clip-assembly path below remains the fidelity upgrade path (same format/transcript rules apply).

## Method
Zero-shot cloning only for v1 (no fine-tune): reference audio + EXACT transcript.
- Official sweet spot: **10–30 s** clean speech; 1–2 min improves fidelity
- Open-source fish-speech `--reference-audio` path: **max 90 s total**
- Target: **60–90 s** assembled → `assets/raphael_reference.wav` + `assets/raphael_reference.txt`

## Language decision: ENGLISH (recommended)
- EN dub VA: **Mallorie Rodak** (Great Sage) — natural English, all-day use, no tech-term mispronunciation risk
- JP VA: Megumi Toyoguchi — authentic but JP prosody on English; optional later "alt voice profile" (second reference file, not a rebuild)
- Raphael speaks English to the user; config `voice_personality.gender: female` (she/her)

## Variations required (priority order)
1. Short acknowledgments 3-5 s: "Notice." / "Affirmative." / "There is no problem." / "Understood. As you wish."
2. Medium analytical lines 4-8 s
3. 2-3 longer narrations (2-4 sentences) for prosody flow
4. Numbers/names if naturally occurring
5. EXCLUDE: screams, laughter, emotional spikes, heavy BGM/SFX lines (character = flat/calm; bad samples destabilize the clone)

## Source moments (quote-db verified; timestamps = JP track — match by quote text for EN dub)
| Ep | JP timestamps | Lines |
|---|---|---|
| 6 | 03:26, 03:28, 08:23, 08:43, 16:57-58 | "There is no problem." · "Affirmative. It is ineffective on Master…" · "Notice. That will not be necessary." · "I have detected the intent to kill from some distance away." |
| 10 | 06:21, 07:30, 09:51, 14:59, 15:58 | "Affirmative…" · "Notice." · analysis lines |
| 11 | 08:51, 13:29, 22:41 | "…the special constitution known as Anti-skill." · "I simply did not wish to make you feel anxious." · "Understood. As you wish." |
| 12 | 10:17, 17:36 | Legend-grade sword line · Magitrain elemental core line |
| 13 | 13:17-32, 16:07, 19:58 | Ifrit analysis · "Proceeding to creation of soul vessel." · "The greater spirit Ifrit has evolved into a Flame Lord." |

(Ep numbering per the Raphael quote entries of the latest season — match by QUOTE TEXT in the user's copy.)

## Format requirements
- WAV preferred (or best source; we convert), mono, resampled to 24 kHz (Fish-Speech handles 16/24/44.1/48)
- Dialogue only: no BGM/SFX/reverb/other speakers/overlap. Dirty clips → demucs vocal separation (voice-phase venv, part of planned torch install)
- Exact transcript per segment incl. punctuation (drives prosody). SRT subtitle files welcome → auto-extract + time-align
- User delivers raw clips + SRTs at a path on C:; orchestrator assembles/cleans/verifies during voice phase

## Fallback
If reference missing/wrong-language at runtime: default female voice + spoken notice (brief §5).

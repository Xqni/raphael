"""brain/voice — Raphael's voice stack (voice-dev, ARCHITECTURE §2).

Public API for the agent loop (brain/loop.py / brain/ws.py):

  transcribe(pcm_bytes) -> str            # STT: PCM s16le 16k mono -> text
  transcribe_result(...)  -> TranscribeResult  # + lang/rtf/segments
  speak(text, job=..., cancel=...)        # async iterator of speak frame dicts
  speak_frame(ev) / speak_payload(ev)     # split JSON frame vs raw audio bytes
  encode_binary_frame(2, seq, payload)    # PROTOCOL §6 binary wrapper
  stt_final_frame / error_frame           # PROTOCOL §3 JSON frames
  WakeGate / PTTGate / InterruptController  # wake word, PTT, barge-in
  get_voice()                             # VoiceStack singleton (cfg-wired)

Wire-up contract for loop.py (full example in brain/voice/README.md):
  - on audio_start{reason}: get_voice().wake.gate(transcript, reason)
    -> kind='wake'|'ptt' + command text; kind='none' = ignore
  - on audio_end: await asyncio.to_thread(voice.transcribe, pcm) ->
    broadcast stt_final_frame(...) ; on VoiceSTTError -> error_frame(code)
  - on barge-in (user speaks while Raphael speaks): voice.interrupts.interrupt()
    THEN submit the new command (speech stops immediately, control returns)
  - narrate(): async for ev in voice.speak(text, job=jid, cancel=ev):
      hub.broadcast(speak_frame(ev), roles={'body'})
      if ev['event']=='chunk': hub.send_binary(encode_binary_frame(2, ev['seq'],
                                                                  speak_payload(ev)))
"""
from __future__ import annotations

from typing import Any, AsyncIterator, Dict, Optional

from .activation import (ActivationGate, GateDecision, PlaybackEchoRegistry,
                         get_activation, get_playback_echoes,
                         reset_activation)
from .confirmation import (VoiceAnswer, parse_voice_answer,
                           to_confirm_answer, voice_confirmation_answer)
from .config import REPO_ROOT, VoiceConfig, load_voice_config
from .stt import (STT_SAMPLE_RATE, CloudTranscriber, Segment,
                  SttEngine, TranscribeResult, Transcriber, VoiceSTTError,
                  get_stt, get_transcriber, is_effectively_silent,
                  pcm_to_wav_bytes, reset_stt, transcribe,
                  transcribe_result)
from .tts import (TTS_SAMPLE_RATE_DEFAULT, FishSpeechServer, PhraseCache,
                  TTSEngine, TTSError, encode_binary_frame, error_frame,
                  get_tts, speak as _speak_singleton, speak_frame,
                  speak_payload, split_sentences, stt_final_frame)
from .wake import (InterruptController, PTTGate, WakeGate, WakeMatch,
                   get_interrupts, get_ptt_gate, get_wake_gate, normalize_text)


class VoiceStack:
    """Everything loop.py needs, wired from config.yaml → voice:.

    `self.wake` is the ActivationGate: its `.gate(transcript, reason)` is the
    phonetic WakeGate PLUS playback-echo rejection (so ws.py's existing
    `voice.wake.gate(...)` call gets self-trigger protection for free), and
    `.should_transcribe(pcm, reason)` is the pre-STT cloud gate.
    """

    def __init__(self, cfg: Optional[VoiceConfig] = None):
        self.cfg = cfg or load_voice_config()
        self.stt = SttEngine(self.cfg)     # cloud (groq) or local per profile
        self.tts = TTSEngine(self.cfg)
        self.wake = ActivationGate(self.cfg)
        self.interrupts = get_interrupts()
        self.ptt = get_ptt_gate()

    # -- STT ----------------------------------------------------------------
    def should_transcribe(self, pcm: bytes, reason: Optional[str] = None,
                          sample_rate: int = STT_SAMPLE_RATE) -> GateDecision:
        """Pre-STT cloud gate (Wave 2 task 2). reason: 'ptt'|'wake'|None."""
        return self.wake.should_transcribe(pcm, reason=reason,
                                           sample_rate=sample_rate)

    def transcribe(self, pcm: bytes, sample_rate: int = STT_SAMPLE_RATE,
                   reason: Optional[str] = None) -> str:
        return self.transcribe_result(pcm, sample_rate=sample_rate,
                                      reason=reason).text

    def transcribe_result(self, pcm: bytes, sample_rate: int = STT_SAMPLE_RATE,
                          reason: Optional[str] = None) -> TranscribeResult:
        sr = int(sample_rate or STT_SAMPLE_RATE)
        if not self.should_transcribe(pcm, reason=reason, sample_rate=sr):
            # gated locally: no provider call, graceful empty transcript
            return TranscribeResult(text="", lang=None, rtf=0.0,
                                    duration_s=len(pcm) / 2.0 / sr if pcm else 0.0)
        return self.stt.transcribe(pcm, sample_rate=sr)

    # -- TTS ----------------------------------------------------------------
    async def speak(self, text: str, *, job: Optional[str] = None,
                    cancel: Optional[Any] = None,
                    force_fallback: bool = False,
                    ) -> AsyncIterator[Dict[str, Any]]:
        async for ev in self.tts.speak(text, job=job, cancel=cancel,
                                       force_fallback=force_fallback):
            yield ev

    # -- lifecycle ----------------------------------------------------------
    async def warmup(self) -> None:
        """Resume hook (ARCHITECTURE §6): re-warm TTS; STT loads lazily."""
        await self.tts.warmup()

    def shutdown(self) -> None:
        self.tts.shutdown()


_stack: Optional[VoiceStack] = None


def get_voice(cfg: Optional[VoiceConfig] = None) -> VoiceStack:
    global _stack
    if _stack is None:
        _stack = VoiceStack(cfg)
    return _stack


async def speak(text: str, **kwargs: Any) -> AsyncIterator[Dict[str, Any]]:
    """Module-level convenience — same events as VoiceStack.speak."""
    async for ev in get_voice().speak(text, **kwargs):
        yield ev


__all__ = [
    "REPO_ROOT", "VoiceConfig", "load_voice_config",
    "STT_SAMPLE_RATE", "TTS_SAMPLE_RATE_DEFAULT",
    "VoiceSTTError", "Transcriber", "TranscribeResult", "Segment",
    "SttEngine", "CloudTranscriber", "get_stt", "reset_stt",
    "is_effectively_silent", "pcm_to_wav_bytes",
    "ActivationGate", "GateDecision", "PlaybackEchoRegistry",
    "get_activation", "get_playback_echoes", "reset_activation",
    "VoiceAnswer", "parse_voice_answer", "to_confirm_answer",
    "voice_confirmation_answer",
    "transcribe", "transcribe_result", "get_transcriber",
    "TTSError", "TTSEngine", "FishSpeechServer", "PhraseCache",
    "speak", "speak_frame", "speak_payload", "encode_binary_frame",
    "stt_final_frame", "error_frame", "split_sentences", "get_tts",
    "WakeGate", "WakeMatch", "PTTGate", "InterruptController",
    "normalize_text", "get_wake_gate", "get_interrupts", "get_ptt_gate",
    "VoiceStack", "get_voice",
]

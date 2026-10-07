"""Class-level TTS/STT mocks — AGENT_RULES §5: "Never spawn Fish TTS (port
8777 reserved for main; voice tests mock TTS)" and cloud_temp has no local
models (no faster-whisper).

install(monkeypatch) patches:
- TTSEngine.warmup        -> no-op (the REAL warmup SPAWNS the fish server)
- TTSEngine.speak         -> deterministic start/chunk/end stream, 50 ms of
                             silence, recorded into SPEAK_CALLS
- FishSpeechServer.ensure_started -> hard-fail (defense in depth: even an
                             unpatched speak path can never reach spawn())
- VoiceStack.transcribe_result -> records the PCM handed to it (proves binary
                             frame parsing) and returns a canned transcript

wake gate / InterruptController stay REAL (pure logic, no hardware).
monkeypatch reverts every patch at fixture teardown.
"""
from __future__ import annotations

from typing import Any, Dict, List

# per-test records (cleared by install())
SPEAK_CALLS: List[Dict[str, Any]] = []
STT_CALLS: List[bytes] = []
CANNED_TRANSCRIPT = 'mock transcript'


def install(monkeypatch) -> None:
    from brain.voice import TranscribeResult, VoiceStack
    from brain.voice.tts import TTSEngine, FishSpeechServer, TTSError

    SPEAK_CALLS.clear()
    STT_CALLS.clear()

    async def _warmup(self) -> None:
        return None

    async def _ensure_started(self, *args, **kwargs) -> None:
        raise TTSError('E_LOCAL_DOWN', 'qa-security: TTS mocked in tests')

    async def _speak(self, text, *, job=None, cancel=None,
                     force_fallback=False, **kwargs):
        # **kwargs absorbs new voice-lane params (Wave 5 added
        # max_sentences — an unknown kwarg here silently killed speech)
        SPEAK_CALLS.append({'text': text, 'job': job})
        rate = int(getattr(self.cfg, 'tts_sample_rate', 24000) or 24000)
        yield {'type': 'speak', 'v': 1, 'job': job, 'seq': 0, 'event': 'start',
               'sample_rate': rate, 'text': text, 'cached': False,
               'engine': 'mock'}
        pcm = b'\x00\x00' * (rate // 20)          # 50 ms of silence
        yield {'type': 'speak', 'v': 1, 'job': job, 'seq': 1, 'event': 'chunk',
               'sample_rate': rate, 'amplitude': 0.0, 'cached': False,
               'engine': 'mock', 'payload': pcm}
        yield {'type': 'speak', 'v': 1, 'job': job, 'seq': 2, 'event': 'end',
               'sample_rate': rate, 'cached': False, 'engine': 'mock'}

    def _transcribe_result(self, pcm, sample_rate=None, **kwargs) -> Any:
        STT_CALLS.append(bytes(pcm))
        dur = len(pcm) / 32000.0                  # s16le 16k mono
        return TranscribeResult(text=CANNED_TRANSCRIPT, lang='en', rtf=0.05,
                                duration_s=dur)

    monkeypatch.setattr(TTSEngine, 'warmup', _warmup)
    monkeypatch.setattr(TTSEngine, 'speak', _speak)
    monkeypatch.setattr(FishSpeechServer, 'ensure_started', _ensure_started)
    monkeypatch.setattr(VoiceStack, 'transcribe_result', _transcribe_result)

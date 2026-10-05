"""brain/voice/stt.py — faster-whisper speech-to-text (voice-dev).

Contract:
  transcribe(pcm_bytes, sample_rate=16000) -> str
    - pcm_bytes: raw PCM s16le mono (PROTOCOL §6 kind=1 payload)
    - returns '' gracefully for silence/empty audio
    - raises VoiceSTTError (with .code = PROTOCOL §10 code) when the model
      cannot be loaded — never crashes the caller's loop

VAD: faster-whisper's built-in silero VAD (vad_filter=True) gives clean
segment boundaries at the utterance level (audio_start..audio_end).

Lazy model load: the WhisperModel is constructed on first use only, so
brain startup never blocks on STT weights.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from .config import VoiceConfig, load_voice_config

STT_SAMPLE_RATE = 16000  # PROTOCOL §3 audio_start: sample_rate 16000, mono, pcm_s16le


class VoiceSTTError(Exception):
    """Typed STT failure — loop.py maps .code into a PROTOCOL error frame."""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass
class Segment:
    start: float
    end: float
    text: str


@dataclass
class TranscribeResult:
    text: str
    lang: Optional[str] = None
    rtf: float = 0.0            # real-time factor (transcribe_time / audio_duration)
    duration_s: float = 0.0
    segments: List[Segment] = field(default_factory=list)


def pcm_s16le_to_float32(pcm: bytes) -> np.ndarray:
    """Raw s16le bytes -> float32 mono array in [-1, 1]."""
    if not pcm:
        return np.zeros(0, dtype=np.float32)
    # drop a trailing odd byte (partial sample) rather than crash
    usable = len(pcm) - (len(pcm) % 2)
    if usable == 0:
        return np.zeros(0, dtype=np.float32)
    ints = np.frombuffer(pcm[:usable], dtype="<i2")
    return ints.astype(np.float32) / 32768.0


def _preload_cuda_libs() -> bool:
    """ctranslate2 dlopens libcublas.so.12 etc. at model-load time; the libs
    ship inside brain/.venv as nvidia pip packages (torch cu126 deps) but
    glibc's dlopen cache captured LD_LIBRARY_PATH at process start. Preloading
    with RTLD_GLOBAL registers the sonames so ctranslate2's dlopen resolves."""
    import ctypes
    import glob

    here = Path(__file__).resolve()
    venv = here.parents[1] / ".venv"          # brain/voice/stt.py -> brain/.venv
    patterns = [
        str(venv / "lib" / "python3.12" / "site-packages" / "nvidia" / "*" / "lib"
            / "libcudart.so.12"),
        str(venv / "lib" / "python3.12" / "site-packages" / "nvidia" / "*" / "lib"
            / "libcublasLt.so.12"),
        str(venv / "lib" / "python3.12" / "site-packages" / "nvidia" / "*" / "lib"
            / "libcublas.so.12"),
        str(venv / "lib" / "python3.12" / "site-packages" / "nvidia" / "*" / "lib"
            / "libcudnn.so.9"),
    ]
    loaded = 0
    for pat in patterns:
        for lib in sorted(glob.glob(pat)):
            try:
                ctypes.CDLL(lib, mode=ctypes.RTLD_GLOBAL)
                loaded += 1
            except OSError:
                continue
    return loaded > 0


class Transcriber:
    """faster-whisper wrapper: lazy load, device auto per config, graceful."""

    def __init__(self, cfg: Optional[VoiceConfig] = None):
        self.cfg = cfg or load_voice_config()
        self._model = None
        self._model_name = self.cfg.stt_model
        self._load_error: Optional[VoiceSTTError] = None
        self.load_ms: Optional[float] = None

    # ---- model lifecycle --------------------------------------------------
    def _resolve_device(self) -> tuple[str, str]:
        """Returns (device, compute_type). auto -> cuda+float16 when available."""
        want = (self.cfg.stt_device or "auto").lower()
        compute = (self.cfg.stt_compute or "auto").lower()
        device = want
        if want == "auto":
            try:
                import ctranslate2

                device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
            except Exception:  # noqa: BLE001 — ctranslate2 without CUDA build
                device = "cpu"
        if compute == "auto":
            compute = "float16" if device == "cuda" else "int8"
        return device, compute

    def load(self) -> None:
        """Construct the WhisperModel (idempotent). Raises VoiceSTTError."""
        if self._model is not None:
            return
        if self._load_error is not None:
            raise self._load_error
        t0 = time.perf_counter()
        try:
            from faster_whisper import WhisperModel
        except ImportError as e:
            self._load_error = VoiceSTTError(
                "E_LOCAL_DOWN", f"faster-whisper not installed in this venv: {e}")
            raise self._load_error from e
        device, compute = self._resolve_device()
        if device == "cuda":
            _preload_cuda_libs()          # libcublas for ctranslate2 (see fn)
        try:
            # model name (e.g. "small") resolves via HF cache; downloads on
            # first ever use when online (brain keeps weights cached after).
            self._model = WhisperModel(
                self.cfg.stt_model, device=device, compute_type=compute,
                download_root=None,  # default HF cache
            )
        except Exception as e:  # noqa: BLE001 — any load failure is typed
            msg = str(e)
            code = "E_OFFLINE" if ("offline" in msg.lower()
                                   or "connection" in msg.lower()
                                   or "huggingface" in msg.lower()) else "E_INTERNAL"
            self._load_error = VoiceSTTError(
                code, f"whisper model '{self.cfg.stt_model}' unavailable: {msg[:300]}")
            raise self._load_error from e
        self.load_ms = (time.perf_counter() - t0) * 1000.0

    def unload(self) -> None:
        """Free model memory (E_LOCAL_OOM recovery path — ARCHITECTURE §4)."""
        self._model = None
        self._load_error = None

    # ---- transcription ----------------------------------------------------
    def transcribe(self, pcm: bytes, sample_rate: int = STT_SAMPLE_RATE,
                   language: Optional[str] = None) -> TranscribeResult:
        """PCM s16le mono bytes -> TranscribeResult. '' for silence/empty.

        Raises VoiceSTTError only for model-load failures; audio problems
        degrade to an empty transcript (graceful).
        """
        audio = pcm_s16le_to_float32(pcm)
        duration = len(audio) / float(sample_rate or STT_SAMPLE_RATE)
        if len(audio) == 0:
            return TranscribeResult(text="", lang=None, rtf=0.0, duration_s=0.0)
        self.load()  # raises VoiceSTTError when weights/stack are unavailable
        assert self._model is not None
        lang = language if language is not None else self.cfg.stt_language
        t0 = time.perf_counter()
        try:
            segments_iter, info = self._model.transcribe(
                audio,
                language=lang,
                vad_filter=True,                      # VAD-cleaned boundaries
                vad_parameters=dict(min_silence_duration_ms=500),
                beam_size=5,
                condition_on_previous_text=False,
            )
            segments: List[Segment] = []
            parts: List[str] = []
            for s in segments_iter:
                text = (s.text or "").strip()
                if text:
                    segments.append(Segment(start=float(s.start),
                                            end=float(s.end), text=text))
                    parts.append(text)
        except Exception as e:  # noqa: BLE001 — inference failure, not crash
            raise VoiceSTTError("E_INTERNAL", f"transcription failed: {e}") from e
        elapsed = time.perf_counter() - t0
        rtf = (elapsed / duration) if duration > 0 else 0.0
        return TranscribeResult(
            text=" ".join(parts).strip(),
            lang=getattr(info, "language", None),
            rtf=rtf,
            duration_s=duration,
            segments=segments,
        )


# ---- module-level singleton (loop.py integration point) --------------------
_transcriber: Optional[Transcriber] = None


def get_transcriber(cfg: Optional[VoiceConfig] = None) -> Transcriber:
    global _transcriber
    if _transcriber is None:
        _transcriber = Transcriber(cfg)
    return _transcriber


def transcribe(pcm: bytes, sample_rate: int = STT_SAMPLE_RATE,
               cfg: Optional[VoiceConfig] = None) -> str:
    """Public API (ARCHITECTURE §2): PCM s16le 16k mono bytes -> text.

    Silence/empty PCM -> ''. Model unavailable -> VoiceSTTError(code, detail).
    Blocking: call via asyncio.to_thread from the agent loop.
    """
    return get_transcriber(cfg).transcribe(pcm, sample_rate=sample_rate).text


def transcribe_result(pcm: bytes, sample_rate: int = STT_SAMPLE_RATE,
                      cfg: Optional[VoiceConfig] = None) -> TranscribeResult:
    """Like transcribe() but returns lang/rtf/segments (stt_final frame data)."""
    return get_transcriber(cfg).transcribe(pcm, sample_rate=sample_rate)

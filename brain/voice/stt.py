"""brain/voice/stt.py — speech-to-text: cloud (Groq Whisper via router) or local
faster-whisper (voice-dev).

Contract:
  transcribe(pcm_bytes, sample_rate=16000) -> str
  transcribe_result(...) -> TranscribeResult
    - pcm_bytes: raw PCM s16le mono (PROTOCOL §6 kind=1 payload)
    - returns '' gracefully for silence/empty audio
    - raises VoiceSTTError (with .code = PROTOCOL §10 code) when the engine
      cannot be reached — never crashes the caller's loop

Engine selection (config voice.stt_engine + profile, docs/WAVES.md):
  profile cloud_temp -> ALWAYS `groq`: router.transcribe() (Groq Whisper).
                        faster-whisper is never imported or loaded here.
  profile local      -> voice.stt_engine selects `local` (faster-whisper) or
                        `groq`. The local code path stays in the repo, gated.

Silence/short audio never leaves the machine: a pure-silence segment is
answered locally with '' (no cloud call).

VAD: utterance segmentation happens BEFORE this module (body/win/audio_in.py
VadSegmenter) — one segment = one transcribe call.
"""
from __future__ import annotations

import asyncio
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from .config import VoiceConfig, load_voice_config

STT_SAMPLE_RATE = 16000  # PROTOCOL §3 audio_start: sample_rate 16000, mono, pcm_s16le

# Local silence short-circuit (also keeps silence off the cloud): a segment
# shorter than MIN or quieter than QUIET_RMS (int16 RMS units — the body's
# VAD opens at ~80+) transcribes to '' without any engine call.
MIN_TRANSCRIBE_S = 0.15
QUIET_RMS = 40.0


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


# ---- cloud STT (router.transcribe — Groq Whisper, profile cloud_temp) ------
def pcm_to_wav_bytes(pcm: bytes, sample_rate: int) -> bytes:
    """Raw s16le mono PCM -> standard WAV container bytes.

    Groq Whisper's /audio/transcriptions takes a file (wav/webm/ogg/...), not
    bare PCM — wrapping here keeps the wire format self-describing.
    """
    import io

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)                     # s16le
        w.setframerate(int(sample_rate))
        w.writeframes(pcm or b"")
    return buf.getvalue()


def _rms_i16(pcm: bytes) -> float:
    usable = len(pcm) - (len(pcm) % 2)
    if usable == 0:
        return 0.0
    x = np.frombuffer(pcm[:usable], dtype="<i2").astype(np.float64)
    return float(np.sqrt(np.mean(x * x))) if x.size else 0.0


def is_effectively_silent(pcm: bytes, sample_rate: int) -> bool:
    """True when the segment cannot contain speech — answered locally with '',
    never sent to a provider (privacy + rate-limit hygiene)."""
    if not pcm:
        return True
    duration = len(pcm) / 2.0 / float(sample_rate or STT_SAMPLE_RATE)
    if duration < MIN_TRANSCRIBE_S:
        return True
    return _rms_i16(pcm) < QUIET_RMS


def _map_router_error(exc: BaseException) -> VoiceSTTError:
    """Any provider/router failure -> VoiceSTTError with a PROTOCOL §10 code."""
    if isinstance(exc, VoiceSTTError):
        return exc
    code = getattr(exc, "code", None)
    if isinstance(code, str) and code.startswith("E_"):
        return VoiceSTTError(code, str(getattr(exc, "detail", None) or exc))
    msg = str(exc)
    low = msg.lower()
    if isinstance(exc, TimeoutError):
        return VoiceSTTError("E_TIMEOUT", f"transcribe timed out: {msg[:200]}")
    if isinstance(exc, (ConnectionError, OSError)) or any(
            k in low for k in ("offline", "connection", "network",
                               "name or service", "no route", "unreachable",
                               "temporary failure")):
        return VoiceSTTError("E_OFFLINE", f"transcribe unreachable: {msg[:200]}")
    if "401" in msg or "403" in msg or "auth" in low or "api key" in low:
        return VoiceSTTError("E_PROVIDER_AUTH", f"transcribe auth: {msg[:200]}")
    if "429" in msg or "rate" in low:
        return VoiceSTTError("E_PROVIDER_429", f"transcribe rate-limited: {msg[:200]}")
    return VoiceSTTError("E_INTERNAL", f"transcribe failed: {msg[:200]}")


# PROTOCOL §10: clients surface error detail as subtitle text ONLY for this
# code set — everything else is fatal/internal and must not leak to screen.
SUBTITLE_CODES = frozenset({
    "E_LOCK_BUSY", "E_TIMEOUT", "E_CONFIRM_TIMEOUT", "E_PROVIDER_429",
    "E_LOCAL_OOM", "E_LOCAL_DOWN", "E_OFFLINE",
})


def stt_outage_subtitle(code: str, detail: str = "") -> Optional[str]:
    """Human notice for an STT outage (Wave 4: cloud gate fails -> a subtitle
    notice, never a silent drop of what the user just said).

    Returns a brief, secret-free subtitle for surfaceable PROTOCOL §10 codes,
    else None (fatal/internal codes show no raw detail). Suggested wire-up:
    brain/ws.py `_on_audio_end` except-branch broadcasts this as a `subtitle`
    frame next to error_frame() (request: voice__to__brain-core__
    stt-outage-subtitle).
    """
    if code not in SUBTITLE_CODES:
        return None
    return f"Voice input unavailable ({code}) — type it instead, or retry."


class CloudTranscriber:
    """Groq Whisper through the router facade (INTERFACES §a `transcribe`).

    Blocking by design: callers run it via asyncio.to_thread (brain/ws.py
    already does). Never touches faster-whisper — profile cloud_temp has no
    local models (WAVES.md global constraints).
    """

    def __init__(self, cfg: Optional[VoiceConfig] = None):
        self.cfg = cfg or load_voice_config()
        self.last_provider: Optional[str] = None
        self.calls = 0

    def _router_transcribe(self):
        # Lazy import: brain.router must be importable even in unit tests that
        # stub it; no provider HTTP happens at import time.
        import brain.router as router

        fn = getattr(router, "transcribe", None)
        if fn is None:
            raise VoiceSTTError(
                "E_INTERNAL",
                "router.transcribe() missing — router lane contract "
                "docs/INTERFACES §a not implemented yet")
        return fn

    def transcribe(self, pcm: bytes, sample_rate: int = STT_SAMPLE_RATE,
                   language: Optional[str] = None) -> TranscribeResult:
        sr = int(sample_rate or STT_SAMPLE_RATE)
        duration = len(pcm) / 2.0 / sr if pcm else 0.0
        if is_effectively_silent(pcm, sr):
            return TranscribeResult(text="", lang=None, rtf=0.0, duration_s=duration)
        audio = pcm_to_wav_bytes(pcm, sr)
        lang = language if language is not None else self.cfg.stt_language
        fn = self._router_transcribe()
        t0 = time.perf_counter()
        self.calls += 1
        try:
            res = fn(audio, language=lang)
            if asyncio.iscoroutine(res):
                # BUG H fix (live gate 2026-10-07): Router.transcribe is async;
                # this runs in brain/ws.py's asyncio.to_thread worker (no
                # running loop in this thread) — previously the coroutine was
                # never awaited, every wake transcript came back empty, and
                # voice input silently died after audio_end. Bridge it here.
                try:
                    asyncio.get_running_loop()
                except RuntimeError:
                    res = asyncio.run(res)
                else:
                    # don't leak the un-awaited coroutine (ResourceWarning)
                    close = getattr(res, "close", None)
                    if callable(close):
                        close()
                    raise VoiceSTTError(
                        "E_INTERNAL",
                        "async transcribe reached a running-loop thread — "
                        "callers must run SttEngine.transcribe via to_thread")
        except VoiceSTTError:
            raise
        except Exception as e:  # noqa: BLE001 — router error types vary by lane
            raise _map_router_error(e) from e
        elapsed = time.perf_counter() - t0
        if isinstance(res, dict):
            text = str(res.get("text") or "").strip()
            rtf = res.get("rtf")
            provider = res.get("provider")
        else:
            text = str(getattr(res, "text", "") or "").strip()
            rtf = getattr(res, "rtf", None)
            provider = getattr(res, "provider", None)
        self.last_provider = provider if isinstance(provider, str) else None
        try:
            rtf_val = float(rtf) if rtf is not None else (
                elapsed / duration if duration > 0 else 0.0)
        except (TypeError, ValueError):
            rtf_val = elapsed / duration if duration > 0 else 0.0
        return TranscribeResult(text=text, lang=None, rtf=rtf_val,
                                duration_s=duration)


# ---- engine dispatcher (what loop.py/ws.py actually call) ------------------
class SttEngine:
    """Chooses cloud vs local per config + profile, once per instance.

    profile cloud_temp -> CloudTranscriber only: faster-whisper is never
    constructed, imported or loaded (WAVES.md: no local models).
    """

    def __init__(self, cfg: Optional[VoiceConfig] = None):
        self.cfg = cfg or load_voice_config()
        self._cloud: Optional[CloudTranscriber] = None
        self._local: Optional[Transcriber] = None

    @property
    def kind(self) -> str:
        return self.cfg.effective_stt_engine

    @property
    def cloud(self) -> CloudTranscriber:
        if self._cloud is None:
            self._cloud = CloudTranscriber(self.cfg)
        return self._cloud

    @property
    def local(self) -> Transcriber:
        """Local faster-whisper — reachable ONLY when the profile allows it."""
        if not self.cfg.local_stt_enabled:
            raise VoiceSTTError(
                "E_LOCAL_DOWN",
                f"local STT disabled under profile '{self.cfg.profile}'")
        if self._local is None:
            self._local = Transcriber(self.cfg)
        return self._local

    def transcribe(self, pcm: bytes, sample_rate: int = STT_SAMPLE_RATE,
                   language: Optional[str] = None) -> TranscribeResult:
        if self.kind == "local":
            return self.local.transcribe(pcm, sample_rate=sample_rate,
                                         language=language)
        return self.cloud.transcribe(pcm, sample_rate=sample_rate,
                                     language=language)


# ---- module-level singleton (loop.py integration point) --------------------
_transcriber: Optional[SttEngine] = None


def get_stt(cfg: Optional[VoiceConfig] = None) -> SttEngine:
    global _transcriber
    if _transcriber is None:
        _transcriber = SttEngine(cfg)
    return _transcriber


def reset_stt() -> None:
    """Test hook: drop the singleton (config/instance changes take effect)."""
    global _transcriber
    _transcriber = None


def get_transcriber(cfg: Optional[VoiceConfig] = None) -> Transcriber:
    """LOCAL faster-whisper singleton (profile local / integration tests)."""
    global _local_transcriber
    if _local_transcriber is None:
        _local_transcriber = Transcriber(cfg)
    return _local_transcriber


_local_transcriber: Optional[Transcriber] = None


def transcribe(pcm: bytes, sample_rate: int = STT_SAMPLE_RATE,
               cfg: Optional[VoiceConfig] = None) -> str:
    """Public API (ARCHITECTURE §2): PCM s16le 16k mono bytes -> text.

    Silence/empty PCM -> '' (no provider call). Engine failure ->
    VoiceSTTError(code, detail). Blocking: call via asyncio.to_thread.
    """
    return get_stt(cfg).transcribe(pcm, sample_rate=sample_rate).text


def transcribe_result(pcm: bytes, sample_rate: int = STT_SAMPLE_RATE,
                      cfg: Optional[VoiceConfig] = None) -> TranscribeResult:
    """Like transcribe() but returns lang/rtf/segments (stt_final frame data)."""
    return get_stt(cfg).transcribe(pcm, sample_rate=sample_rate)

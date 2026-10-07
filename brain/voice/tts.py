"""brain/voice/tts.py — Fish-Speech TTS adapter + phrase cache + speak stream
(voice-dev). Emits PROTOCOL §3 `speak` frame dicts, sentence by sentence:
the FIRST sentence is synthesized and streamed while the rest still generates.

Engine resolution order for speak(text):
  1. PhraseCache hit      -> cached wav chunks (cached=True)
  2. Fish-Speech server   -> real synthesis via the isolated venv
                             (brain/voice/.venv-fish + vendor repo v1.5.0 +
                              brain/voice/models/fish-speech-1.5), resampled to
                              config voice.tts_sample_rate (24000)
  3. Degraded fallback    -> SUBTITLE-ONLY: no audio chunks, plus a ONE-TIME
                             `notice` on the end event so loop.py can subtitle
                             the truth ("TTS engine unavailable ...") instead
                             of the reply arriving as mysterious silence.

Reference voice: config voice.tts_voice (assets/raphael_reference.wav). When
the asset exists it is sent as an in-context reference (base64 JSON per
tools/schema.py ServeReferenceAudio) — until then Fish-Speech picks its own
timbre (addendum §10: fallback voice + spoken/subtitled notice).

Amplitude: per-chunk RMS of the real synthesized audio, gain 3.0, clamped
0..1 (PROTOCOL §8 — orb pulse). pitch_hz: rough zero-crossing estimate,
emitted only when energy + range gates pass (optional field, graceful).

Binary chunks (PROTOCOL §6 kind=2) are NOT sent by this module — loop.py
takes event['payload'] and wraps it with encode_binary_frame() after the
matching speak JSON frame.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import math
import os
import re
import signal
import struct
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

import httpx
import numpy as np

from .config import VoiceConfig, load_voice_config
from .activation import get_playback_echoes
from .wake import normalize_text

TTS_SAMPLE_RATE_DEFAULT = 24000
PROTOCOL_MAGIC = b"RAPH"
_BINARY_KIND_TTS = 2          # brain->body PCM chunk (PROTOCOL §6)

_SENT_SPLIT_RE = re.compile(r"(?<=[.!?。！？;:])\s+")
_LOG_DIR = Path(__file__).resolve().parent / "logs"


class TTSError(Exception):
    """Typed TTS failure — loop.py maps .code into a PROTOCOL error frame."""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


# ---- audio helpers ---------------------------------------------------------
def pcm_s16le_to_float32(pcm: bytes) -> np.ndarray:
    if not pcm:
        return np.zeros(0, dtype=np.float32)
    usable = len(pcm) - (len(pcm) % 2)
    if usable == 0:
        return np.zeros(0, dtype=np.float32)
    return np.frombuffer(pcm[:usable], dtype="<i2").astype(np.float32) / 32768.0


def float32_to_pcm_s16le(x: np.ndarray) -> bytes:
    x = np.clip(x, -1.0, 1.0)
    return (x * 32767.0).astype("<i2").tobytes()


def resample_s16le(pcm: bytes, src_sr: int, dst_sr: int) -> bytes:
    """Linear-interpolation resample of mono s16le PCM (32k->24k quality is
    fine for speech; no scipy dependency in brain/.venv)."""
    if src_sr == dst_sr or not pcm:
        return pcm
    x = pcm_s16le_to_float32(pcm)
    if len(x) == 0:
        return b""
    n_dst = max(1, int(round(len(x) * dst_sr / src_sr)))
    t_src = np.linspace(0.0, 1.0, num=len(x), endpoint=False)
    t_dst = np.linspace(0.0, 1.0, num=n_dst, endpoint=False)
    return float32_to_pcm_s16le(np.interp(t_dst, t_src, x))


def chunk_amplitude(pcm_chunk: bytes, gain: float = 3.0) -> float:
    """PROTOCOL §8 amplitude 0..1 — RMS of the REAL audio, gain-scaled."""
    x = pcm_s16le_to_float32(pcm_chunk)
    if len(x) == 0:
        return 0.0
    rms = float(np.sqrt(np.mean(x * x)))
    return max(0.0, min(1.0, rms * gain))


def chunk_pitch_hz(pcm_chunk: bytes, sample_rate: int) -> Optional[float]:
    """Rough f0 via zero-crossing rate, gated: only voiced-ish, energetic
    chunks in 60-400 Hz emit pitch_hz; otherwise None (§8: optional field)."""
    x = pcm_s16le_to_float32(pcm_chunk)
    if len(x) < 64:
        return None
    rms = float(np.sqrt(np.mean(x * x)))
    if rms < 0.04:
        return None
    signs = np.signbit(x)
    zcr = float(np.count_nonzero(signs[1:] != signs[:-1])) / (len(x) - 1)
    f_hz = zcr * sample_rate / 2.0
    if 60.0 <= f_hz <= 400.0:
        return round(f_hz, 1)
    return None


def split_sentences(text: str, max_chars: int = 220) -> List[str]:
    """Sentence boundaries for speak streaming (also handles CJK + long runs)."""
    t = (text or "").strip()
    if not t:
        return []
    parts = [p.strip() for p in _SENT_SPLIT_RE.split(t) if p and p.strip()]
    out: List[str] = []
    for p in parts:
        while len(p) > max_chars:                      # hard-wrap long runs
            cut = p.rfind(" ", 0, max_chars)
            if cut < max_chars // 2:
                cut = max_chars
            out.append(p[:cut].strip())
            p = p[cut:].strip()
        if p:
            out.append(p)
    return out


def encode_binary_frame(kind: int, seq: int, payload: bytes) -> bytes:
    """PROTOCOL §6: [4-byte magic 'RAPH'][u8 kind][u32 seq][payload].

    Byte order for the u32 seq: BIG-endian (network order) — PROTOCOL does
    not specify; body-dev must match (documented in README/handoff).
    """
    return PROTOCOL_MAGIC + struct.pack(">BI", kind & 0xFF, seq & 0xFFFFFFFF) + payload


def wav_bytes_to_s16le_pcm(wav: bytes, target_sr: int) -> Tuple[bytes, int]:
    """Decode wav bytes (any rate/channels) -> mono s16le at target_sr."""
    import soundfile as sf

    data, sr = sf.read(io.BytesIO(wav), dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    pcm = float32_to_pcm_s16le(mono)
    if sr != target_sr:
        pcm = resample_s16le(pcm, int(sr), target_sr)
    return pcm, target_sr


# ---- phrase cache ----------------------------------------------------------
class PhraseCache:
    """Disk cache of synthesized phrases (config voice.ack_cache).

    Lookup order per phrase: human-named '<normalized>.wav' first (lets the
    user drop pre-recorded acks), then sha1-normalized hash file.
    Key = normalize_text(text) (wake.py: NFKC + lowercase + de-punctuated).
    """

    def __init__(self, directory: Path):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def key_for(text: str) -> str:
        return normalize_text(text)

    @staticmethod
    def _hash_name(key: str) -> str:
        return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16] + ".wav"

    def path_for(self, text: str) -> Path:
        key = self.key_for(text)
        human = self.dir / f"{key}.wav"
        if human.exists():
            return human
        return self.dir / self._hash_name(key)

    def load(self, text: str) -> Optional[bytes]:
        try:
            p = self.path_for(text)
            if p.exists() and p.stat().st_size > 0:
                return p.read_bytes()
        except OSError:
            pass
        return None

    def store(self, text: str, wav: bytes) -> Optional[Path]:
        try:
            p = self.dir / self._hash_name(self.key_for(text))
            p.write_bytes(wav)
            return p
        except OSError:
            return None


# ---- fish-speech server (isolated venv) ------------------------------------
class FishSpeechServer:
    """Manages the fish-speech v1.5.0 API server subprocess + REST calls.

    Server command (docs/en/inference.md @ v1.5.0):
      python -m tools.api_server --listen H:P --llama-checkpoint-path CKPT
             --decoder-checkpoint-path CKPT/firefly-gan-vq-fsq-8x1024-21hz-generator.pth
             --decoder-config-name firefly_gan_vq --device cuda --half
    Request:  POST /v1/tts {text, format:"wav", streaming:false, normalize:true,
              references:[{audio:<b64>, text:<str>}]?}
    Response: raw wav bytes (Content-Type audio/wav), decoder sample rate
              (32000 for firefly_gan_vq -> resampled here to 24000).
    """

    def __init__(self, cfg: VoiceConfig):
        self.cfg = cfg
        self.proc: Optional[subprocess.Popen] = None
        self._starting: Optional[asyncio.Task] = None
        self.base = f"http://{cfg.fish_host}:{cfg.fish_port}"
        self.log_dir = cfg.log_dir                # instance-derived (INTERFACES §d)
        self.log_path = self.log_dir / "fish_server.log"
        self.last_error: Optional[str] = None
        self.startup_ms: Optional[float] = None

    # -- lifecycle -----------------------------------------------------------
    def _spawn(self) -> subprocess.Popen:
        ckpt = self.cfg.fish_checkpoint_path
        llama = ckpt
        decoder = ckpt / "firefly-gan-vq-fsq-8x1024-21hz-generator.pth"
        if not llama.exists() or not decoder.exists():
            raise TTSError("E_LOCAL_DOWN",
                           f"fish-speech checkpoint incomplete under {ckpt}")
        venv_py = self.cfg.fish_venv_python
        if not venv_py.exists():
            raise TTSError("E_LOCAL_DOWN",
                           f"fish venv missing: {venv_py} "
                           "(run brain/voice/scripts/build_fish_venv.sh)")
        device = (self.cfg.fish_device or "auto").lower()
        if device == "auto":
            try:
                import torch

                device = "cuda" if torch.cuda.is_available() else "cpu"
            except Exception:  # noqa: BLE001
                device = "cpu"
        cmd = [str(venv_py), "-m", "tools.api_server",
               "--listen", f"{self.cfg.fish_host}:{self.cfg.fish_port}",
               "--llama-checkpoint-path", str(llama),
               "--decoder-checkpoint-path", str(decoder),
               "--decoder-config-name", "firefly_gan_vq",
               "--device", device]
        if device == "cuda":
            cmd.append("--half")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        logf = open(self.log_path, "ab")  # noqa: SIM115 — lives with subprocess
        env = dict(os.environ)
        env.setdefault("HF_HUB_OFFLINE", "1")   # weights are local
        env.setdefault("no_proxy", "127.0.0.1,localhost")
        return subprocess.Popen(
            cmd, cwd=str(self.cfg.fish_vendor_path), stdout=logf,
            stderr=subprocess.STDOUT, env=env, start_new_session=True)

    def _alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                r = await client.post(f"{self.base}/v1/health")
                return r.status_code == 200 and r.json().get("status") == "ok"
        except Exception:  # noqa: BLE001
            return False

    async def ensure_started(self, timeout_s: float = 240.0) -> None:
        """Idempotent start + wait for /v1/health. Raises TTSError."""
        if await self.health():
            return
        if self._starting is None:
            loop = asyncio.get_running_loop()
            self._starting = loop.create_task(self._start_once(timeout_s))
        await self._starting

    async def _start_once(self, timeout_s: float) -> None:
        t0 = time.perf_counter()
        try:
            self.proc = self._spawn()
        except TTSError:
            raise
        except Exception as e:  # noqa: BLE001
            self.last_error = str(e)
            raise TTSError("E_INTERNAL", f"fish server spawn failed: {e}") from e
        deadline = time.perf_counter() + timeout_s
        while time.perf_counter() < deadline:
            if await self.health():
                self.startup_ms = (time.perf_counter() - t0) * 1000.0
                self._starting = None
                return
            if not self._alive():
                tail = ""
                try:
                    tail = self.log_path.read_text(errors="replace")[-800:]
                except OSError:
                    pass
                self.last_error = tail
                self._starting = None
                raise TTSError(
                    "E_LOCAL_DOWN",
                    f"fish server exited rc={self.proc.poll()} during startup; "
                    f"log tail: {tail[-400:]}")
            await asyncio.sleep(1.0)
        self._starting = None
        raise TTSError("E_TIMEOUT", f"fish server not healthy in {timeout_s}s")

    def stop(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            try:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
                self.proc.wait(timeout=10)
            except Exception:  # noqa: BLE001
                try:
                    os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
                except Exception:  # noqa: BLE001
                    pass
        self.proc = None
        self._starting = None

    # -- synthesis -----------------------------------------------------------
    def _references(self) -> List[Dict[str, str]]:
        """In-context reference from assets/raphael_reference.wav when present."""
        voice = self.cfg.tts_voice_path
        if not voice.exists():
            return []
        try:
            raw = voice.read_bytes()
        except OSError:
            return []
        ref_text = ""
        txt = voice.with_suffix(".txt")
        if txt.exists():
            try:
                ref_text = txt.read_text(encoding="utf-8").strip()
            except OSError:
                ref_text = ""
        return [{"audio": base64.b64encode(raw).decode("ascii"),
                 "text": ref_text}]

    async def synthesize(self, text: str) -> bytes:
        """Sentence -> wav bytes (decoder rate). Raises TTSError on failure."""
        payload = {
            "text": text, "format": "wav", "streaming": False,
            "normalize": True, "use_memory_cache": "on",
            "references": self._references(),
        }
        try:
            async with httpx.AsyncClient(timeout=180.0) as client:
                r = await client.post(f"{self.base}/v1/tts", json=payload)
        except httpx.HTTPError as e:
            raise TTSError("E_LOCAL_DOWN", f"fish /v1/tts unreachable: {e}") from e
        if r.status_code != 200:
            raise TTSError("E_INTERNAL",
                           f"fish /v1/tts HTTP {r.status_code}: {r.text[:200]}")
        if not r.content or len(r.content) < 128:
            raise TTSError("E_INTERNAL", "fish /v1/tts returned empty audio")
        return r.content


# ---- speak stream ----------------------------------------------------------
@dataclass
class SpeakStreamStats:
    sentences: int = 0
    chunks: int = 0
    cached: bool = False
    engine: str = "none"


def _placeholder_tone_pcm(sample_rate: int, ms: int = 350) -> bytes:
    """Honest degraded-mode audio: soft 440 Hz sine with fades — clearly a
    placeholder (events carry notice + engine='fallback'), never presented as
    Raphael's voice."""
    n = int(sample_rate * ms / 1000)
    t = np.arange(n, dtype=np.float32) / sample_rate
    x = 0.18 * np.sin(2.0 * math.pi * 440.0 * t)
    fade = max(1, n // 10)
    env = np.ones(n, dtype=np.float32)
    env[:fade] = np.linspace(0.0, 1.0, fade)
    env[-fade:] = np.linspace(1.0, 0.0, fade)
    return float32_to_pcm_s16le(x * env)


class TTSEngine:
    """The object loop.py talks to: cfg + cache + fish server singleton."""

    def __init__(self, cfg: Optional[VoiceConfig] = None):
        self.cfg = cfg or load_voice_config()
        self.cache = PhraseCache(self.cfg.ack_cache_path)
        self.fish = FishSpeechServer(self.cfg)
        self.stats = SpeakStreamStats()
        self._notice_shown = False      # degraded-mode notice: ONCE per process

    def _once(self, message: str) -> Optional[str]:
        """Returns `message` the first time, None afterwards (one-time notice)."""
        if self._notice_shown:
            return None
        self._notice_shown = True
        return message

    def fallback_notice(self) -> Optional[str]:
        """One-time degraded-mode notice (Wave 2 task 3): the FIRST reply after
        Fish becomes unavailable tells the user why there is no voice; every
        later reply stays quiet (subtitles still carry the text) instead of
        repeating the apology — or playing a placeholder tone forever."""
        return self._once("TTS engine unavailable — replies are shown as "
                          "subtitles until Fish-Speech is back.")

    @property
    def sample_rate(self) -> int:
        return int(self.cfg.tts_sample_rate or TTS_SAMPLE_RATE_DEFAULT)

    async def warmup(self) -> None:
        """Pre-start the fish server (resume hook: ARCHITECTURE §6 reliability).
        Never raises — warmup failure degrades to fallback at speak time."""
        try:
            await self.fish.ensure_started()
        except TTSError as e:
            self.fish.last_error = str(e)

    def shutdown(self) -> None:
        self.fish.stop()

    def _chunk_events(self, pcm: bytes, seq_start: int, job: Optional[str],
                      cached: bool, engine: str) -> Tuple[List[Dict[str, Any]], int]:
        """PCM @24k -> speak 'chunk' frame dicts (payload attached)."""
        rate = self.sample_rate
        n = max(1, int(rate * self.cfg.chunk_ms / 1000))
        events: List[Dict[str, Any]] = []
        seq = seq_start
        for off in range(0, len(pcm), n):
            chunk = pcm[off:off + n]
            if not chunk:
                break
            events.append({
                "type": "speak", "v": 1, "job": job, "seq": seq,
                "event": "chunk", "sample_rate": rate,
                "amplitude": chunk_amplitude(chunk),
                "pitch_hz": chunk_pitch_hz(chunk, rate),
                "cached": cached, "engine": engine,
                "payload": chunk,
            })
            seq += 1
        return events, seq

    async def speak(self, text: str, *, job: Optional[str] = None,
                    cancel: Optional[asyncio.Event] = None,
                    force_fallback: bool = False,
                    ) -> AsyncIterator[Dict[str, Any]]:
        """Async iterator of PROTOCOL speak frame dicts, sentence by sentence.

        Frame fields: type='speak', v=1, job, seq, event=start|chunk|end,
        sample_rate, text (start only), amplitude+pitch_hz (chunk only),
        cached, engine ('fish'|'cache'|'fallback'), notice? (degraded mode),
        interrupted? (end only, barge-in). Chunk frames also carry
        'payload' (raw s16le bytes) — strip via speak_payload() before
        json.dumps; wrap with encode_binary_frame(2, seq, payload).
        """
        rate = self.sample_rate
        sentences = split_sentences(text)
        if not sentences:
            return
        # Playback-echo bookkeeping: remember what she is about to say so the
        # activation gate can drop her own voice when it bounces back through
        # the mic (self-trigger loop prevention — activation.py).
        get_playback_echoes().remember(text)
        self.stats = SpeakStreamStats(sentences=len(sentences))

        # --- 1. cache check (whole phrase) ---------------------------------
        cached_wav: Optional[bytes] = None
        if not force_fallback:
            cached_wav = self.cache.load(text)
        cached = cached_wav is not None
        engine = "cache" if cached else "none"

        yield {"type": "speak", "v": 1, "job": job, "seq": 0, "event": "start",
               "sample_rate": rate, "text": text, "cached": cached,
               "engine": engine}

        seq = 1

        def _end(interrupted: bool, notice: Optional[str] = None) -> Dict[str, Any]:
            ev: Dict[str, Any] = {"type": "speak", "v": 1, "job": job,
                                  "seq": seq, "event": "end",
                                  "sample_rate": rate, "cached": cached,
                                  "engine": self.stats.engine or engine}
            if interrupted:
                ev["interrupted"] = True
            if notice:
                ev["notice"] = notice
            return ev

        if cancel is not None and cancel.is_set():
            self.stats.engine = engine or "cache"
            yield _end(interrupted=True)
            return

        # --- 2a. cache hit: stream wav chunks immediately -------------------
        if cached_wav is not None:
            self.stats.cached = True
            self.stats.engine = "cache"
            try:
                pcm, _ = wav_bytes_to_s16le_pcm(cached_wav, rate)
            except Exception:  # noqa: BLE001 — corrupt cache entry -> refallback
                pcm = b""
            if pcm:
                chunk_evs, next_seq = self._chunk_events(pcm, seq, job, True,
                                                         "cache")
                for ev in chunk_evs:
                    if cancel is not None and cancel.is_set():
                        seq = ev["seq"]
                        yield _end(interrupted=True)
                        return
                    seq = ev["seq"] + 1
                    yield ev
                yield _end(interrupted=False)
                return
            # corrupt cache: fall through to synthesis

        # --- 2b. fish-speech, sentence by sentence --------------------------
        fish_ok = False
        if not force_fallback:
            try:
                await self.fish.ensure_started()
                fish_ok = True
            except TTSError:
                fish_ok = False

        synthesized: List[bytes] = []
        notice: Optional[str] = None
        if fish_ok:
            self.stats.engine = "fish"
            for sent in sentences:
                if cancel is not None and cancel.is_set():
                    yield _end(interrupted=True)
                    return
                try:
                    wav = await self.fish.synthesize(sent)   # blocks on THIS sentence
                    pcm, _ = wav_bytes_to_s16le_pcm(wav, rate)
                    synthesized.append(pcm)
                except TTSError as e:
                    # engine died mid-stream: finish what we have + notice
                    fish_ok = False
                    notice = self._once(
                        f"TTS engine error ({e.code}) — partial speech; "
                        f"{e.detail[:120]}")
                    break
                # stream the sentence NOW while the next one generates
                chunk_evs, next_seq = self._chunk_events(pcm, seq, job, False,
                                                         "fish")
                for ev in chunk_evs:
                    if cancel is not None and cancel.is_set():
                        seq = ev["seq"]
                        yield _end(interrupted=True)
                        return
                    seq = ev["seq"] + 1
                    yield ev
                if not fish_ok:
                    break
            if fish_ok and synthesized:
                # store full phrase for future cache hits
                try:
                    full = b"".join(synthesized)
                    import soundfile as sf

                    buf = io.BytesIO()
                    sf.write(buf, pcm_s16le_to_float32(full), rate, format="WAV",
                             subtype="PCM_16")
                    self.cache.store(text, buf.getvalue())
                except Exception:  # noqa: BLE001 — cache write is best-effort
                    pass

        # --- 2c. degraded fallback (SUBTITLE-ONLY, one-time notice) ---------
        if not fish_ok and not synthesized:
            # Wave 2 task 3: Fish unavailable -> no audio at all (never a
            # placeholder tone), loop.py already subtitles the reply; the
            # ONE-TIME notice explains the missing voice instead of silence
            # being mysterious (or the apology repeating on every reply).
            self.stats.engine = "fallback"
            notice = notice or self.fallback_notice()
            if cancel is not None and cancel.is_set():
                yield _end(interrupted=True, notice=notice)
                return
            yield _end(interrupted=False, notice=notice)
            return

        yield _end(interrupted=False, notice=notice)


# ---- PROTOCOL frame helpers (loop.py convenience) --------------------------
def speak_frame(event: Dict[str, Any]) -> Dict[str, Any]:
    """JSON-safe speak frame (payload stripped)."""
    return {k: v for k, v in event.items() if k != "payload"}


def speak_payload(event: Dict[str, Any]) -> bytes:
    p = event.get("payload")
    return p if isinstance(p, (bytes, bytearray)) else b""


def stt_final_frame(text: str, lang: Optional[str], rtf: float,
                    job: Optional[str] = None) -> Dict[str, Any]:
    return {"type": "stt_final", "v": 1, "job": job, "text": text,
            "lang": lang or "", "rtf": round(float(rtf), 3)}


def error_frame(code: str, detail: str, job: Optional[str] = None) -> Dict[str, Any]:
    return {"type": "error", "v": 1, "code": code, "job": job,
            "detail": str(detail)[:300]}


# ---- module singleton ------------------------------------------------------
_engine: Optional[TTSEngine] = None


def get_tts(cfg: Optional[VoiceConfig] = None) -> TTSEngine:
    global _engine
    if _engine is None:
        _engine = TTSEngine(cfg)
    return _engine


async def speak(text: str, **kwargs: Any) -> AsyncIterator[Dict[str, Any]]:
    """Public API: async iterator of speak frame dicts (see TTSEngine.speak)."""
    async for ev in get_tts().speak(text, **kwargs):
        yield ev

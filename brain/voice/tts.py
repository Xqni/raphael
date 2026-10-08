"""brain/voice/tts.py — Fish-Speech TTS adapter + phrase cache + speak stream
(voice-dev). Emits PROTOCOL §3 `speak` frame dicts.

GAPLESS DELIVERY (P0, 2026-10-07): multi-sentence replies are PRE-ROLLED —
every sentence is synthesized first (bounded by `preroll_budget_s`,
env `RAPHAEL_TTS_PREROLL_S`, default 20s, 0 disables), then all chunks are
burst-sent, so the body never starves mid-reply (fish ~RTF 0.5 left one
12.23s inter-chunk hole otherwise). Single-sentence replies and cache hits
have no added latency. Sentences beyond the spoken cap are never synthesized.

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

Reference voice (USER DIRECTIVE 2026-10-07 — Bug D): config voice.tts_voice
(currently assets/raphael_reference_jp.wav, the great-sage voice) is sent as
an in-context reference (base64 JSON per tools/schema.py ServeReferenceAudio)
on EVERY synthesis, with a proof log line (`[tts] ref sent: path=... bytes=
...`). voice.tts_reference_required (default True) turns a missing reference
into a LOUD failure (subtitle notice + log) instead of a silent default/Zira
voice. The phrase cache is namespaced by sha1(reference)[:12] — a reference
change can never replay another voice's audio — and fish's own text-keyed
memory cache is disabled for the same reason.

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
import shutil
import signal
import struct
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

import httpx
import numpy as np

from .config import VoiceConfig, load_voice_config, voice_data_dir
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


def _log(msg: str) -> None:
    """stdout-flushed lane log (brain's stdout goes to its log file; pythonw
    pipes swallow unflushed prints — always flush)."""
    print(msg, flush=True)


def reference_fingerprint(path: Path) -> str:
    """sha1(reference audio)[:12] — the phrase-cache namespace (Bug D).
    Missing/unreadable file -> 'noref' (never raises: engine must construct)."""
    try:
        data = Path(path).read_bytes()
    except OSError:
        return "noref"
    if not data:
        return "noref"
    return hashlib.sha1(data).hexdigest()[:12]


# ---- timbre sanity (P0 2026-10-07: never cache a wrong-voice render) -------
STORE_MIN_COS = 0.65   # measured: our-voice renders 0.74-0.98, Zira 0.13-0.48,
                       # the one poisoned live entry 0.643 -> 0.65 splits them
_SPEC_BANDS = None     # np.logspace 200..7000 Hz, 17 edges, built lazily


def _log_spec(x: np.ndarray, sr: int) -> Optional["np.ndarray"]:
    """16-band log-spectral fingerprint of a float32 mono signal."""
    global _SPEC_BANDS
    if len(x) < sr // 5:
        return None
    if _SPEC_BANDS is None:
        _SPEC_BANDS = np.logspace(np.log10(200), np.log10(7000), 17)
    frame, hop = int(0.04 * sr), int(0.02 * sr)
    vec = []
    freqs = np.fft.rfftfreq(frame, 1 / sr)
    for i in range(0, len(x) - frame, hop):
        f = x[i:i + frame]
        if float(np.sqrt(np.mean(f * f))) < 0.03:
            continue
        mag = np.abs(np.fft.rfft(f * np.hanning(frame)))
        e = [float(np.sum(mag[(freqs >= _SPEC_BANDS[j]) &
                              (freqs < _SPEC_BANDS[j + 1])] ** 2) + 1e-9)
             for j in range(16)]
        vec.append(np.log(e))
    if not vec:
        return None
    return np.mean(np.stack(vec), axis=0)


def _read_mono16k(path: Path) -> Optional[np.ndarray]:
    try:
        import soundfile as sf
        data, sr = sf.read(str(path), dtype="float32", always_2d=True)
    except Exception:  # noqa: BLE001 — sanity gate must never break speak()
        return None
    x = data.mean(axis=1)
    if sr != 16000:
        n = int(len(x) * 16000 / sr)
        if n <= 0:
            return None
        x = np.interp(np.linspace(0, len(x) - 1, n),
                      np.arange(len(x)), x).astype(np.float32)
    return x


def timbre_similarity(pcm: bytes, sample_rate: int,
                      ref_path: Path) -> Optional[float]:
    """Cosine similarity of 16-band log-spectra vs the configured reference.

    Coarse timbre proxy (NOT speaker verification): a wrong-voice synthesis
    (fish drift / pre-reference audio) scores far from the reference, our
    renders score high (measured 0.74-0.98 vs 0.13-0.64 for wrong voices).
    Blind spot: spectrally FLAT noise scores high — irrelevant in practice
    (fish synthesizes speech, and both real wrong voices we measured are far
    below the threshold). None = cannot judge (too short / unreadable ref)
    -> caller keeps (fail-open: never block caching for lack of evidence)."""
    x = pcm_s16le_to_float32(pcm)
    if sample_rate != 16000:
        n = int(len(x) * 16000 / sample_rate)
        if n <= 0:
            return None
        x = np.interp(np.linspace(0, len(x) - 1, n),
                      np.arange(len(x)), x).astype(np.float32)
    a = _log_spec(x, 16000)
    ref = _read_mono16k(ref_path)
    b = _log_spec(ref, 16000) if ref is not None else None
    if a is None or b is None:
        return None
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if not denom:
        return None
    return float(np.dot(a, b) / denom)


def sweep_legacy_cache(directory: Path,
                       dest: Optional[Path] = None) -> List[Path]:
    """P0 2026-10-07: move NON-namespaced (pre-reference) hash wavs OUT of the
    ack cache root. The wave-3 namespace means every current entry lives in
    `<dir>/<ref_sha1>/`; a bare `16-hex.wav` at the root is a pre-JP leftover
    that must never be served (it can't be looked up either — belt and braces
    + the acceptance criterion "no non-namespaced wav survives").

    Only AUTO-STORED (hex-named) files are touched; user-dropped, text-named
    acks (documented feature) are left alone. Returns the moved paths.
    """
    import re
    moved: List[Path] = []
    try:
        directory = Path(directory)
        dest = Path(dest) if dest else (
            voice_data_dir() / "cache_swept")
        dest.mkdir(parents=True, exist_ok=True)
        for p in sorted(directory.glob("*.wav")):
            if re.fullmatch(r"[0-9a-f]{16}\.wav", p.name):
                target = dest / p.name
                if target.exists():            # never overwrite a prior sweep
                    target = dest / f"{p.stem}_{int(p.stat().st_mtime)}.wav"
                shutil.move(str(p), str(target))  # cross-device safe (tmpfs!)
                moved.append(p)
    except Exception as e:  # noqa: BLE001 — housekeeping must never break start
        _log(f"[tts] cache sweep failed: {type(e).__name__}: {e}")
    return moved


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

    REFERENCE-NAMESPACED (Bug D / user directive 2026-10-07 — "JP great-sage
    voice on EVERY speech"): auto-stored wavs live in `<ack_cache>/<ref_fp>/`,
    where `ref_fp` = sha1(reference audio)[:12]. Changing the voice reference
    can therefore NEVER replay an old-voice wav (the Zira-era hashes at the
    top level become unreachable), and future persona voices coexist.

    Lookup order per phrase: current-ref human-named '<normalized>.wav'
    (subdir) -> user-dropped ack at the TOP level (text-named only: a hash
    file up there is an unreachable leftover from another voice, never read)
    -> sha1 hash file in the current-ref subdir.
    Key = normalize_text(text) (wake.py: NFKC + lowercase + de-punctuated).
    """

    def __init__(self, directory: Path, fingerprint: str = ""):
        self.dir = Path(directory)
        self.fingerprint = (fingerprint or "noref")[:12] or "noref"
        self.subdir = self.dir / self.fingerprint
        self.subdir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def key_for(text: str) -> str:
        return normalize_text(text)

    @staticmethod
    def _hash_name(key: str) -> str:
        return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16] + ".wav"

    def path_for(self, text: str) -> Path:
        key = self.key_for(text)
        human_sub = self.subdir / f"{key}.wav"
        if human_sub.exists():
            return human_sub
        human_top = self.dir / f"{key}.wav"        # user-dropped ack (text name)
        if human_top.exists():
            return human_top
        return self.subdir / self._hash_name(key)

    def load(self, text: str) -> Optional[bytes]:
        try:
            p = self.path_for(text)
            if p.exists() and p.stat().st_size > 0:
                return p.read_bytes()
        except OSError:
            pass
        return None

    def store(self, text: str, wav: bytes) -> Optional[Path]:
        """Atomic write (flake-hardening): a concurrent reader — another test
        run, or the live stack — must never see a half-written wav. Write to a
        per-process temp file, then os.replace() (atomic on POSIX + Windows)."""
        try:
            p = self.subdir / self._hash_name(self.key_for(text))
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
            tmp.write_bytes(wav)
            os.replace(tmp, p)
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

    # -- reference voice (USER DIRECTIVE / Bug D) ----------------------------
    def check_reference(self) -> Path:
        """The configured reference MUST be loadable before synthesis.

        `tts_reference_required` (default True — user directive 2026-10-07:
        the great-sage voice on EVERY speech, no default/Zira voice ever):
        a missing or empty reference raises TTSError so speak() degrades
        LOUDLY (notice + log) instead of quietly synthesizing in fish's
        default voice. Opt out only with VoiceConfig(
        tts_reference_required=False) — tests and explicit tooling.
        """
        voice = self.cfg.reference_path
        try:
            missing = (not voice.exists()) or voice.stat().st_size == 0
        except OSError:
            missing = True
        if missing and self.cfg.tts_reference_required:
            raise TTSError("E_INTERNAL",
                           f"voice reference MISSING: {voice} — refusing to "
                           f"synthesize without it (config voice.tts_voice)")
        return voice

    def _references(self) -> List[Dict[str, str]]:
        """In-context reference payload — sent on EVERY synthesis.

        LOUD (Bug D): never silently empty. Missing+required -> TTSError;
        missing+explicitly-optional -> one clear log line about fish's
        default voice being used.
        """
        voice = self.check_reference()          # raises when required+missing
        try:
            raw = voice.read_bytes()
        except OSError as e:
            if self.cfg.tts_reference_required:
                raise TTSError("E_INTERNAL",
                               f"voice reference unreadable: {voice} ({e})") from e
            _log(f"[tts] REFERENCE UNREADABLE ({voice}) — fish default voice")
            return []
        if not raw:
            if self.cfg.tts_reference_required:
                raise TTSError("E_INTERNAL", f"voice reference empty: {voice}")
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

    def _payload(self, text: str, references: List[Dict[str, str]]) -> Dict[str, Any]:
        # fish's own memory cache is keyed by TEXT alone — after a reference
        # change it would replay the OLD voice (Bug D suspect #3), so it is
        # OFF and our reference-namespaced PhraseCache is the only cache.
        return {
            "text": text, "format": "wav", "streaming": False,
            "normalize": True, "use_memory_cache": "off",
            "references": references,
        }

    async def synthesize(self, text: str) -> bytes:
        """Sentence -> wav bytes (decoder rate). Raises TTSError on failure."""
        references = self._references()          # LOUD: raises if ref missing
        voice = self.cfg.reference_path
        try:
            size = voice.stat().st_size
        except OSError:
            size = 0
        if references:
            # PROOF LINE (Bug D acceptance): path + bytes sent per synthesis
            _log(f"[tts] ref sent: path={voice} bytes={size} sha1="
                 f"{reference_fingerprint(voice)} sentence={text[:48]!r}")
        else:
            _log(f"[tts] NO REFERENCE sent (optional mode): {voice} — "
                 f"fish default voice in use")
        payload = self._payload(text, references)
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
        # reference fingerprint = phrase-cache namespace (Bug D): switching the
        # voice reference can never replay a wav synthesized with another voice
        self.reference_path, self._tier_note = self.cfg.tier_voice_path()
        self.reference_fp = reference_fingerprint(self.reference_path)
        self._tier_notice_shown = False
        self.cache = PhraseCache(self.cfg.ack_cache_path,
                                 fingerprint=self.reference_fp)
        self.fish = FishSpeechServer(self.cfg)
        self.stats = SpeakStreamStats()
        self._notice_shown = False      # degraded-mode notice: ONCE per process
        # fish-death recovery state (Wave 4 failure modes) — per-speak flags
        self._recovery_attempted = False
        self._recovered_this_speak = False
        self._recovery_notice_shown = False
        # P0 gapless playback: how long a multi-sentence reply may be
        # pre-rolled (synthesized before the first chunk is sent). Default
        # 60s: fish serializes requests, so wall-time per sentence inflates
        # when the live brain talks concurrently (measured: a 26.4s request
        # from another client queued ahead) — the budget is a safety valve
        # against unbounded waits, NOT a latency target; hitting it falls
        # back to live streaming (holes possible, logged). 0 disables
        # pre-roll entirely (old sentence-streaming behavior). A one-time
        # notice is emitted when pre-roll exceeds 8s (Rule-15 UX honesty).
        try:
            self.preroll_budget_s = float(
                os.environ.get("RAPHAEL_TTS_PREROLL_S", "60") or 60)
        except (TypeError, ValueError):
            self.preroll_budget_s = 60.0
        # P0 (2026-10-07): non-namespaced pre-reference wavs must never sit in
        # the cache root — swept once at startup (regenerable, moved outside
        # the repo; user-dropped text-named acks are untouched).
        moved = sweep_legacy_cache(self.cfg.ack_cache_path)
        if moved:
            _log(f"[tts] swept {len(moved)} non-namespaced cache wavs -> "
                 f"{voice_data_dir() / 'cache_swept'} (stale-voice cleanup)")

    # -- fish death mid-speak recovery (Wave 4) ------------------------------
    async def _restart_fish(self, timeout_s: float = 8.0) -> bool:
        """ONE restart attempt when fish dies mid-speak.

        Ownership rule (Rule 14 / INTERFACES §d): we stop a process only if
        `fish.proc` says WE spawned it — an externally-managed server (live
        stack, supervisor) is never killed, only re-checked and reused.
        Bounded timeout: mid-speak recovery must not hang the job.
        """
        if self._recovery_attempted:
            return False
        self._recovery_attempted = True
        try:
            if self.fish.proc is not None:
                _log("[tts] fish died mid-speak -> restarting OUR process")
                self.fish.stop()
        except Exception:  # noqa: BLE001 — restart must never raise into speak()
            pass
        try:
            await self.fish.ensure_started(timeout_s=timeout_s)
            _log("[tts] fish recovery OK (mid-speak restart)")
            return True
        except TTSError as e:
            self.fish.last_error = str(e)
            _log(f"[tts] fish recovery FAILED: {e.code} {e.detail[:200]}")
            return False

    async def _synthesize_resilient(self, sentence: str) -> bytes:
        """Synthesize one sentence with ONE restart+retry on engine death.
        Reference errors are never retried (a restart cannot fix a missing
        reference — that must fail loud, Bug D)."""
        try:
            return await self.fish.synthesize(sentence)
        except TTSError as e:
            if "reference" in e.detail:
                raise
            if not await self._restart_fish():
                raise
            self._recovered_this_speak = True
            return await self.fish.synthesize(sentence)   # single retry

    def _recovery_notice(self) -> Optional[str]:
        """One-time notice after a SUCCESSFUL mid-speak restart (the user
        heard a hiccup — tell them once, never on every reply)."""
        if self._recovery_notice_shown:
            return None
        self._recovery_notice_shown = True
        return "Voice engine restarted mid-reply."

    def refresh_reference(self) -> str:
        """Re-resolve the TIER reference + fingerprint (cheap), re-namespace
        the phrase cache when anything changed — self-heals both a user
        reference swap AND a persona-tier flip (great_sage -> ciel) WITHOUT a
        restart, invalidating old-voice cache entries from that first chunk.
        Returns the current fingerprint."""
        path, note = self.cfg.tier_voice_path()
        fp = reference_fingerprint(path)     # content-addressed: catches an
        # in-place file swap too (Bug D), not just a path/tier change
        if path != self.reference_path or fp != self.reference_fp:
            _log(f"[tts] reference -> {path} (tier '{self.cfg.persona_tier}', "
                 f"fp {fp}); phrase cache re-namespaced")
            self.reference_path = path
            self.reference_fp = fp
            self.cache = PhraseCache(self.cfg.ack_cache_path,
                                     fingerprint=fp)
        self._tier_note = note
        return fp

    def _tier_fallback_notice(self) -> Optional[str]:
        """One-time notice when the persona tier's voice slot was missing and
        the current reference was used instead (Wave 5 tier surface — the
        evolution design's 'fallback + spoken notice')."""
        if self._tier_notice_shown or not self._tier_note:
            return None
        self._tier_notice_shown = True
        return self._tier_note

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
        Never raises — warmup failure degrades to fallback at speak time.
        Also verifies (LOUDly) that the reference voice is loadable, so a
        missing ref is visible at boot instead of at the first answer."""
        try:
            await self.fish.ensure_started()
        except TTSError as e:
            self.fish.last_error = str(e)
        try:
            ref = self.fish.check_reference()
            size = ref.stat().st_size if ref.exists() else 0
            _log(f"[tts] reference present: path={ref} bytes={size} "
                 f"fp={self.refresh_reference()}")
        except TTSError as e:
            self.fish.last_error = str(e)
            _log(f"[tts] BLOCKED (reference) at warmup: {e.detail}")

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
                    max_sentences: Optional[int] = None,
                    ) -> AsyncIterator[Dict[str, Any]]:
        """Async iterator of PROTOCOL speak frame dicts, sentence by sentence.

        Frame fields: type='speak', v=1, job, seq, event=start|chunk|end,
        sample_rate, text (start only), amplitude+pitch_hz (chunk only),
        cached, engine ('fish'|'cache'|'fallback'), notice? (degraded mode),
        interrupted? (end only, barge-in). Chunk frames also carry
        'payload' (raw s16le bytes) — strip via speak_payload() before
        json.dumps; wrap with encode_binary_frame(2, seq, payload).

        SPOKEN DELIVERY CAP (Wave 5): at most `max_sentences` sentences are
        synthesized — default from config voice_personality
        `spoken_reply_max_sentences` (2); `max_sentences=0` disables the cap.
        The subtitle/UI always carries the full text (loop.py), so fish never
        burns GPU on audio nobody hears (Rule 15), and long Reports/Answers
        read aloud at a fixed pace.
        """
        rate = self.sample_rate
        sentences = split_sentences(text)
        if not sentences:
            return
        limit = (self.cfg.spoken_max_sentences if max_sentences is None
                 else max_sentences)
        if limit and limit > 0 and len(sentences) > limit:
            _log(f"[tts] spoken cap: synthesizing {limit} of "
                 f"{len(sentences)} sentences (rest is subtitle-only)")
            sentences = sentences[:limit]
        spoken = " ".join(sentences)
        # Playback-echo bookkeeping: remember what she is about to SAY so the
        # activation gate can drop her own voice when it bounces back through
        # the mic (self-trigger loop prevention — activation.py).
        get_playback_echoes().remember(spoken)
        # Reference handshake (Bug D): re-fingerprint + re-namespace the phrase
        # cache BEFORE any cache lookup, so a swapped reference is picked up
        # immediately and old-voice wavs are unreachable from the first chunk.
        self.refresh_reference()
        # fresh recovery state for this utterance (Wave 4 failure modes)
        self._recovery_attempted = False
        self._recovered_this_speak = False
        self.stats = SpeakStreamStats(sentences=len(sentences))

        # --- 1. cache check (whole phrase) ---------------------------------
        cached_wav: Optional[bytes] = None
        if not force_fallback:
            cached_wav = self.cache.load(spoken)
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
        pre_err: Optional[TTSError] = None
        if not force_fallback:
            try:
                await self.fish.ensure_started()
            except TTSError as e:
                pre_err = e
            if pre_err is None:
                try:
                    # LOUD reference gate (Bug D): a missing reference must
                    # never reach a default-voice synthesis
                    self.fish.check_reference()
                    fish_ok = True
                except TTSError as e:
                    pre_err = e

        synthesized: List[bytes] = []
        notice: Optional[str] = None
        remainder: List[str] = []
        if fish_ok:
            self.stats.engine = "fish"
            # P0 (2026-10-07) GAPLESS PLAYBACK: fish runs at ~RTF 0.5, so
            # sentence N+1 is NOT ready when N's chunks finish — the body
            # drains and we get a mid-reply hole (measured: ONE 12.23s
            # inter-chunk hole; fish log shows the cause: a single dense
            # sentence request taking 11.81s of generation). Fix: PRE-ROLL
            # multi-sentence replies — synthesize the whole reply FIRST
            # (bounded by preroll_budget_s), then burst-send every chunk, so
            # the body never starves. Single-sentence replies and cache hits
            # are unaffected (no added latency). Disable with
            # RAPHAEL_TTS_PREROLL_S=0 (old sentence-streaming behavior).
            t_preroll = time.perf_counter()
            for i, sent in enumerate(sentences):
                if cancel is not None and cancel.is_set():
                    yield _end(interrupted=True)
                    return
                try:
                    # resilient: ONE restart+retry if fish dies mid-speak
                    wav = await self._synthesize_resilient(sent)
                    pcm, _ = wav_bytes_to_s16le_pcm(wav, rate)
                    synthesized.append(pcm)
                except TTSError as e:
                    # engine died mid-stream: finish what we have + notice
                    fish_ok = False
                    notice = self._once(
                        f"TTS engine error ({e.code}) — partial speech; "
                        f"{e.detail[:120]}")
                    break
                if len(sentences) > 1:
                    elapsed = time.perf_counter() - t_preroll
                    buffered_s = sum(len(p) / 2.0 / rate for p in synthesized)
                    remaining = len(sentences) - (i + 1)
                    # budget is a hard cap (checked first): never wait longer
                    if remaining and elapsed > self.preroll_budget_s:
                        remainder = sentences[i + 1:]
                        _log(f"[tts] preroll budget "
                             f"{self.preroll_budget_s}s hit after "
                             f"{i + 1}/{len(sentences)} sentences — streaming "
                             f"the rest live (gaps possible)")
                        break
                    # adaptive early-start: once the BUFFERED audio can out-run
                    # the estimated remaining generation (1.3x margin), start
                    # speaking and stream the tail as it arrives — cuts the
                    # pre-roll wait without reintroducing holes.
                    est_remaining_gen = (elapsed / (i + 1)) * remaining * 1.3
                    if remaining and buffered_s >= est_remaining_gen:
                        remainder = sentences[i + 1:]
                        _log(f"[tts] preroll adaptive start: "
                             f"{len(synthesized)} sentences ({buffered_s:.1f}s "
                             f"audio) buffered in {elapsed:.1f}s, streaming "
                             f"the remaining {remaining}")
                        break
            if len(sentences) > 1:
                preroll_s = round(time.perf_counter() - t_preroll, 2)
                _log(f"[tts] preroll: {len(synthesized)}/{len(sentences)} "
                     f"sentences buffered in {preroll_s}s before first chunk")
                if preroll_s > 8.0:
                    notice = notice or self._once(
                        "Preparing the full reply — one moment.")
            # burst-send everything buffered (gapless head) ...
            for pcm in synthesized:
                chunk_evs, next_seq = self._chunk_events(pcm, seq, job, False,
                                                         "fish")
                for ev in chunk_evs:
                    if cancel is not None and cancel.is_set():
                        seq = ev["seq"]
                        yield _end(interrupted=True, notice=notice)
                        return
                    seq = ev["seq"] + 1
                    yield ev
            # ... then any budget-deferred tail, sentence by sentence
            for sent in remainder:
                if cancel is not None and cancel.is_set():
                    yield _end(interrupted=True, notice=notice)
                    return
                try:
                    wav = await self._synthesize_resilient(sent)
                    pcm, _ = wav_bytes_to_s16le_pcm(wav, rate)
                except TTSError as e:
                    fish_ok = False
                    notice = notice or self._once(
                        f"TTS engine error ({e.code}) — partial speech; "
                        f"{e.detail[:120]}")
                    break
                chunk_evs, next_seq = self._chunk_events(pcm, seq, job, False,
                                                         "fish")
                for ev in chunk_evs:
                    if cancel is not None and cancel.is_set():
                        seq = ev["seq"]
                        yield _end(interrupted=True, notice=notice)
                        return
                    seq = ev["seq"] + 1
                    yield ev
            if fish_ok and synthesized:
                # store full phrase for future cache hits — but ONLY when the
                # render actually matches the reference voice (P0 2026-10-07:
                # one live entry scored 0.64 = off-voice, and a cached
                # wrong-voice phrase replays forever).
                try:
                    full = b"".join(synthesized)
                    score = timbre_similarity(full, rate, self.reference_path)
                    if score is not None and score < STORE_MIN_COS:
                        _log(f"[tts] cache store REFUSED: timbre cos "
                             f"{score:.2f} < {STORE_MIN_COS} vs "
                             f"{self.reference_path.name} (off-voice render "
                             f"not cached; phrase re-synthesizes)")
                    else:
                        import soundfile as sf

                        buf = io.BytesIO()
                        sf.write(buf, pcm_s16le_to_float32(full), rate,
                                 format="WAV", subtype="PCM_16")
                        self.cache.store(spoken, buf.getvalue())
                        if score is not None:
                            _log(f"[tts] cached phrase (timbre cos "
                                 f"{score:.2f} vs {self.reference_path.name})")
                except Exception:  # noqa: BLE001 — cache write is best-effort
                    pass

        # --- 2c. degraded fallback (SUBTITLE-ONLY, one-time notice) ---------
        if not fish_ok and not synthesized:
            # Wave 2 task 3: Fish unavailable -> no audio at all (never a
            # placeholder tone), loop.py already subtitles the reply; the
            # ONE-TIME notice explains the missing voice instead of silence
            # being mysterious (or the apology repeating on every reply).
            self.stats.engine = "fallback"
            if pre_err is not None and "reference" in pre_err.detail:
                # Bug D / user directive: missing reference = LOUD, specific
                # notice (subtitled) + the log line — never a default voice
                notice = notice or self._once(
                    f"Voice reference unavailable — {pre_err.detail[:180]}")
                _log(f"[tts] BLOCKED (reference): {pre_err.detail}")
            notice = notice or self.fallback_notice()
            if cancel is not None and cancel.is_set():
                yield _end(interrupted=True, notice=notice)
                return
            yield _end(interrupted=False, notice=notice)
            return

        if notice is None:
            # one-time informational notices (subtitled): tier voice-slot
            # fallback first (Wave 5), then a successful mid-speak restart
            notice = (self._tier_fallback_notice()
                      or (self._recovery_notice()
                          if self._recovered_this_speak else None))
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


# ---- spoken Notice delivery (Wave 5) ----------------------------------------
_NOTICE_LEADINS = ("warning:", "caution:", "attention:", "note:")


def notice_spoken_text(text: str, level: str = "info") -> str:
    """Level-tinted phrasing for a SPOKEN Notice (Wave 5).

    info -> as-is (calm, matter-of-fact, persona §10); warn -> a crisp lead-in
    UNLESS the text already carries one (idempotent), so an alerted warning is
    audibly distinct from a status line. Unknown levels coerce to 'info' — the
    same rule as brain/notice.build(). Sentence pacing stays with speak()
    (voice_personality.spoken_reply_max_sentences).
    """
    t = " ".join(str(text or "").split())
    if not t:
        return ""
    if str(level or "info").lower() != "warn":
        return t
    low = t.lower()
    if any(low.startswith(p) for p in _NOTICE_LEADINS):
        return t
    return f"Warning: {t}"


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

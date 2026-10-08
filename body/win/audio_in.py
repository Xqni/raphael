"""Audio input for the Windows Body.
Captures microphone PCM (16kHz mono), handles PTT gating, and streams
binary frames to the Brain per PROTOCOL §6.
"""
import asyncio
from collections import deque
import sys
import struct
from typing import Optional, Callable, Awaitable

def _require_or_die(pkg: str, pin: str):
    """SEC-9 (Wave 5H): runtime `pip install` is REMOVED. The Body must run
    in a pre-provisioned, hash-pinned environment; a missing dependency fails
    LOUD at import instead of mutating the environment at runtime."""
    try:
        return __import__(pkg)
    except ImportError as e:
        raise RuntimeError(
            f"[audio] SEC-9: required package '{pkg}=={pin}' is not installed. "
            f"Runtime pip installs are disabled — provision this environment "
            f"once from the hash-pinned manifest "
            f"(brain/voice/body-audio-requirements.txt), e.g. "
            f"'uv pip install --require-hashes -r "
            f"brain/voice/body-audio-requirements.txt', then restart the Body. "
            f"Original error: {e}") from e


_require_or_die('sounddevice', '0.5.1')
import sounddevice as sd
_require_or_die('numpy', '2.2.6')
import numpy as np

# PROTOCOL §6 binary frame constants
MAGIC = b'RAPH'
KIND_MIC = 1

class MicStreamer:
    def __init__(self, 
                 on_frame: Callable[[bytes], Awaitable[None]], 
                 on_start: Callable[[dict], Awaitable[None]], 
                 on_end: Callable[[], Awaitable[None]]):
        self.on_frame = on_frame
        self.on_start = on_start
        self.on_end = on_end
        self.sample_rate = 16000
        self.channels = 1
        self.is_capturing = False
        self._seq = 0

    def _encode_frame(self, payload: bytes) -> bytes:
        # [4-byte magic "RAPH"][u8 kind][u32 seq][payload]
        # u32 seq is BIG-ENDIAN per brain/voice/__init__.py
        return MAGIC + struct.pack('>BI', KIND_MIC, self._seq) + payload

    async def start_capture(self, reason: str = 'ptt'):
        if self.is_capturing:
            return
        self.is_capturing = True
        self._seq = 0
        
        # Send audio_start frame per PROTOCOL §3
        await self.on_start({
            "type": "audio_start",
            "v": 1,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "encoding": "pcm_s16le",
            "reason": reason
        })

        # Use a queue to bridge sounddevice callback to asyncio.
        # THREAD-SAFETY: the sounddevice callback runs on ITS OWN thread —
        # asyncio.Queue is not thread-safe, so hop onto the loop first.
        self.queue = asyncio.Queue()
        self._loop = asyncio.get_running_loop()

        def callback(indata, frames, time, status):
            if status:
                print(f"[audio_in] SD status: {status}", file=sys.stderr)
            # Convert float32 to pcm_s16le
            audio_int16 = (indata * 32767).astype(np.int16)
            self._loop.call_soon_threadsafe(self.queue.put_nowait,
                                            audio_int16.tobytes())

        try:
            with sd.InputStream(samplerate=self.sample_rate, 
                                channels=self.channels, 
                                dtype='float32', 
                                callback=callback):
                while self.is_capturing:
                    chunk = await self.queue.get()
                    frame = self._encode_frame(chunk)
                    await self.on_frame(frame)
                    self._seq += 1
        except Exception as e:
            print(f"[audio_in] Stream error: {e}", file=sys.stderr)
        finally:
            self.is_capturing = False

    async def stop_capture(self):
        self.is_capturing = False
        await self.on_end()

class VadSegmenter:
    """Pure voice-activity state machine (no device I/O -> unit-testable).

    Adaptive noise floor + thresholds -> utterance boundaries:
      feed(chunk_bytes) -> ('pre'|'speech'|'end', chunk)
    'pre'  = below-threshold chunk kept as pre-roll (word onset lives here)
    'speech' = voiced chunk (forward to the brain inside a segment)
    'end'  = emitted once when silence hangover closes an utterance
    """

    SPEECH_MIN = 2      # >=200ms above threshold to open a segment
    SILENCE_CLOSE = 25  # >=2.5s silent -> close (CONVERSATIONAL: natural
                        # thinking pauses must not split an utterance;
                        # adds ~2.5s latency before transcription)
    MIN_LEN = 3         # discard segments <300ms (clicks/blips)
    MAX_LEN = 600       # force-close at 60s (long REQUESTS allowed; was 20s = hard mid-sentence chop)
    NOISE_EMA = 0.93    # quiet-level tracker (only updates when quiet)
    MULT = 3.5          # trigger = max(ABS_FLOOR, noise*3.5)
    ABS_FLOOR = 80      # int16 RMS (measured: ambient 20, speaker-fed
                        # playback chunks 40-225 peaky, real speech 2000+)
    # NOTE: measured data killed the naive rule — speech RMS is PEAKY
    # (225,64,143,81...) so thresholds must clear the valleys, not peaks.
    ECHO_OPEN_RMS = 400  # echo guard (Wave 2 task 2): while Raphael is
                        # speaking, a new segment must reach SPEECH-level
                        # energy to open — her playback (measured 40-225 at
                        # the mic) can't self-trigger, real user speech
                        # (measured 2000+) opens normally (barge-in works).
                        # Only affects OPENING; open-segment hysteresis below
                        # is untouched (live-tested behavior preserved).

    def __init__(self):
        self.noise = self.ABS_FLOOR
        # Windowed evidence (measured speech RMS is peaky: 225,64,143,81...
        # — consecutive-run rules NEVER fire through the valleys). Open on
        # >=2 hits in the last 5 chunks; a single click = 1 hit = rejected.
        self._hits = deque(maxlen=5)
        self._below = 0
        self.open = False
        self._len = 0
        self._pre = []          # pre-roll deque (last2 chunks)
        self.seen_segments = 0
        self.echo_guard = False  # True while TTS playback is active (audio_out)

    @staticmethod
    def _rms(chunk: bytes) -> float:
        import numpy as _np
        x = _np.frombuffer(chunk, dtype='<i2')
        if x.size == 0:
            return 0.0
        return float(_np.sqrt(_np.mean(_np.square(x.astype(_np.float64)))))

    def feed(self, chunk: bytes):
        rms = self._rms(chunk)
        thr = max(self.ABS_FLOOR, self.noise * self.MULT)
        events = []

        if not self.open:
            # Echo guard: while Raphael's TTS is playing, her voice must not
            # open a segment (self-trigger). Only OPENING is guarded — the
            # open-state hysteresis below keeps its live-tested behavior.
            open_thr = max(thr, self.ECHO_OPEN_RMS) if self.echo_guard else thr
            # track noise floor only while quiet (robust to music/talk bleed);
            # her playback is NOT ambient, so the floor freezes while guarded
            if not self.echo_guard and rms < thr:
                self.noise = self.NOISE_EMA * self.noise + (1 - self.NOISE_EMA) * rms
            self._hits.append(1 if rms >= open_thr else 0)
            self._pre.append(chunk)          # rolling pre-roll (incl. valleys)
            if len(self._pre) > 3:
                self._pre.pop(0)
            if sum(self._hits) >= 2:
                self.open = True
                self._below = 0
                self._len = 0
                # flush ALL pre-roll (the loud word-onset chunk lives here)
                for pre in self._pre:
                    events.append(('speech', pre))
                self._len += len(self._pre)
                self._pre.clear()
                self._hits.clear()
                events.insert(0, ('start', None))
        else:
            self._len += 1
            if rms >= thr * 0.6:      # hysteresis while speaking
                self._below = 0
                events.append(('speech', chunk))
            else:
                self._below += 1
                events.append(('speech', chunk))  # tail voiced-out fades via thr*0.6
                if self._below >= self.SILENCE_CLOSE or self._len >= self.MAX_LEN:
                    self.open = False
                    self._hits.clear()
                    self._pre.clear()
                    if self._len >= self.MIN_LEN:
                        self.seen_segments += 1
                        events.append(('end', None))
                    else:
                        # too short: retract everything emitted for it
                        events = [e for e in events if e[0] != 'speech']
                        # note: start already sent -> brain gets empty segment;
                        # audio_end with empty buffer = graceful early-ack ✓
                        events.append(('end', None))
        return events


class WakeStream:
    """Always-on mic -> VadSegmenter -> the same callbacks PTT used.

    audio_start carries reason='wake' -> brain's WakeGate requires the wake
    word ("Raphael, <command>"); non-wake speech is transcribed and ignored.
    """

    BLOCK_FRAMES = 1600   # 100ms @16k

    def __init__(self, on_frame, on_start, on_end, device=None,
                 log=None):
        # pythonw stdout is a PIPE -> unflushed prints vanish for minutes;
        # every wake log line must flush (found: "armed" invisible live).
        self.log = log or (lambda m: print(m, flush=True))
        self.on_frame = on_frame
        self.on_start = on_start
        self.on_end = on_end
        self.device = device
        self.vad = VadSegmenter()
        self._loop = None
        self._queue = None
        self._stop = False
        self.frames_sent = 0

    async def run(self):
        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue()  # unbounded: consumer is network-bound; QueueFull inside call_soon_threadsafe would kill the loop task
        loop = self._loop

        def callback(indata, frames, time_info, status):
            if status:
                print(f"[audio_in] wake SD status: {status}", file=sys.stderr)
            chunk = (indata[:, 0] * 32767).astype(np.int16).tobytes() \
                if indata.dtype != np.int16 else indata.tobytes()
            try:
                loop.call_soon_threadsafe(self._queue.put_nowait, chunk)
            except RuntimeError:
                pass

        try:
            stream = sd.InputStream(
                samplerate=self.sample_rate, channels=1, dtype='float32',
                blocksize=self.BLOCK_FRAMES, callback=callback,
                device=self.device)
            stream.start()
        except Exception as e:  # noqa: BLE001
            self.log(f"[audio_in] WAKE stream failed: {e}")
            return
        try:
            try:
                dev_name = str(sd.query_devices(kind="input")["name"])[:60]
            except Exception:  # noqa: BLE001
                dev_name = "default input"
            self.log(f"[audio_in] ALWAYS-LISTENING armed "
                     f"(device={dev_name}; say the wake word to be heard)")
            self._start_dict = {
                "type": "audio_start", "v": 1,
                "sample_rate": self.sample_rate, "channels": 1,
                "encoding": "pcm_s16le", "reason": "wake"}
            while not self._stop:
                chunk = await self._queue.get()
                self.vad.echo_guard = self._playback_active()
                for kind, data in self.vad.feed(chunk):
                    if kind == 'start':
                        self.log("[audio_in] wake segment OPEN "
                                 f"(noise floor {self.vad.noise:.0f})")
                        await self.on_start(dict(self._start_dict))
                    elif kind == 'speech':
                        if data is not None:
                            await self.on_frame(
                                MAGIC + struct.pack('>BI', KIND_MIC,
                                                    self.vad._len & 0xFFFFFFFF)
                                + data)
                            self.frames_sent += 1
                    elif kind == 'end':
                        self.log(f"[audio_in] wake segment CLOSE "
                                 f"(#{self.vad.seen_segments}, "
                                 f"{self.vad._len} chunks in segment)")
                        await self.on_end()
        finally:
            try:
                stream.stop()
                stream.close()
            except Exception:  # noqa: BLE001
                pass

    async def stop(self):
        self._stop = True

    @staticmethod
    def _playback_active() -> bool:
        """True while Raphael's TTS is coming out of the speaker (audio_out).
        Lazy import (module may run as body.win.audio_in or flat audio_in);
        any failure = no guard, never a dead mic task."""
        try:
            if __package__:
                from . import audio_out
            else:
                import audio_out
            return bool(audio_out.playback_active())
        except Exception:  # noqa: BLE001
            return False

    # seq per segment restarts at... keep monotonic via vad._len mod u32 ✓


    sample_rate = 16000


async def start_mic_stream(on_frame, on_start, on_end):
    """Entry point for the Body loop."""
    print('[audio_in] Microphone streamer initialized', file=sys.stderr, flush=True)
    return MicStreamer(on_frame, on_start, on_end)

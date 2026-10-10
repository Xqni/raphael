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
    LOUD at import instead of mutating the environment at runtime.

    pc-control coordination (request pc-control__to__voice__sec9-audio-pip-helpers):
    prefer the shared body helper `body/win/depfail.py` (their file, its error
    names the whole-Body manifest `body/win/requirements.txt`); fall back to
    this module's own check when depfail isn't importable (standalone/flat
    import modes) so the audio modules never hard-depend on a file we don't
    own landing first.
    """
    # Presence check = actual importability (works with real installs AND the
    # test suites' stubbed modules); only on failure do we produce the pointed
    # SEC-9 error — preferring the shared helper's message when it's around.
    try:
        return __import__(pkg)
    except ImportError:
        pass
    try:
        try:
            from . import depfail          # package mode (body.win.audio_in)
        except ImportError:
            import depfail                 # flat/script mode (same dir)
        depfail.require(pkg)               # raises: pointed SEC-9 error
    except ImportError:
        depfail = None                     # helper itself unavailable
    except RuntimeError:
        raise                              # their pointed error: propagate
    raise RuntimeError(
        f"[audio] SEC-9: required package '{pkg}=={pin}' is not installed. "
        f"Runtime pip installs are disabled — provision once from the "
        f"hash-pinned manifests: body/win/requirements.txt (whole Body, "
        f"covers these pins) or brain/voice/body-audio-requirements.txt "
        f"(linux/test hosts): 'pip install --require-hashes -r <file>', "
        f"then restart the Body.")


_require_or_die('sounddevice', '0.5.1')
import sounddevice as sd
_require_or_die('numpy', '2.2.6')
import numpy as np

# PROTOCOL §6 binary frame constants
MAGIC = b'RAPH'
KIND_MIC = 1

# AUD-24 (Wave 5H): bound the sounddevice-callback -> asyncio handoff.
# 600 chunks = 60 s of the wake stream's 100 ms frames; beyond that the
# consumer (network/brain) is stalled and the OLDEST audio is dropped —
# recency beats backlog for a mic lane, and the callback thread can never
# outrun the loop or raise QueueFull inside call_soon_threadsafe.
QUEUE_MAX_CHUNKS = 600


def _env_int(name: str, default: int, lo: int = 1, hi: int = 100) -> int:
    """P0-URGENT (coord inbox 47): SILENCE_CLOSE / CONTINUATION_GRACE are
    config-driven via env so the live latency lever needs no rebuild.

    Out-of-range / non-integer values FAIL-CLOSED to the default (a typo
    must never deafen the mic or split every clause): clamped into [lo, hi]
    after int() attempt, default on any parse error."""
    import os
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        val = int(raw)
    except ValueError:
        return default
    return max(lo, min(hi, val))


def _enqueue_bounded(queue, chunk, stats: dict) -> None:
    """Drop-oldest bounded put (runs on the LOOP thread — queue ops stay
    single-threaded). Never raises; every drop is counted + rate-limited
    to the log (1st, then every 500th)."""
    if queue.full():
        try:
            queue.get_nowait()               # drop the OLDEST chunk
        except Exception:  # noqa: BLE001 — QueueEmpty under a race
            pass
        stats["dropped"] = stats.get("dropped", 0) + 1
        d = stats["dropped"]
        if d == 1 or d % 500 == 0:
            print(f"[audio_in] mic queue full (max {queue.maxsize}) — "
                  f"dropped oldest chunk (total dropped: {d})", flush=True)
    try:
        queue.put_nowait(chunk)
    except Exception:  # noqa: BLE001 — full again under a race
        stats["dropped"] = stats.get("dropped", 0) + 1


class EndGrace:
    """Deferred audio_end + continuation decision (Cut A 2026-10-08).

    Pure state machine (unit-tested, no device): the VAD's `end` event is a
    CANDIDATE close — `audio_end` is held for `grace_chunks` so a resume
    inside the window becomes reason='continuation' (brain appends: ONE
    transcription of part1+part2, brain tests/test_sec3_cloud_stt_gate.py
    contract) instead of splitting the command. Grace expiry fires the end.

      vad_end()            -> hold begins (VAD closed after SILENCE_CLOSE)
      vad_start() -> True  -> resume inside window: hold cancelled, caller
                              sends the continuation start
      tick() -> True       -> hold expired: caller sends audio_end
    """

    def __init__(self, grace_chunks: int):
        self.grace = int(grace_chunks)
        self.held = False
        self.left = 0

    def vad_end(self) -> None:
        self.held = True
        self.left = self.grace

    def vad_start(self) -> bool:
        if self.held:
            self.held = False
            self.left = 0
            return True                    # -> continuation
        return False

    def tick(self) -> bool:
        if not self.held:
            return False
        self.left -= 1
        if self.left <= 0:
            self.held = False
            return True                    # -> fire audio_end
        return False

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
        # AUD-24: bounded drop-oldest — the callback must never grow without
        # limit nor raise QueueFull inside call_soon_threadsafe.
        self.queue = asyncio.Queue(maxsize=QUEUE_MAX_CHUNKS)
        self._drop_stats = {}
        self._loop = asyncio.get_running_loop()

        def callback(indata, frames, time, status):
            if status:
                print(f"[audio_in] SD status: {status}", file=sys.stderr)
            # Convert float32 to pcm_s16le
            audio_int16 = (indata * 32767).astype(np.int16)
            self._loop.call_soon_threadsafe(_enqueue_bounded, self.queue,
                                            audio_int16.tobytes(),
                                            self._drop_stats)

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
    SILENCE_CLOSE = _env_int("RAPHAEL_SILENCE_CLOSE", 12)  # >=N*100ms silent
                        # -> CANDIDATE close (Cut A 2026-10-08; brain-core
                        # utt-continuation-merge MERGED): audio_end is then
                        # HELD for CONTINUATION_GRACE so a resume inside the
                        # window APPENDS on the brain side instead of
                        # splitting. close(12)+grace(13)=25 chunks = the OLD
                        # 2.5s worst-case end latency and the old no-split
                        # coverage -> ZERO split regressions (accepted target).
    CONTINUATION_GRACE = _env_int("RAPHAEL_CONTINUATION_GRACE", 8)  # chunks
                        # (x100ms = 0.8s, was 1.3s) held before audio_end
                        # fires; a 'start' inside the window cancels the held
                        # end and sends reason='continuation' instead.
                        # P0-URGENT (coord inbox 47, user: 'huge delay'):
                        # 13->8 trims perceived speech->subtitle by ~0.5-0.7s
                        # immediately (worst-case end latency drops ~0.5s).
                        # TRADEOFF, honest: the no-split merge window shrinks
                        # 1.3s->0.8s, so a resume gap longer than 0.8s now
                        # SPLITS into a second utterance instead of appending
                        # (brain merges only within the window). Measured
                        # human pause between clauses stays well under 0.8s,
                        # so real barge-in/resume still merges; only a >0.8s
                        # hesitation can split. Override via
                        # RAPHAEL_CONTINUATION_GRACE=13 to restore the old
                        # window without a rebuild.
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

    def __init__(self, silence_close: Optional[int] = None,
                 continuation_grace: Optional[int] = None):
        # P0-URGENT (coord inbox 47): close/grace are per-instance override-
        # able (tests parameterize them); class defaults are the env-driven
        # config values (_env_int) -> main runs grace=8 (0.8s hold).
        self.SILENCE_CLOSE = (int(silence_close) if silence_close is not None
                              else self.SILENCE_CLOSE)
        self.CONTINUATION_GRACE = (
            int(continuation_grace) if continuation_grace is not None
            else self.CONTINUATION_GRACE)
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
    # Cut A live-bug fix (integrator glue 2026-10-09, voice-owned file): the
    # grace hold at the run loop referenced self.CONTINUATION_GRACE which only
    # existed on VadSegmenter -> AttributeError killed the wake task at startup
    # ("wake task died") and the mic went deaf. One source of truth:
    CONTINUATION_GRACE = VadSegmenter.CONTINUATION_GRACE

    def __init__(self, on_frame, on_start, on_end, device=None,
                 log=None, continuation_grace: Optional[int] = None):
        # pythonw stdout is a PIPE -> unflushed prints vanish for minutes;
        # every wake log line must flush (found: "armed" invisible live).
        self.log = log or (lambda m: print(m, flush=True))
        self.on_frame = on_frame
        self.on_start = on_start
        self.on_end = on_end
        self.device = device
        self.vad = VadSegmenter(continuation_grace=continuation_grace)
        # P0-URGENT (coord inbox 47): the grace window is the instance's own
        # (mirrors the vad we just built) — main default grace=8 (0.8s hold)
        # so perceived speech->subtitle drops ~0.5-0.7s. Class attr kept as
        # the config default for any construction that doesn't override.
        self.CONTINUATION_GRACE = self.vad.CONTINUATION_GRACE
        self._loop = None
        self._queue = None
        self._stop = False
        self.frames_sent = 0

    async def run(self):
        self._loop = asyncio.get_running_loop()
        # AUD-24: bounded drop-oldest (was: unbounded — a stalled consumer
        # would let the callback thread grow memory without limit; a bare
        # put_nowait would raise QueueFull inside call_soon_threadsafe)
        self._queue = asyncio.Queue(maxsize=QUEUE_MAX_CHUNKS)
        self._drop_stats = {}
        loop = self._loop

        def callback(indata, frames, time_info, status):
            if status:
                print(f"[audio_in] wake SD status: {status}", file=sys.stderr)
            chunk = (indata[:, 0] * 32767).astype(np.int16).tobytes() \
                if indata.dtype != np.int16 else indata.tobytes()
            try:
                loop.call_soon_threadsafe(_enqueue_bounded, self._queue,
                                          chunk, self._drop_stats)
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
            self._cont_dict = dict(self._start_dict, reason="continuation")
            grace = EndGrace(self.CONTINUATION_GRACE)
            while not self._stop:
                chunk = await self._queue.get()
                self.vad.echo_guard = self._playback_active()
                events = self.vad.feed(chunk)
                start_seen = False
                for kind, data in events:
                    if kind == 'start':
                        start_seen = True
                        if grace.vad_start():
                            # Cut A: resume inside the grace window -> the
                            # brain APPENDS to the open utterance (no split)
                            self.log("[audio_in] resume within grace -> "
                                     "continuation (append)")
                            await self.on_start(dict(self._cont_dict))
                        else:
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
                        # candidate close: HOLD the audio_end for the grace
                        # window (resume -> continuation; expiry -> end)
                        grace.vad_end()
                        self.log(f"[audio_in] wake segment CLOSE(held) "
                                 f"(#{self.vad.seen_segments}, "
                                 f"{self.vad._len} chunks, grace="
                                 f"{grace.left})")
                if not start_seen and grace.tick():
                    self.log("[audio_in] grace expired -> audio_end")
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

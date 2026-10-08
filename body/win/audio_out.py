"""Audio output for the Windows Body — CONTINUOUS stream playback.

PROTOCOL §6: kind=2 binary frames carry PCM s16le @24 kHz (chunk_ms slices).
The old player called sd.play() PER CHUNK with sleep-based pacing — every
chunk paid PortAudio stream-open latency and the sleeps never matched real
playback time, so replies came out as 'im....a.....g...pp...' stutter (user
report, 2026-10-05). This version opens ONE OutputStream whose callback
drains a shared buffer: chunks concatenate seamlessly; a short pre-buffer
absorbs network jitter; underruns render as silence instead of clicks.
"""
import asyncio
import sys
import threading
import time

import numpy as np
import sounddevice as sd

RATE_DEFAULT = 24000          # PROTOCOL §3 speak sample_rate
PREBUF_S = 0.25               # start rendering once this much is buffered
DRAIN_POLL_S = 0.05           # finish() poll while the tail drains
DRAIN_TIMEOUT_S = 5.0         # never hang a job on a stuck buffer
STALE_RESET_S = 2.5           # reset() only drops audio OLDER than this


class StreamPlayer:
    """Buffered float32 mono OutputStream; feed() from the async side,
    callback drains on PortAudio's thread (lock-guarded)."""

    def __init__(self, rate: int = RATE_DEFAULT):
        self.rate = rate
        self._buf = bytearray()
        self._lock = threading.Lock()
        self._stream = None
        self._playing = False
        self.chunks = 0
        self.bytes_in = 0
        self.bytes_out = 0
        self.underruns = 0
        self.dropped = 0            # bytes thrown away (P0 loss accounting)
        self.kept = 0               # bytes PRESERVED across a speak start
        self._last_feed_ts = 0.0

    # -- producer side -----------------------------------------------------
    def feed(self, pcm: bytes):
        if not pcm:
            return
        with self._lock:
            self._buf += pcm
            self.bytes_in += len(pcm)
            self.chunks += 1
            self._last_feed_ts = time.monotonic()
            prebuffered = len(self._buf) >= int(PREBUF_S * self.rate * 2)
        if self._stream is None and prebuffered:
            self._open()

    def reset(self):
        """speak 'start' — begin a new utterance.

        P0 (2026-10-07): must NOT drop audio that is still draining. The body
        handles `end` as a detached task, so the NEXT sentence's `start` can
        arrive while the previous tail is still buffered — the old
        clear-here threw away up to 42% of an utterance (user report:
        "she is not speaking anymore"). Pending audio younger than
        STALE_RESET_S is KEPT (consecutive sentences play continuously);
        only genuinely stale leftovers (nothing fed for 2.5 s) are dropped —
        and counted in `dropped`.
        """
        with self._lock:
            stale = (not self._buf) or (
                time.monotonic() - self._last_feed_ts > STALE_RESET_S)
            if stale:
                self.dropped += len(self._buf)
                self._buf.clear()
            else:
                self.kept += len(self._buf)     # continuous utterance
            self._playing = False

    async def finish(self, tail: float = 1.0):
        """speak 'end' — flush whatever is buffered, then close cleanly."""
        # if end raced ahead of chunks (sub-prebuffer utterance), open anyway
        with self._lock:
            has_data = bool(self._buf)
        if has_data and self._stream is None:
            self._open()
        # Long replies arrive as BURSTS (brain pushes chunks back-to-back);
        # the fixed 5s budget truncated them mid-sentence (in!=out — user
        # heard chopped audio). Budget scales with buffered audio at ~1.5x
        # realtime: healthy drains never expire; a dead device still bounds out.
        with self._lock:
            _buffered = len(self._buf)
        deadline = (asyncio.get_event_loop().time() + 4
                    + (_buffered / max(1, self.rate * 2)) * 1.5 + 3)
        expired = False
        while True:
            with self._lock:
                empty = not self._buf
            if empty:
                break
            if asyncio.get_event_loop().time() > deadline:
                expired = True
                break
            await asyncio.sleep(DRAIN_POLL_S)
        if expired:
            # device stalled: give up LOUDLY and account for the loss — never
            # leave a dead tail to bleed into the next utterance
            with self._lock:
                left = len(self._buf)
                self.dropped += left
                self._buf.clear()
            print(f"[audio_out] drain deadline expired — dropped {left}B "
                  f"(device stalled?)", flush=True)
        await asyncio.sleep(min(tail, 0.5))  # let the last callback pull
        self._close()

    # -- device lifecycle --------------------------------------------------
    def _callback(self, outdata, frames, time_info, status):
        with self._lock:
            take = min(frames * 2, len(self._buf)) & ~1  # whole int16 samples
            if take:
                pcm = np.frombuffer(bytes(self._buf[:take]), dtype='<i2')
                del self._buf[:take]
                self.bytes_out += take
            else:
                pcm = None
                if self._playing:
                    self.underruns += 1
        if pcm is None:
            outdata[:frames, 0] = 0.0
            return
        n = len(pcm)
        outdata[:n, 0] = pcm.astype(np.float32) / 32768.0
        if n < frames:
            outdata[n:, 0] = 0.0
        self._playing = True

    def _open(self):
        if self._stream is not None:
            return
        try:
            self._stream = sd.OutputStream(
                samplerate=self.rate, channels=1, dtype='float32',
                blocksize=0, callback=self._callback)
            self._stream.start()
        except Exception as e:  # noqa: BLE001 — device issues must not crash
            print(f"[audio_out] stream open failed: {e}", file=sys.stderr,
                  flush=True)
            self._stream = None

    def _close(self):
        st, self._stream = self._stream, None
        self._playing = False
        if st is not None:
            try:
                st.stop()
                st.close()
            except Exception as e:  # noqa: BLE001
                print(f"[audio_out] stream close: {e}", file=sys.stderr,
                      flush=True)

    def stats(self) -> dict:
        with self._lock:
            return {'chunks': self.chunks, 'bytes_in': self.bytes_in,
                    'bytes_out': self.bytes_out, 'underruns': self.underruns,
                    'dropped': self.dropped, 'kept': self.kept,
                    'buffered': len(self._buf)}

    def active(self) -> bool:
        """True while Raphael's voice is (or is about to be) coming out of the
        speaker. The mic lane (audio_in) uses this for echo suppression: while
        she speaks, the VAD only opens on speech-LEVEL energy, so her own
        playback can't re-trigger the wake chain — but the user talking over
        her still opens a segment (barge-in keeps working)."""
        with self._lock:
            return self._stream is not None and (bool(self._buf) or self._playing)


# module singleton — one device handle for the whole body process
PLAYER = StreamPlayer()


def playback_active() -> bool:
    """True while TTS audio is being rendered (echo-suppression signal for
    audio_in.WakeStream). Safe to call from the asyncio side any time."""
    return PLAYER.active()


# -- legacy/simple API (ws binary path calls this) --------------------------
async def play_tts_chunk(chunk: bytes, sample_rate: int = RATE_DEFAULT):
    PLAYER.feed(chunk)


def speak_start():
    PLAYER.reset()


async def speak_end():
    await PLAYER.finish()
    st = PLAYER.stats()
    print(f"[audio_out] utterance done: {st['chunks']} chunks, "
          f"in={st['bytes_in']}B out={st['bytes_out']}B "
          f"underruns={st['underruns']}", flush=True)


class AudioPlayer:  # backwards-compat shim (old name)
    def __init__(self, sample_rate: int = RATE_DEFAULT):
        self.sample_rate = sample_rate

    async def play_chunk(self, chunk: bytes):
        PLAYER.feed(chunk)

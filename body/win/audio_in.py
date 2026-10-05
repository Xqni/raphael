"""Audio input for the Windows Body.
Captures microphone PCM (16kHz mono), handles PTT gating, and streams
binary frames to the Brain per PROTOCOL §6.
"""
import asyncio
import sys
import struct
from typing import Optional, Callable, Awaitable

def _ensure_pkg(pkg: str, import_name: str = None, pin: str = ''):
    try:
        __import__(import_name or pkg)
    except ImportError:
        import subprocess
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--quiet', 
                                ('%s==%s' % (pkg, pin)) if pin else pkg])
        __import__(import_name or pkg)

_ensure_pkg('sounddevice', pin='0.5.1')
import sounddevice as sd
_ensure_pkg('numpy', pin='2.2.6')  # was imported bare (compile-only test hid it)
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

async def start_mic_stream(on_frame, on_start, on_end):
    """Entry point for the Body loop."""
    print('[audio_in] Microphone streamer initialized', file=sys.stderr, flush=True)
    return MicStreamer(on_frame, on_start, on_end)

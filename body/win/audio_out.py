"""Audio output for the Windows Body.
Plays back PCM (24kHz mono) chunks received from the Brain per PROTOCOL §6.
"""
import asyncio
import sys

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
import numpy as np

class AudioPlayer:
    def __init__(self, sample_rate: int = 24000):
        self.sample_rate = sample_rate

    async def play_chunk(self, chunk: bytes):
        # Binary frames arrive as [RAPH][kind=2][seq u32][payload]
        # We strip the header if passed as a full frame, but usually’s passed as payload
        # For now, we assume this is the raw PCM payload.
        try:
            audio_data = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0
            # Non-blocking playback using sounddevice
            sd.play(audio_data, self.sample_rate)
            # Wait for the chunk to finish playing to avoid overlaps/gaps in streaming
            # (In a real production driver we'd use a stream buffer)
            await asyncio.sleep(len(audio_data) / self.sample_rate)
        except Exception as e:
            print(f"[audio_out] Playback error: {e}", file=sys.stderr)

async def play_tts_chunk(chunk: bytes, sample_rate: int = 24000):
    """Convenience wrapper."""
    player = AudioPlayer(sample_rate)
    await player.play_chunk(chunk)

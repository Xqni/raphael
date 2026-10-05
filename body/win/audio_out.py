"""Audio output stub for the Windows Body.

Plays back PCM (24 kHz mono) chunks received from the Brain. The current
implementation simply acknowledges receipt via a log statement.
"""
import asyncio
import sys

async def play_tts_chunk(chunk: bytes, sample_rate: int = 24000):
    print(f'[audio_out] Received TTS chunk ({len(chunk)} bytes) at {sample_rate} Hz', file=sys.stderr, flush=True)
    # Real implementation would feed the PCM to the default audio device.
    await asyncio.sleep(0)  # no‑op placeholder

if __name__ == '__main__':
    # Demo – read a file and pretend to play.
    import pathlib
    data = pathlib.Path('test_tts.pcm').read_bytes() if pathlib.Path('test_tts.pcm').exists() else b''
    asyncio.run(play_tts_chunk(data))

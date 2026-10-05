"""Audio input stub for the Windows Body.

Future implementation will capture microphone PCM (16 kHz mono) and stream
binary frames to the Brain. For now we expose a coroutine that logs its
invocation – the protocol will treat the missing audio as a no‑op.
"""
import asyncio
import sys

async def start_mic_stream():
    print('[audio_in] microphone streaming stub started', file=sys.stderr, flush=True)
    # In a real implementation we would open the default audio device and
    # feed PCM chunks to the WS binary protocol.
    while True:
        await asyncio.sleep(1)

if __name__ == '__main__':
    asyncio.run(start_mic_stream())

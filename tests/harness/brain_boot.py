"""Hermetic brain subprocess boot (qa-security harness).

Spawned by tests/regression/test_instance_isolation.py as
`python tests/harness/brain_boot.py` with RAPHAEL_* env vars. Runs uvicorn
on the given host/port after installing SAFETY patches:

- builtins.open guard: the MAIN instance pidfile /tmp/raphael-brain.pid is
  never written from a test (app.py catches the resulting OSError);
- TTS/STT mocked at class level BEFORE brain import: no Fish-Speech spawn,
  no faster-whisper load, no port 8777 contact (AGENT_RULES §5).

Everything else is the REAL brain app — that is the point of the test.
"""
import builtins
import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

# --- 1) never touch MAIN's pidfile -----------------------------------------
_real_open = builtins.open


def _guarded_open(file, mode='r', *args, **kwargs):
    m = str(mode)
    if ('w' in m) or ('a' in m) or ('+' in m):
        if str(file) == '/tmp/raphael-brain.pid':
            raise OSError('qa-security harness: pidfile write blocked')
    return _real_open(file, mode, *args, **kwargs)


builtins.open = _guarded_open

# --- 2) mock voice BEFORE any brain import ---------------------------------
from brain.voice.tts import TTSEngine, FishSpeechServer, TTSError  # noqa: E402


async def _warmup(self):
    return None


async def _ensure_started(self, *a, **k):
    raise TTSError('E_LOCAL_DOWN', 'qa-security harness: TTS mocked')


async def _speak(self, text, *, job=None, cancel=None, force_fallback=False):
    yield {'type': 'speak', 'v': 1, 'job': job, 'seq': 0, 'event': 'start',
           'sample_rate': 24000, 'text': text, 'cached': False,
           'engine': 'mock'}
    yield {'type': 'speak', 'v': 1, 'job': job, 'seq': 1, 'event': 'end',
           'sample_rate': 24000, 'cached': False, 'engine': 'mock'}


TTSEngine.warmup = _warmup
TTSEngine.speak = _speak
FishSpeechServer.ensure_started = _ensure_started

# --- 3) run ----------------------------------------------------------------
import uvicorn  # noqa: E402

if __name__ == '__main__':
    host = os.environ.get('RAPHAEL_BIND', '127.0.0.1')
    port = int(os.environ.get('RAPHAEL_PORT', '8765'))
    uvicorn.run('brain.app:app', host=host, port=port, log_level='warning')

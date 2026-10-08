import os

# starlette TestClient cannot decode binary frames (UTF-8) — opt tests
# OUT of binary TTS; production keeps it ON (see brain/loop.py).
os.environ.setdefault("RAPHAEL_DISABLE_BINARY_TTS", "1")

"""Shared test isolation: point the memory DB at a TEMP file and disable the
router so tests never touch brain/memory/memory.db or the network.
(RAPHAEL_TOKEN_PATH stays a per-module fixture — see tests/test_health.py.)
"""
import os
import tempfile
from pathlib import Path

_fd, _db = tempfile.mkstemp(prefix='raphael-test-db-')
os.close(_fd)
os.environ['RAPHAEL_DB_PATH'] = _db
os.environ.setdefault('RAPHAEL_DISABLE_ROUTER', '1')
os.environ.setdefault('RAPHAEL_CONFIRM_TIMEOUT_S', '2')

import pytest  # noqa: E402


# ---- hermetic TTS: a lane test must NEVER touch or spawn a real Fish server
# (INTERFACES §d: "voice tests mock TTS"). A live fish on :8777 made speak-
# bound tests slow/flaky (real GPU synthesis) and without one, warmup would
# SPAWN it (up to 240 s) — a hard rules violation. Mock at the VoiceStack
# seam so fanout/frame-shape assertions still run against the real loop.
async def _fake_speak(self, text, *, job=None, cancel=None,
                      force_fallback=False):
    rate = int(getattr(getattr(self, 'cfg', None), 'tts_sample_rate', 24000))
    yield {"type": "speak", "v": 1, "job": job, "seq": 0, "event": "start",
           "sample_rate": rate, "text": text, "cached": True, "engine": "mock"}
    yield {"type": "speak", "v": 1, "job": job, "seq": 1, "event": "end",
           "sample_rate": rate, "cached": True, "engine": "mock"}


async def _fake_warmup(self):
    return None


@pytest.fixture(autouse=True)
def _orb_transient_state():
    """Cross-test isolation: the orb error-linger window / listening /
    speaking counters are module globals — clear them around every test so a
    failure window can't leak 'error' into an unrelated state assertion."""
    try:
        from brain import orbstate
        orbstate.reset_transient_for_tests()
        yield
        orbstate.reset_transient_for_tests()
    except Exception:  # noqa: BLE001 — never block a test on this
        yield


@pytest.fixture(autouse=True)
def _hermetic_tts(monkeypatch, request):
    """Patch VoiceStack.speak/warmup PER TEST, only for tests under brain/tests.

    Two leaks fixed (both seen in the merged-main combined run
    brain/tests + brain/voice/tests, voice failing 4x):
    1. The original import-time permanent patch stayed on the class for the
       whole process — voice's own tests (REAL chunk frames from their
       FakeFish) then saw the fake start/end-only generator.
    2. A plain function-scoped fixture is not enough either: when pytest's
       rootdir inference makes this conftest a session-level fixture
       (baseid=''), it also runs for tests OUTSIDE brain/tests. The physical
       path guard below makes the mock follow the TEST's location, not
       pytest's conftest scoping.
    """
    try:
        test_path = Path(str(request.node.path)).resolve()
    except Exception:  # noqa: BLE001 — no path info: stay hermetic-skip
        yield
        return
    if not test_path.is_relative_to(Path(__file__).resolve().parent):
        # not a brain/tests test (e.g. brain/voice/tests in a combined run):
        # they need the REAL VoiceStack.speak — do not touch it.
        yield
        return
    try:
        from brain.voice import VoiceStack
        monkeypatch.setattr(VoiceStack, 'speak', _fake_speak)
        monkeypatch.setattr(VoiceStack, 'warmup', _fake_warmup)
    except Exception as _e:  # noqa: BLE001 — loud: hermeticity must not fail silent
        print(f'[conftest] TTS mock NOT installed: {type(_e).__name__}: {_e}',
              flush=True)
    yield


@pytest.fixture(scope='session', autouse=True)
def _cleanup_db():
    yield
    for p in (_db, _db + '-wal', _db + '-shm'):
        try:
            os.remove(p)
        except OSError:
            pass

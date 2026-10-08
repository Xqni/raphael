"""AUD-05 foreground push (pc-control half): frame shape, dedupe, retry,
lock-free guarantee, <100 ms local latency, watcher fallback (mocked
Windows layer — no real hooks, no input, no sockets)."""
import asyncio
import json
import time

import pytest

from body.win import automation, foreground, ws_client

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _fg_reset():
    foreground.reset()
    yield
    foreground.reset()


class Sender:
    """Captures pushed frames; can be told to fail or raise."""

    def __init__(self, ok: bool = True, raise_exc: bool = False):
        self.frames = []
        self.ok = ok
        self.raise_exc = raise_exc

    async def send(self, frame):
        if self.raise_exc:
            raise RuntimeError('sender exploded')
        self.frames.append(frame)
        return self.ok


async def test_build_frame_shape_and_lock_free(fake):
    frame = foreground.build_frame(force=True)
    assert frame['type'] == 'foreground' and frame['v'] == 1
    assert isinstance(frame['ts'], int) and frame['ts'] > 0
    assert set(frame['window']) == {'hwnd', 'title', 'process', 'pid'}
    assert frame['window']['hwnd'] == 1001        # FakeWin default fg
    assert not automation.lock_held()


async def test_build_frame_null_when_unverifiable(fake):
    fake.foreground_window = None
    frame = foreground.build_frame(force=True)
    assert frame['window'] is None                # gate must stay fail-closed


async def test_push_dedupe_change_and_force(fake):
    sender = Sender()
    foreground.set_sender(sender.send)

    first = await foreground.push(force=True)     # connect snapshot
    assert first is not None and len(sender.frames) == 1
    again = await foreground.push()               # unchanged -> deduped
    assert again is None and len(sender.frames) == 1

    fake.foreground_window = fake.windows[1]      # focus change -> push
    changed = await foreground.push()
    assert changed is not None and len(sender.frames) == 2
    assert sender.frames[-1]['window']['hwnd'] == 1002

    forced = await foreground.push(force=True)    # resync refreshes even
    assert forced is not None and len(sender.frames) == 3


async def test_push_never_touches_the_input_lock(fake, monkeypatch):
    """Lock-free guarantee (AUD-05): if anything tried to take the lock,
    this test would blow up."""
    async def _boom(*_a, **_k):
        raise AssertionError('foreground push must never acquire the lock')

    monkeypatch.setattr(automation, 'acquire_input_lock', _boom)
    foreground.set_sender(Sender().send)
    assert await foreground.push(force=True) is not None
    assert await foreground.check_once(force=True) is not None


async def test_push_latency_under_100ms(fake):
    sender = Sender()
    foreground.set_sender(sender.send)
    await foreground.push(force=True)
    fake.foreground_window = fake.windows[1]
    t0 = time.monotonic()
    frame = await foreground.check_once()
    elapsed = time.monotonic() - t0
    assert frame is not None
    assert elapsed < 0.1, 'push path took %.3fs (>100ms budget)' % elapsed
    assert sender.frames[-1]['window']['hwnd'] == 1002


async def test_failed_send_is_retried(fake):
    sender = Sender(ok=False)
    foreground.set_sender(sender.send)
    assert await foreground.push(force=True) is None
    # dedupe NOT recorded on failure -> the next tick attempts the same change
    assert await foreground.push() is None
    assert len(sender.frames) == 2, 'failed send must be retried, not deduped'

    raiser = Sender(raise_exc=True)
    foreground.set_sender(raiser.send)
    assert await foreground.push(force=True) is None   # swallowed, no crash
    ok = Sender()
    foreground.set_sender(ok.send)
    assert await foreground.push() is not None         # retried after failure
    assert len(ok.frames) == 1


async def test_ws_client_send_frame_offline_and_online(fake):
    ws_client._current_ws = None
    frame = {'type': 'foreground', 'v': 1, 'ts': 1, 'window': None}
    assert await ws_client._send_frame(frame) is False    # disconnected

    class _WS:
        def __init__(self):
            self.sent = []

        async def send(self, raw):
            self.sent.append(json.loads(raw))

    ws = _WS()
    ws_client._current_ws = ws
    try:
        assert await ws_client._send_frame(frame) is True
        assert ws.sent == [frame]
    finally:
        ws_client._current_ws = None


async def test_start_falls_back_to_poll_without_hook(fake, monkeypatch):
    """Non-Windows / hook failure -> 1s poll + 30s resync tasks, reported."""
    import body.win.foreground as fg
    monkeypatch.setattr(fg, 'os_name', lambda: 'posix')    # never hooks here
    try:
        diag = fg.start(asyncio.get_running_loop())
        assert diag == {'hook': False, 'poll': True}
        again = fg.start(asyncio.get_running_loop())       # idempotent
        assert again == {'hook': False, 'poll': True}
        sender = Sender()
        fg.set_sender(sender.send)
        await fg.check_once(force=True)                    # sampler path works
        assert len(sender.frames) == 1, 'poll-mode sampler must push'
    finally:
        fg.reset()                                         # cancel watcher tasks
        await asyncio.sleep(0)                             # let them settle


async def test_check_once_feeds_the_ring_shape(fake):
    """End-to-end local leg: backend -> frame -> sender, identity fields the
    brain-core consumer folds into record_foreground('title | process')."""
    sender = Sender()
    foreground.set_sender(sender.send)
    await foreground.check_once(force=True)
    win = sender.frames[-1]['window']
    identity = '%s | %s' % (win.get('title', ''), win.get('process', ''))
    assert identity == 'Untitled - Notepad | notepad.exe'

"""Conversation-turn capture tests (brain-core producer seam, ACCEPTED contract).

Hermetic: temp DB via conftest, no network, no real runtime DB.
Deterministic by default: the background flusher is disabled per test
(yielded `real_ensure` lets the bg-thread test re-enable it).
"""
import inspect
import time

import pytest

from brain.memory import conversation


@pytest.fixture(autouse=True)
def _disable_background_flusher(monkeypatch):
    """Tests drive persistence via flush() — only the bg-thread test opts in."""
    real_ensure = conversation._ensure_flusher
    monkeypatch.setattr(conversation, '_ensure_flusher', lambda: None)
    yield real_ensure


def test_signature_matches_accepted_contract():
    """Exact signature brain-core codes against: keyword-only, same params."""
    sig = inspect.signature(conversation.on_turn)
    params = list(sig.parameters)
    assert params == ['user', 'assistant', 'job', 'task_kind', 'ts']
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for p in sig.parameters.values())
    assert sig.parameters['user'].default is inspect.Parameter.empty
    assert sig.parameters['assistant'].default is inspect.Parameter.empty
    with pytest.raises(TypeError):          # positional call must fail
        conversation.on_turn('u', 'a')      # type: ignore[misc]


def test_on_turn_buffers_then_persists_on_flush():
    out = conversation.on_turn(user='what time is it', assistant='14:02',
                               job='j_20261007_0001', task_kind='system')
    assert out is None
    # O(1) job path: nothing hit the DB synchronously (buffer-only contract)
    assert conversation.buffered() == 1
    assert conversation.turn_count() == 0
    assert conversation.flush() == 1
    assert conversation.buffered() == 0
    rows = conversation.recent_turns(limit=5)
    assert len(rows) == 1
    r = rows[0]
    assert r['user'] == 'what time is it'
    assert r['assistant'] == '14:02'
    assert r['job'] == 'j_20261007_0001'
    assert r['task_kind'] == 'system'
    assert isinstance(r['ts'], int) and r['ts'] > 0


def test_on_turn_fail_silent_when_persist_broken(monkeypatch):
    """A broken DB must drop the turn, never raise into the conversation."""
    def _boom(_batch):
        raise RuntimeError('db corrupt')
    monkeypatch.setattr(conversation, '_persist', _boom)
    assert conversation.on_turn(user='u', assistant='a') is None   # no raise
    assert conversation.flush() == 1                               # swallowed path


def test_on_turn_fail_silent_when_flusher_start_broken(monkeypatch):
    """Even a thread that cannot start must not surface an error."""
    def _boom_start():
        raise RuntimeError('cannot spawn thread')
    monkeypatch.setattr(conversation, '_ensure_flusher', _boom_start)
    assert conversation.on_turn(user='u', assistant='a') is None   # inside try
    assert conversation.buffered() == 1                            # still captured


def test_on_turn_never_raises_on_garbage_args():
    assert conversation.on_turn(user=None, assistant=None) is None      # type: ignore[arg-type]
    assert conversation.buffered() == 0                                 # empty -> dropped
    assert conversation.on_turn(user=123, assistant=['x']) is None      # type: ignore[arg-type]
    assert conversation.flush() == 1                                    # coerced, stored


def test_text_is_capped():
    conversation.on_turn(user='U' * 20000, assistant='A' * 20000)
    conversation.flush()
    r = conversation.recent_turns(limit=1)[0]
    assert len(r['user']) == conversation._TEXT_CAP + 1      # cap + ellipsis
    assert r['user'].endswith('…')


def test_buffer_is_bounded_without_flusher():
    """If persistence is unavailable the buffer drops oldest, never grows."""
    for i in range(conversation._BUF_MAX + 50):
        conversation.on_turn(user=f'u{i}', assistant='a')
    assert conversation.buffered() == conversation._BUF_MAX


def test_background_flusher_persists_without_manual_flush(
        monkeypatch, _disable_background_flusher):
    """The lazily-started daemon thread persists on its own cadence and
    shutdown() leaves no orphan thread behind (Rule 14)."""
    real_ensure = _disable_background_flusher
    monkeypatch.setattr(conversation, '_ensure_flusher', real_ensure)
    monkeypatch.setattr(
        conversation, '_cfg',
        lambda dotted, default: 0.05 if dotted == 'memory.conversation_flush_s'
        else default)
    conversation.on_turn(user='bg', assistant='turn')
    deadline = time.time() + 3.0
    while time.time() < deadline and conversation.turn_count() == 0:
        time.sleep(0.05)
    assert conversation.turn_count() == 1
    conversation.shutdown(timeout=2.0)
    t = conversation._thread
    assert t is None or not t.is_alive()


def test_trim_drops_oldest_beyond_max_rows(monkeypatch):
    monkeypatch.setattr(
        conversation, '_cfg',
        lambda dotted, default: 5 if dotted == 'memory.conversation_max_rows'
        else default)
    for i in range(12):
        conversation.on_turn(user=f'u{i}', assistant='a')
        conversation.flush()
    assert conversation.turn_count() == 5
    newest = [r['user'] for r in conversation.recent_turns(limit=5)]
    assert newest == ['u11', 'u10', 'u9', 'u8', 'u7']   # oldest dropped


def test_readers_fail_silent_on_db_error(monkeypatch):
    import brain.memory as mem
    def _raise():
        raise RuntimeError('db gone')
    monkeypatch.setattr(mem, 'get_conn', _raise)
    assert conversation.recent_turns(limit=3) == []
    assert conversation.turn_count() == 0
    assert conversation.clear_turns() == 0

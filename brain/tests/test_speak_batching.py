"""Streamed-sentence batching (voice request APPROVED 2026-10-07):
_SentenceSpeaker holds speech until batch_size sentences OR batch_wait_s OR
stream end, then ONE voice.speak(joined) per batch — its pre-roll keeps the
cadence gapless. Subtitles stay per-sentence. Hermetic: fake voice, no fish."""
import asyncio

import pytest

from brain import loop as loop_mod


class _Interrupts:
    def __init__(self):
        self.events = {}

    def register(self, key):
        self.events[key] = asyncio.Event()
        return self.events[key]

    def done(self, key):
        self.events.pop(key, None)


class FakeVoice:
    """Records each voice.speak() TEXT — one call per batch is the contract."""

    def __init__(self):
        self.spoken = []
        self.interrupts = _Interrupts()

    async def speak(self, text, *, job=None, cancel=None,
                    force_fallback=False):
        self.spoken.append(text)
        yield {'type': 'speak', 'v': 1, 'job': job, 'seq': 0,
               'event': 'start', 'sample_rate': 24000, 'text': text,
               'cached': True, 'engine': 'mock'}
        yield {'type': 'speak', 'v': 1, 'job': job, 'seq': 1,
               'event': 'end', 'sample_rate': 24000, 'cached': True,
               'engine': 'mock'}


def _speaker(voice, **kw):
    kw.setdefault('batch_size', 2)
    kw.setdefault('batch_wait_s', 5.0)      # long: batching must not timer-out
    return loop_mod._SentenceSpeaker(None, 'j_batch', voice, **kw)


@pytest.mark.asyncio
async def test_sentences_speak_in_batches_of_two():
    v = FakeVoice()
    spk = _speaker(v, batch_size=2)
    async with spk:
        spk.push('One.')
        spk.push('Two.')
        spk.push('Three.')
        await asyncio.sleep(0.02)           # batch 1 drains while stream open
    # stream end (sentinel) flushes the remainder as batch 2
    assert v.spoken == ['One. Two.', 'Three.'], v.spoken


@pytest.mark.asyncio
async def test_single_sentence_flushes_on_stream_end_without_waiting():
    """A short reply must NOT sit through the hold timer — the sentinel
    arrives immediately after the flush."""
    v = FakeVoice()
    spk = _speaker(v, batch_size=2, batch_wait_s=30.0)
    t0 = asyncio.get_event_loop().time()
    async with spk:
        spk.push('Only one sentence here.')
    elapsed = asyncio.get_event_loop().time() - t0
    assert v.spoken == ['Only one sentence here.']
    assert elapsed < 1.0, f'short reply waited {elapsed:.2f}s for the timer'


@pytest.mark.asyncio
async def test_hold_timer_speaks_partial_batch():
    """End of stream or a stalled token feed: the timer releases the partial
    batch instead of holding forever."""
    v = FakeVoice()
    spk = _speaker(v, batch_size=3, batch_wait_s=0.05)
    async with spk:
        spk.push('Lonely sentence.')
        await asyncio.sleep(0.2)            # > hold, no 2nd sentence, no end
        assert v.spoken == ['Lonely sentence.'], v.spoken


@pytest.mark.asyncio
async def test_barge_in_drops_unspoken_batch():
    v = FakeVoice()
    spk = _speaker(v, batch_size=4, batch_wait_s=5.0)
    async with spk:
        spk.push('Dropped one.')
        spk.push('Dropped two.')
        await asyncio.sleep(0.02)
        spk.cancel.set()                    # user speaks over her
        await asyncio.sleep(0.02)
    assert v.spoken == [], 'cancel must drop the unsounded batch'


@pytest.mark.asyncio
async def test_subtitles_flow_per_sentence_before_batching():
    """UI unaffected: subtitles broadcast per sentence in push(), independent
    of when speech starts."""
    from brain.ws import get_hub
    from brain.tests.test_orb_states import FakeWs, Session, drain
    hub = get_hub()
    ws = FakeWs()
    sess = Session(ws, '127.0.0.1')
    sess.authed = True
    sess.role = 'ui'
    hub._sessions[sess.sid] = sess
    try:
        v = FakeVoice()
        spk = loop_mod._SentenceSpeaker(hub, 'j_batch', v,
                                        batch_size=3, batch_wait_s=5.0)
        async with spk:
            spk.push('First sentence.')
            await asyncio.sleep(0.01)
            subs = [t for t in ws.texts if t.get('type') == 'subtitle']
            assert len(subs) == 1, subs        # subtitle already out
            assert v.spoken == []              # speech still batched/held
            spk.push('Second sentence.')
            spk.push('Third sentence.')        # batch fills -> one speak
            await asyncio.sleep(0.02)
            assert v.spoken == ['First sentence. Second sentence. Third sentence.']
        subs = [t for t in ws.texts if t.get('type') == 'subtitle']
        assert len(subs) == 3                  # per sentence, unchanged
    finally:
        hub._sessions.pop(sess.sid, None)


@pytest.mark.asyncio
async def test_batch_defaults_come_from_lane_config():
    """config.d/brain-core.yaml carries the knobs (2 / 1.5 by default)."""
    from brain import config as appcfg
    assert appcfg.cfg_get(appcfg.get_config(), 'agent.speak_batch_sentences',
                          None) == 2
    assert appcfg.cfg_get(appcfg.get_config(), 'agent.speak_batch_wait_s',
                          None) == 1.5
    v = FakeVoice()
    spk = loop_mod._SentenceSpeaker(None, 'j_cfg', v)   # no explicit knobs
    assert spk.batch_size == 2 and abs(spk.batch_wait_s - 1.5) < 1e-9

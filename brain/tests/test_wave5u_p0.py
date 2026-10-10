"""Wave 5U P0 tests (charter §5.1, review findings #3-#5):
- P0.3: RiskDecision.target population (frame fields ride the existing
  broadcast — additive; qa's flow tests pin the frame end-to-end).
- P0.6: admission-stage input lock — 8 needs_lock jobs + 1 chat job: chat
  completes WITHOUT waiting; GUI jobs park in waiting_lock (no worker) and
  requeue when the lock frees.
- P0.7: router foreground_unknown refusal -> LLMResult.reason + one warn
  Notice (NOT a provider-outage notice); /status.foreground shape.
- P0.8: derived latency metrics command->tts_first_audio and
  audio_end->tts_first_audio appear in /status.latency (latency.snapshot).
"""
import asyncio

import pytest

from brain import confirm as confirm_mod
from brain import fastpath
from brain import foreground
from brain import latency
from brain.jobs import store
from brain.jobs.engine import get_engine


# ---- P0.3 ------------------------------------------------------------------
def test_classify_populates_target():
    d = confirm_mod.classify('delete the old log files')
    assert d.target == 'delete the old log files'
    d2 = confirm_mod.tool_decision('file_trash')
    assert d2.target == 'file_trash'


# ---- P0.6 admission lock ---------------------------------------------------
@pytest.mark.asyncio
async def test_chat_never_waits_behind_gui_jobs_at_admission():
    """8 input_lock jobs + 1 chat job while the lock is HELD: the chat job
    completes while all 8 park in waiting_lock (finding #4: a GUI burst
    must not starve conversation)."""
    engine = get_engine()
    started_here = not engine.started
    if started_here:
        engine.start(workers=2)
    engine.pause()
    ran = []

    async def runner(job):
        jid = job['id']
        if job.get('input_lock'):
            assert await engine.lock.acquire(jid), 'lock admission owner'
            await asyncio.sleep(0.01)
            engine.lock.release(jid)
        ran.append(job['job'])

    engine.runner = runner
    engine.lock.force_release()          # deterministic baseline
    # external owner holds the lock for the whole parking phase
    assert await engine.lock.acquire(999999) is True
    try:
        gui = [await engine.submit(text=f'gui job {i}', priority='user_facing',
                                   input_lock=True) for i in range(8)]
        chat = await engine.submit(text='hello chat', priority='user_facing')
        engine.resume()
        # chat completes while the lock is STILL held by the external owner
        for _ in range(200):
            if (store.get_job(chat['id']) or {}).get('status') == 'done':
                break
            await asyncio.sleep(0.02)
        assert (store.get_job(chat['id']) or {}).get('status') == 'done', \
            'chat must finish without waiting for the input lock'
        assert chat['job'] in ran
        parked = [j for j in gui
                  if (store.get_job(j['id']) or {}).get('status') == 'waiting_lock']
        assert len(parked) == 8, [store.get_job(j['id'])['status'] for j in gui]
        assert engine.stats()['jobs_waiting_lock'] == 8
        # free the lock -> all 8 requeue, run, and finish
        engine.lock.release(999999)
        for _ in range(400):
            if all((store.get_job(j['id']) or {}).get('status') == 'done'
                   for j in gui):
                break
            await asyncio.sleep(0.02)
        done = [j for j in gui
                if (store.get_job(j['id']) or {}).get('status') == 'done']
        assert len(done) == 8, [store.get_job(j['id'])['status'] for j in gui]
        assert engine.stats()['jobs_waiting_lock'] == 0
    finally:
        engine.lock.force_release()
        for j in gui:
            engine.cancel(j['job'])
        engine.cancel(chat['job'])
        engine.pause()
        engine.runner = None
        if started_here:
            await engine.shutdown()


def test_needs_lock_hint_chat_is_false_and_gui_intent_reads_registry():
    assert fastpath.needs_lock_hint('hello there, how are you') is False
    assert fastpath.needs_lock_hint('what time is it') is False
    # screenshot intent -> registry meta decides (needs_lock False today:
    # body-side gui, no local lock) — the hint must mirror the runtime rule
    assert fastpath.needs_lock_hint('screenshot') == \
        bool(__import__('brain.tools', fromlist=['x']).describe('screenshot')
             .get('needs_lock'))


# ---- P0.7 foreground-unknown legibility ------------------------------------
@pytest.mark.asyncio
async def test_foreground_unknown_refusal_notices_once_not_as_outage(monkeypatch):
    from brain import llm as llm_mod
    from brain import notice
    from brain.ws import Session, get_hub

    class _ForegroundRefusal(Exception):
        code = 'E_OFFLINE'
        reason = 'foreground_unknown'

    async def bad_facade(messages, tools=None, stream=False, purpose='chat',
                         task_kind=None, **kw):
        raise _ForegroundRefusal("foreground window unknown — refusing")

    monkeypatch.setattr(llm_mod, '_facade', lambda: bad_facade)
    monkeypatch.delenv('RAPHAEL_DISABLE_ROUTER', raising=False)  # facade path
    notice.reset_for_tests()

    class _FakeWs:
        def __init__(self):
            self.texts = []

        async def send_text(self, data):
            import json
            self.texts.append(json.loads(data))

        async def send_bytes(self, data):
            pass

        async def close(self):
            pass

    hub = get_hub()
    ws = _FakeWs()
    s = Session(ws, '127.0.0.1')
    s.authed = True
    s.role = 'cli'
    hub._sessions[s.sid] = s
    try:
        res = await llm_mod.chat([{'role': 'user', 'content': 'hi'}])
        assert res.ok is False and res.reason == 'foreground_unknown'
        for _ in range(6):
            await asyncio.sleep(0)
        notes = [t for t in ws.texts if t.get('type') == 'notice']
        fg = [n for n in notes if 'focused window is unknown' in n['text']]
        assert len(fg) == 1 and fg[0]['level'] == 'warn', notes
        assert not any('unreachable' in n['text'] for n in notes), \
            'a foreground refusal must never masquerade as an outage'
    finally:
        hub._sessions.pop(s.sid, None)
        notice.reset_for_tests()


def test_status_foreground_shape():
    foreground.reset_for_tests()
    b = foreground.status_block()
    assert b['state'] == 'unknown' and b['age_s'] is None
    foreground.set_foreground('Doc - Notepad | notepad.exe')
    b = foreground.status_block()
    assert b['state'] == 'ok' and 0.0 <= b['age_s'] < 5.0
    foreground.reset_for_tests()


# ---- P0.8 derived latency metrics ------------------------------------------
def test_derived_latency_metrics_in_snapshot():
    latency.reset_for_tests()
    try:
        latency.note_submit(1)
        latency.note_audio_end()
        latency.note_speak_start('j_test')
        latency.note_tts_first_audio('j_test')
        snap = latency.snapshot()
        stages = snap['stages']
        assert 'tts_first_audio' in stages
        assert 'command_to_tts_audio' in stages, stages
        assert 'audio_end_to_tts_audio' in stages, stages
        assert stages['command_to_tts_audio'] >= 0.0
        assert stages['audio_end_to_tts_audio'] >= 0.0
    finally:
        latency.reset_for_tests()


def test_derived_metrics_skip_stale_anchors():
    latency.reset_for_tests()
    try:
        latency.note_submit(2)
        latency._last_submit -= 600.0        # 10 min old = unrelated turn
        latency.note_speak_start('j_stale')
        latency.note_tts_first_audio('j_stale')
        stages = latency.snapshot()['stages']
        assert 'tts_first_audio' in stages
        assert 'command_to_tts_audio' not in stages, stages
        assert 'audio_end_to_tts_audio' not in stages, stages
    finally:
        latency.reset_for_tests()

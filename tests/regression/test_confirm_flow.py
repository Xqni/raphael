"""Regression: confirmation flow (PROTOCOL §9, RVA §7):
- timeout ABORTS, never auto-approves;
- deny → 'Aborted.' + E_CANCELLED;
- approve → scoped grant journaled on THAT job only;
- concurrent jobs each carry their own pending confirmation;
- free-text intent check fails closed;
- voice-channel / voice-path confirmation rules (xfail tripwires — voice
  confirm is not wired yet and high-risk has no non-voice requirement).
"""
import time

import pytest

from harness import voicespy
from harness.wssession import WSSession, SessionTimeout


def _wait_terminal(cli, job, timeout=12.0):
    return cli.wait(lambda m: m.get('type') == 'job_event'
                    and m.get('job') == job
                    and m.get('status') in ('done', 'failed', 'cancelled'),
                    timeout=timeout)


def test_timeout_aborts_never_auto_approves(client, qa_token):
    with WSSession(client, qa_token, role='cli') as cli:
        cli.send({'type': 'command', 'v': 1,
                  'text': 'purchase the annual software license',
                  'source': 'text'})
        ack = cli.wait(lambda m: m.get('type') == 'ack', timeout=5)
        job = ack['job']
        conf = cli.wait(lambda m: m.get('type') == 'needs_confirm'
                        and m.get('job') == job, timeout=5)
        assert conf['question'] and conf['actions'] == ['yes', 'no']
        assert conf['expires_at'] > int(time.time() * 1000)
        final = _wait_terminal(cli, job, timeout=10)   # 2 s test timeout
        assert final['status'] == 'cancelled', final
        assert final['error_code'] == 'E_CONFIRM_TIMEOUT', final


def test_deny_aborts_with_spoken_line(client, qa_token):
    with WSSession(client, qa_token, role='cli') as cli:
        cli.send({'type': 'command', 'v': 1,
                  'text': 'delete my screenshots folder', 'source': 'text'})
        ack = cli.wait(lambda m: m.get('type') == 'ack', timeout=5)
        job = ack['job']
        cli.wait(lambda m: m.get('type') == 'needs_confirm'
                 and m.get('job') == job, timeout=5)
        cli.send({'type': 'confirm_resp', 'v': 1, 'job': job,
                  'answer': 'no'})
        cli.wait(lambda m: m.get('type') == 'ack'
                 and m.get('answer') == 'no', timeout=5)
        final = _wait_terminal(cli, job, timeout=8)
        assert final['status'] == 'cancelled'
        assert final['text'] == 'Aborted.'
        assert final['error_code'] == 'E_CANCELLED'


def test_approve_grants_scoped_job_and_journals_it(client, qa_token):
    with WSSession(client, qa_token, role='cli') as cli:
        cli.send({'type': 'command', 'v': 1,
                  'text': 'echo rm cleanup staged', 'source': 'text'})
        ack = cli.wait(lambda m: m.get('type') == 'ack', timeout=5)
        job = ack['job']
        cli.wait(lambda m: m.get('type') == 'needs_confirm'
                 and m.get('job') == job, timeout=5)
        cli.send({'type': 'confirm_resp', 'v': 1, 'job': job,
                  'answer': 'yes'})
        final = _wait_terminal(cli, job, timeout=8)
        assert final['status'] == 'done', final
        assert final['text'] == 'Echo: rm cleanup staged'
        # scoped grant recorded on the job record (PROTOCOL §9.3)
        import json as _json
        from brain.memory import get_conn
        from brain.jobs import store
        rowid = store.parse_job_ref(job)
        conn = get_conn()
        try:
            rows = conn.execute('SELECT event FROM journal WHERE job_id=?',
                                (rowid,)).fetchall()
        finally:
            conn.close()
        events = [_json.loads(r['event']) for r in rows]
        granted = [e for e in events
                   if isinstance(e, dict) and e.get('event') == 'confirm_granted']
        assert granted, [e.get('event') if isinstance(e, dict) else e
                         for e in events]


def test_concurrent_jobs_each_hold_their_own_confirmation(client, qa_token):
    """Confirming job A never grants job B (PROTOCOL §9.4)."""
    with WSSession(client, qa_token, role='cli') as cli:
        jobs = []
        for text in ('echo rm cache purge',
                     'echo rm backup purge'):
            cli.send({'type': 'command', 'v': 1, 'text': text,
                      'source': 'text'})
            ack = cli.wait(lambda m: m.get('type') == 'ack', timeout=5)
            jobs.append(ack['job'])
        job_a, job_b = jobs
        # both pending confirmations must be live (frames may arrive in any
        # order relative to acks — collect from everything received)
        cli.drain(quiet=0.5, cap=5.0)
        got = {f.get('job') for f in cli.frames
               if f.get('type') == 'needs_confirm'}
        assert {job_a, job_b} <= got, f'got={got} all={[f.get("type") for f in cli.frames]}'

        # approve A only → A runs to done; B must still be pending
        cli.send({'type': 'confirm_resp', 'v': 1, 'job': job_a,
                  'answer': 'yes'})
        final_a = _wait_terminal(cli, job_a, timeout=8)
        assert final_a['status'] == 'done', final_a

        cli.send({'type': 'job_get', 'v': 1, 'job': job_b})
        snap = cli.wait(lambda m: m.get('type') == 'job_get'
                        and m.get('job', {}).get('job') == job_b, timeout=5)
        assert snap['job']['status'] not in ('done', 'failed', 'cancelled',
                                             'interrupted'), snap['job']

        # and only an explicit deny resolves B
        cli.send({'type': 'confirm_resp', 'v': 1, 'job': job_b,
                  'answer': 'no'})
        final_b = _wait_terminal(cli, job_b, timeout=8)
        assert final_b['status'] == 'cancelled'


# ---- free-text intent check (fail closed) --------------------------------
@pytest.mark.parametrize('answer,expected', [
    ('yes', 'yes'), ('Okay!', 'yes'), ('yeah', 'yes'), ('confirm', 'yes'),
    ('no', 'no'), ('nah', 'no'), ('abort', 'no'),
    ('maybe later', 'no'), ('do what you want', 'no'), ('', 'no'),
    ('what do you think', 'no'),
])
def test_parse_free_text_fails_closed(answer, expected):
    from brain.confirm import parse_free_text
    assert parse_free_text(answer) == expected


# ---- voice-channel rules (tripwires) -------------------------------------
@pytest.mark.xfail(strict=False,
                   reason='RVA §7 voice-first confirmation: a spoken "yes" '
                          '(mic audio_end -> STT transcript) never reaches '
                          'the Confirmer — confirm_resp is only wireable '
                          'from text clients today (request: qa-security -> '
                          'brain-core voice-confirm-wiring)')
def test_spoken_yes_resolves_pending_confirmation(client, qa_token):
    old = voicespy.CANNED_TRANSCRIPT
    voicespy.CANNED_TRANSCRIPT = 'yes'
    try:
        from harness.mock_body import MockBody
        with WSSession(client, qa_token, role='cli') as cli, \
             MockBody(client, qa_token) as body:
            cli.send({'type': 'command', 'v': 1,
                      'text': 'echo voice approval path', 'source': 'text'})
            ack = cli.wait(lambda m: m.get('type') == 'ack', timeout=5)
            job = ack['job']
            cli.wait(lambda m: m.get('type') == 'needs_confirm'
                     and m.get('job') == job, timeout=5)
            body.send({'type': 'audio_start', 'v': 1, 'sample_rate': 16000,
                       'channels': 1, 'encoding': 'pcm_s16le',
                       'reason': 'wake'})
            body.wait(lambda m: m.get('type') == 'ack', timeout=5)
            body.send_bytes(b'RAPH\x01\x00\x00\x00\x00' + b'\x00' * 32)
            body.send({'type': 'audio_end', 'v': 1})
            final = _wait_terminal(cli, job, timeout=10)
            assert final['status'] == 'done', final   # spoken yes must grant
    finally:
        voicespy.CANNED_TRANSCRIPT = old


@pytest.mark.xfail(strict=False,
                   reason='high-risk must need a NON-voice confirmation '
                          'channel (acoustic injection: TTS/speaker replay of '
                          '"yes"); confirm_resp carries no channel field and '
                          'voice-tagged grants are not refused (requests: '
                          'qa-security -> brain-core + integrator PROTOCOL §9)')
def test_voice_channel_grant_is_refused_for_risky_job(client, qa_token):
    with WSSession(client, qa_token, role='cli') as cli:
        cli.send({'type': 'command', 'v': 1,
                  'text': 'echo risky needs nonvoice', 'source': 'text'})
        ack = cli.wait(lambda m: m.get('type') == 'ack', timeout=5)
        job = ack['job']
        cli.wait(lambda m: m.get('type') == 'needs_confirm'
                 and m.get('job') == job, timeout=5)
        cli.send({'type': 'confirm_resp', 'v': 1, 'job': job,
                  'answer': 'yes', 'channel': 'voice'})
        final = _wait_terminal(cli, job, timeout=10)
        # a voice-only grant must NOT run the risky job
        assert final['status'] != 'done', final


def test_confirm_resp_without_pending_is_rejected(client, qa_token):
    with WSSession(client, qa_token, role='cli') as cli:
        cli.send({'type': 'confirm_resp', 'v': 1,
                  'job': 'j_00000000_0000', 'answer': 'yes'})
        reply = cli.wait(lambda m: m.get('type') == 'error', timeout=5)
        assert reply['code'] == 'E_BAD_MSG'

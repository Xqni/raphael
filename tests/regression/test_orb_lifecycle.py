"""Regression: orb_state emission for every lifecycle transition
(INTERFACES §e + PROTOCOL §8). A mock orb client records the exact frame
sequence the server broadcasts.

Contract note (merged brain-core, 2026-10-06): private/paused are MODE
overlays — `private_overlay` is a legacy client-side value the server no
longer emits; base `state` always comes from brain.orbstate.VALID_STATES.
"""
from harness.mock_body import MockBody
from harness.mock_orb import MockOrb
from harness.wssession import WSSession

REQUIRED_CORE = ('idle', 'thinking', 'confirm')
REQUIRED_FULL = ('listening', 'acting', 'speaking', 'error')


def _assert_frame_contract(orb):
    """Every orb_state carries state/jobs_active/mode + shape_hint/task_kind
    (PROTOCOL §8 / INTERFACES §e)."""
    states = orb.orb_states
    assert states, 'no orb_state frames recorded'
    for f in states:
        assert f.get('state'), f
        assert isinstance(f.get('jobs_active'), int), f
        assert f.get('mode') in ('normal', 'private', 'paused'), f
        assert 'shape_hint' in f and 'task_kind' in f, f


def test_core_lifecycle_transitions_emitted(client, qa_token):
    with MockOrb(client, qa_token) as orb, \
         WSSession(client, qa_token, role='cli') as cli:
        # initial snapshot after auth_ok with jobs_active==0 → idle
        orb.wait(lambda m: m.get('type') == 'orb_state'
                 and m.get('state') == 'idle', timeout=5)

        # running job → thinking
        cli.send({'type': 'command', 'v': 1, 'text': 'echo orb thinking',
                  'source': 'text'})
        cli.wait(lambda m: m.get('type') == 'ack', timeout=5)
        orb.wait(lambda m: m.get('type') == 'orb_state'
                 and m.get('state') == 'thinking', timeout=8)

        # risky job → confirm state (orb shows amber per PROTOCOL §9)
        cli.send({'type': 'command', 'v': 1,
                  'text': 'delete my old downloads folder', 'source': 'text'})
        cli.wait(lambda m: m.get('type') == 'ack', timeout=5)
        # needs_confirm broadcast must reach the orb regardless
        orb.drain(quiet=0.5, cap=3.0)
        assert any(f.get('type') == 'needs_confirm' for f in orb.frames), \
            [f.get('type') for f in orb.frames]
        # deny so the test ends clean
        cli.send({'type': 'confirm_resp', 'v': 1,
                  'job': [f for f in orb.frames
                          if f.get('type') == 'needs_confirm'][0]['job'],
                  'answer': 'no'})
        cli.wait(lambda m: m.get('type') == 'ack'
                 and m.get('answer') == 'no', timeout=5)

        # deny → back to idle (mode stays normal)
        cli.send({'type': 'control', 'v': 1, 'action': 'pause'})
        cli.wait(lambda m: m.get('type') == 'ack', timeout=5)
        orb.wait(lambda m: m.get('type') == 'orb_state'
                 and m.get('mode') == 'paused', timeout=5)
        cli.send({'type': 'control', 'v': 1, 'action': 'resume'})
        cli.wait(lambda m: m.get('type') == 'ack', timeout=5)

        # private is a mode overlay (state stays a valid semantic state)
        from brain.orbstate import VALID_STATES
        cli.send({'type': 'control', 'v': 1, 'action': 'private_on'})
        cli.wait(lambda m: m.get('type') == 'ack', timeout=5)
        frame = orb.wait(lambda m: m.get('type') == 'orb_state'
                         and m.get('mode') == 'private', timeout=5)
        assert frame['state'] in VALID_STATES, frame
        cli.send({'type': 'control', 'v': 1, 'action': 'private_off'})
        cli.wait(lambda m: m.get('type') == 'ack', timeout=5)

        _assert_frame_contract(orb)
        seen = set(orb.states)
        missing = set(REQUIRED_CORE) - seen
        assert not missing, f'missing states {missing}; sequence={orb.state_sequence}'


def _drive_full(client, token):
    """Drive one job per documented lifecycle state, sequentially so the
    state sequence is deterministic."""
    with MockBody(client, token) as body:
        with WSSession(client, token, role='cli') as cli:
            # listening: mic lane
            body.send({'type': 'audio_start', 'v': 1, 'sample_rate': 16000,
                       'channels': 1, 'encoding': 'pcm_s16le',
                       'reason': 'wake'})
            body.wait(lambda m: m.get('type') == 'ack'
                      and m.get('audio') == 'start', timeout=5)
            body.send({'type': 'audio_end', 'v': 1})
            body.wait(lambda m: m.get('type') == 'ack'
                      and m.get('audio') == 'end', timeout=8)

            # speaking: fastpath echo narrated through the (mocked) TTS
            cli.send({'type': 'command', 'v': 1, 'text': 'echo speak now',
                      'source': 'text'})
            ack = cli.wait(lambda m: m.get('type') == 'ack', timeout=5)
            cli.wait(lambda m: m.get('type') == 'job_event'
                     and m.get('status') == 'done'
                     and m.get('job') == ack['job'], timeout=8)

            # acting: gui tool → act_req to the body
            cli.send({'type': 'command', 'v': 1,
                      'text': 'take a screenshot', 'source': 'text'})
            ack = cli.wait(lambda m: m.get('type') == 'ack', timeout=5)
            body.next_act_req(timeout=10)
            cli.wait(lambda m: m.get('type') == 'job_event'
                     and m.get('status') == 'done'
                     and m.get('job') == ack['job'], timeout=8)

            # error: provider down (router disabled) → job failed
            cli.send({'type': 'command', 'v': 1,
                      'text': 'explain dark matter briefly', 'source': 'text'})
            ack = cli.wait(lambda m: m.get('type') == 'ack', timeout=5)
            cli.wait(lambda m: m.get('type') == 'job_event'
                     and m.get('status') == 'failed'
                     and m.get('job') == ack['job'], timeout=10)


def test_every_lifecycle_state_emitted(client, qa_token):
    with MockOrb(client, qa_token) as orb:
        _drive_full(client, qa_token)
        orb.drain(quiet=0.6, cap=4.0)
        _assert_frame_contract(orb)
        seen = set(orb.states)
        missing = set(REQUIRED_FULL) - seen
        assert not missing, \
            f'missing states {missing}; sequence={orb.state_sequence}'


def test_orb_confirm_state_while_awaiting(client, qa_token):
    with MockOrb(client, qa_token) as orb, \
         WSSession(client, qa_token, role='cli') as cli:
        cli.send({'type': 'command', 'v': 1,
                  'text': 'delete everything under tmp', 'source': 'text'})
        cli.wait(lambda m: m.get('type') == 'ack', timeout=5)
        orb.wait(lambda m: m.get('type') == 'orb_state'
                 and m.get('state') == 'confirm', timeout=8)
        cli.send({'type': 'cancel', 'v': 1, 'job': 'all',
                  'scope': 'full'})  # cleanup


def test_job_snapshot_reports_awaiting_confirm(client, qa_token):
    with WSSession(client, qa_token, role='cli') as cli:
        cli.send({'type': 'command', 'v': 1,
                  'text': 'delete the old installer files', 'source': 'text'})
        ack = cli.wait(lambda m: m.get('type') == 'ack', timeout=5)
        job = ack['job']
        cli.drain(quiet=0.4, cap=3.0)
        assert any(f.get('type') == 'needs_confirm' and f.get('job') == job
                   for f in cli.frames)
        cli.send({'type': 'job_get', 'v': 1, 'job': job})
        snap = cli.wait(lambda m: m.get('type') == 'job_get', timeout=5)
        assert snap['job']['status'] == 'awaiting_confirm', snap['job']

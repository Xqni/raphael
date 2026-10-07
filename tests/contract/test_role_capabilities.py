"""PROTOCOL §4 role-capability matrix (send side) + broadcast fan-out
(receive side). Server must drop frames a role may not send with
E_UNSUPPORTED, and never broadcast speak/orb_state/stt_final to roles that
must not receive them.
"""
import pytest

from harness.wssession import WSSession

PAYLOADS = {
    'command': {'type': 'command', 'v': 1, 'text': ''},       # cap passes -> E_BAD_MSG
    'audio_start': {'type': 'audio_start', 'v': 1, 'sample_rate': 16000},
    'audio_end': {'type': 'audio_end', 'v': 1},
    'confirm_resp': {'type': 'confirm_resp', 'v': 1,
                     'job': 'j_00000000_0000', 'answer': 'yes'},
    'control': {'type': 'control', 'v': 1, 'action': 'bogus_action'},
    'act_res': {'type': 'act_res', 'v': 1, 'ok': True},        # no job -> E_BAD_MSG
    'orb_input': {'type': 'orb_input', 'v': 1, 'kind': 'click'},
    'state_req': {'type': 'state_req', 'v': 1},
    'job_list': {'type': 'job_list', 'v': 1},
    'job_get': {'type': 'job_get', 'v': 1, 'job': 'j_00000000_0000'},
    'cancel': {'type': 'cancel', 'v': 1, 'job': 'j_00000000_0000',
               'scope': 'full'},
}

DENIED = [
    ('ui', 'act_res'), ('cli', 'act_res'),
    ('ui', 'audio_start'), ('ui', 'audio_end'),
    ('cli', 'audio_start'), ('cli', 'audio_end'),
    ('body', 'orb_input'), ('cli', 'orb_input'),
    ('body', 'state_req'),
]

ALLOWED = [
    (role, mtype)
    for mtype in ('command', 'confirm_resp', 'control', 'cancel',
                  'job_list', 'job_get')
    for role in ('body', 'ui', 'cli')
] + [
    ('body', 'audio_start'), ('body', 'audio_end'), ('body', 'act_res'),
    ('ui', 'orb_input'), ('ui', 'state_req'), ('cli', 'state_req'),
]


@pytest.mark.parametrize('role,mtype', DENIED,
                         ids=[f'{r}-{m}' for r, m in DENIED])
def test_denied_frame_gets_unsupported(client, qa_token, role, mtype):
    with WSSession(client, qa_token, role=role) as s:
        s.send(PAYLOADS[mtype])
        reply = s.wait(lambda m: m.get('type') == 'error', timeout=5)
        assert reply['code'] == 'E_UNSUPPORTED'
        assert mtype in reply.get('detail', ''), reply


@pytest.mark.parametrize('role,mtype', ALLOWED,
                         ids=[f'{r}-{m}' for r, m in ALLOWED])
def test_allowed_frame_not_unsupported(client, qa_token, role, mtype):
    """The cap check passes → the frame reaches its handler (which may still
    reject it with a NON-capability error)."""
    with WSSession(client, qa_token, role=role) as s:
        s.send(PAYLOADS[mtype])
        reply = s.wait(lambda m: m.get('type') in ('error', 'ack',
                                                   'job_list', 'orb_state'),
                       timeout=5)
        assert reply['type'] != 'error' or reply['code'] != 'E_UNSUPPORTED', \
            reply


# ---- receive side ---------------------------------------------------------
def test_speak_json_goes_to_body_and_ui_not_cli(client, qa_token):
    """§4: speak JSON → body+ui only; cli still gets the subtitle line."""
    with WSSession(client, qa_token, role='cli') as cli, \
         WSSession(client, qa_token, role='body') as body, \
         WSSession(client, qa_token, role='ui') as ui:
        cli.send({'type': 'command', 'v': 1, 'text': 'echo fanout probe',
                  'source': 'text'})
        cli.wait(lambda m: m.get('type') == 'ack', timeout=5)
        body_ev = body.wait(lambda m: m.get('type') == 'speak'
                            and m.get('event') in ('start', 'end'), timeout=8)
        assert body_ev['type'] == 'speak'
        ui_ev = ui.wait(lambda m: m.get('type') == 'speak', timeout=8)
        assert ui_ev['type'] == 'speak'
        cli.wait(lambda m: m.get('type') == 'subtitle', timeout=8)
        # cli must NEVER see speak frames
        cli_frames = cli.drain(quiet=0.4, cap=2.0)
        assert not [f for f in cli_frames if f.get('type') == 'speak'], \
            cli_frames


def test_orb_state_broadcast_reaches_ui_only(client, qa_token):
    """§8: orb_state is a ui-role broadcast; other roles only get direct
    replies to their own state_req."""
    with WSSession(client, qa_token, role='ui') as ui, \
         WSSession(client, qa_token, role='cli') as cli1, \
         WSSession(client, qa_token, role='cli') as cli2:
        ui.drain(quiet=0.3, cap=1.0)         # drop the auth-time snapshot
        cli1.send({'type': 'control', 'v': 1, 'action': 'watch_on'})
        cli1.wait(lambda m: m.get('type') == 'ack', timeout=5)
        orb = ui.wait(lambda m: m.get('type') == 'orb_state', timeout=5)
        assert orb['state'] in ('idle', 'thinking', 'confirm',
                                'private_overlay')
        cli2_frames = cli2.drain(quiet=0.4, cap=1.5)
        assert not [f for f in cli2_frames
                    if f.get('type') == 'orb_state'], cli2_frames


def test_state_req_direct_reply_works_for_ui_and_cli(client, qa_token):
    """Direct state_req → orb_state replies are allowed for ui AND cli (§3),
    even though orb_state broadcasts are ui-only."""
    for role in ('ui', 'cli'):
        with WSSession(client, qa_token, role=role) as s:
            s.send({'type': 'state_req', 'v': 1})
            reply = s.wait(lambda m: m.get('type') == 'orb_state', timeout=5)
            assert set(('state', 'jobs_active', 'mode')) <= set(reply)

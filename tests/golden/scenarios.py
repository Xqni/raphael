"""Wave-3 golden job transcripts — scenario drivers (qa-security).

Each scenario runs against a FRESH isolated brain (TestClient + wiped DB
per test — the replay test uses the same driver, so golden == replay
input). It returns per-session sent/received JSON frames; the recorder
normalizes volatile fields (see replay.py::normalize).

Deterministic by construction: mocked TTS (fixed frames), mocked provider
(fixed content), MockBody scripted reply, no clock in asserted payloads.
Sessions are ALWAYS opened after construction and closed in `finally`
(a leaked open session hangs TestClient teardown).
"""
from harness.mock_body import MockBody
from harness.mock_orb import MockOrb
from harness.wssession import WSSession


def _open_all(sessions):
    for _, ws in sessions:
        ws.open()


def _close_all(sessions):
    for _, ws in sessions:
        try:
            ws.close()
        except Exception:  # noqa: BLE001
            pass


def _snapshot(sessions):
    """label -> {sent, recv}; ping frames dropped from recv."""
    return {
        label: {
            'sent': [dict(f) for f in ws.sent],
            'recv': [f for f in ws.frames if f.get('type') != 'ping'],
        }
        for label, ws in sessions
    }


def _drain_all(sessions, quiet=0.4, cap=2.5):
    for _, ws in sessions:
        ws.drain(quiet=quiet, cap=cap)


def run_echo(client, token):
    """fastpath echo -> ack/job_events/answer/subtitle + orb + speaking."""
    sessions = [('0:ui', MockOrb(client, token)),
                ('1:cli', WSSession(client, token, role='cli'))]
    _open_all(sessions)
    try:
        ui, cli = sessions[0][1], sessions[1][1]
        cli.send({'type': 'command', 'v': 1, 'text': 'echo golden hello',
                  'source': 'text'})
        ack = cli.wait(lambda m: m.get('type') == 'ack', timeout=5)
        cli.wait(lambda m: m.get('type') == 'job_event'
                 and m.get('status') == 'done' and m.get('job') == ack['job'],
                 timeout=10)
        _drain_all(sessions)
        return _snapshot(sessions)
    finally:
        _close_all(sessions)


def run_confirm_deny(client, token):
    """risky job -> needs_confirm (both roles) -> deny -> 'Aborted.'."""
    sessions = [('0:ui', MockOrb(client, token)),
                ('1:cli', WSSession(client, token, role='cli'))]
    _open_all(sessions)
    try:
        ui, cli = sessions[0][1], sessions[1][1]
        cli.send({'type': 'command', 'v': 1, 'text': 'delete golden files now',
                  'source': 'text'})
        ack = cli.wait(lambda m: m.get('type') == 'ack', timeout=5)
        job = ack['job']
        cli.wait(lambda m: m.get('type') == 'needs_confirm'
                 and m.get('job') == job, timeout=8)
        cli.send({'type': 'confirm_resp', 'v': 1, 'job': job, 'answer': 'no'})
        cli.wait(lambda m: m.get('type') == 'job_event'
                 and m.get('status') == 'cancelled' and m.get('job') == job,
                 timeout=10)
        _drain_all(sessions)
        return _snapshot(sessions)
    finally:
        _close_all(sessions)


def run_gui_act(client, token):
    """fastpath gui tool -> act_req (body) -> act_res -> done + answer."""
    sessions = [('0:ui', MockOrb(client, token)),
                ('1:body', MockBody(client, token)),
                ('2:cli', WSSession(client, token, role='cli'))]
    _open_all(sessions)
    try:
        ui, body, cli = sessions[0][1], sessions[1][1], sessions[2][1]
        cli.send({'type': 'command', 'v': 1, 'text': 'take a screenshot',
                  'source': 'text'})
        ack = cli.wait(lambda m: m.get('type') == 'ack', timeout=5)
        body.next_act_req(timeout=10)
        cli.wait(lambda m: m.get('type') == 'job_event'
                 and m.get('status') == 'done' and m.get('job') == ack['job'],
                 timeout=10)
        _drain_all(sessions)
        return _snapshot(sessions)
    finally:
        _close_all(sessions)


SCENARIOS = {
    'echo': run_echo,
    'confirm_deny': run_confirm_deny,
    'gui_act': run_gui_act,
}


# Intent oracle for the eval layer (QA-3): input command -> expected tool
# behavior in the recorded transcript. Eval asserts the RECORDING matches —
# tool-call accuracy against the committed fixture, no live model involved.
SCENARIO_META = {
    'echo': {'command': 'echo golden hello', 'tool': None,
             'expect_confirm': False, 'expect_answer': True},
    'confirm_deny': {'command': 'delete golden files now', 'tool': None,
                     'expect_confirm': True, 'expect_answer': False},
    'gui_act': {'command': 'take a screenshot', 'tool': 'screenshot',
                'tool_args': {'max_px': 1280}, 'expect_confirm': False,
                'expect_answer': True},
}

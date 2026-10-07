"""Conversational agent loop tests (Wave 2 task 2/3/4): persona from config,
streamed tokens -> sentence chunks -> speak events, tool-calling loop feeding
back UNTRUSTED results, step cap, Private Mode = fast path only (no LLM),
typed/orb input channels.

The router is FAKED at the `brain.router.chat` seam (INTERFACES §a) — no
network, no keys, no providers.
"""
import json
import os
import tempfile

import pytest
from fastapi.testclient import TestClient

from brain import loop as loop_mod
from brain import orbstate
from brain.app import app
from brain.mode import get_mode
from brain.ws import get_hub

TEST_TOKEN = 'agent-loop-token-321'


# ---- fakes ------------------------------------------------------------------
def make_fake_chat(script):
    """Fake INTERFACES §a facade. `script` = per-call step dicts:
    {text, chunks, tool_calls, error, code} — last step repeats."""
    calls = []

    async def chat(messages, tools=None, stream=False, purpose='chat'):
        idx = len(calls)
        step = script[idx] if idx < len(script) else script[-1]
        if callable(step):
            step = step(messages)
        calls.append({'messages': [dict(m) for m in messages],
                      'tools': tools, 'stream': stream, 'purpose': purpose})

        async def gen():
            if step.get('error'):
                yield {'finish': 'error',
                       'code': step.get('code', 'E_OFFLINE'),
                       'error': step['error']}
                return
            chunks = step.get('chunks')
            if chunks is None:
                chunks = [step.get('text', '')]
            for c in chunks:
                yield {'delta': c}
            final = {'finish': 'stop', 'provider': 'fake-provider',
                     'model': 'fake-model'}
            if step.get('tool_calls'):
                final['tool_calls'] = step['tool_calls']
            yield final
        return gen()

    return chat, calls


@pytest.fixture
def fake_chat(monkeypatch):
    import brain.router as router
    monkeypatch.delenv('RAPHAEL_DISABLE_ROUTER', raising=False)

    def install(script):
        fn, calls = make_fake_chat(script)
        monkeypatch.setattr(router, 'chat', fn, raising=False)
        return calls
    yield install
    monkeypatch.delattr(router, 'chat', raising=False)


@pytest.fixture(autouse=True)
def _fresh_state():
    loop_mod.reset_history_for_tests()
    orbstate.reset_for_tests()
    orbstate.finish_boot()
    get_mode().set('private_off', persist=False)
    yield
    loop_mod.reset_history_for_tests()
    get_mode().set('private_off', persist=False)


@pytest.fixture(scope='module')
def token_path():
    fd, path = tempfile.mkstemp(prefix='raphael-test-token-agent-')
    with os.fdopen(fd, 'w') as f:
        f.write(TEST_TOKEN)
    old = os.environ.get('RAPHAEL_TOKEN_PATH')
    os.environ['RAPHAEL_TOKEN_PATH'] = path
    yield path
    if old is None:
        os.environ.pop('RAPHAEL_TOKEN_PATH', None)
    else:
        os.environ['RAPHAEL_TOKEN_PATH'] = old
    try:
        os.remove(path)
    except OSError:
        pass


def _recv_json(ws, timeout=8.0):
    import anyio
    from starlette.websockets import WebSocketDisconnect

    async def _inner():
        with anyio.fail_after(timeout):
            return await ws._send_rx.receive()

    message = ws.portal.call(_inner)
    if message['type'] == 'websocket.close':
        raise WebSocketDisconnect(code=message.get('code', 1000),
                                   reason=message.get('reason', ''))
    text = message.get('text')
    if text is None:
        text = message.get('bytes', b'').decode()
    return json.loads(text)


def _recv_until(ws, pred, skip=('ping',), limit=80, timeout=8):
    frames = []
    for _ in range(limit):
        msg = _recv_json(ws, timeout=timeout)
        frames.append(msg)
        if msg.get('type') in skip:
            continue
        if pred(msg):
            return msg, frames
    raise AssertionError(f'predicate not met; types={[f.get("type") for f in frames]}')


def _auth(ws, role):
    ws.send_text(json.dumps({'type': 'auth', 'v': 1, 'token': TEST_TOKEN,
                             'role': role, 'client': 'test', 'client_v': '1.0'}))
    return _recv_json(ws, timeout=5)


def _command(ws, text, source='text'):
    ws.send_text(json.dumps({'type': 'command', 'v': 1, 'text': text,
                             'source': source}))
    ack, _ = _recv_until(ws, lambda m: m.get('type') == 'ack')
    return ack['job']


# ---- task 2: persona + streaming + history ---------------------------------
def test_persona_streamed_reply_and_multi_turn_history(token_path, fake_chat):
    calls = fake_chat([{'text': 'Hello there. Raphael speaking.',
                        'chunks': ['Hello there. ', 'Raphael', ' speaking.']},
                       {'text': 'Acknowledged.'}])
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as ws_ui:
            assert _auth(ws_ui, 'ui')['type'] == 'auth_ok'
            with client.websocket_connect('/ws') as ws_body:
                assert _auth(ws_body, 'body')['type'] == 'auth_ok'
                with client.websocket_connect('/ws') as ws_cli:
                    assert _auth(ws_cli, 'cli')['type'] == 'auth_ok'
                    job = _command(ws_cli, 'tell me something interesting')
                    # stream -> subtitle chunks reach the ui as they arrive
                    sub, _ = _recv_until(
                        ws_ui, lambda m: m.get('type') == 'subtitle'
                        and 'Hello there.' in m.get('text', ''))
                    # speak events reach body AND ui (PROTOCOL §4)
                    spk, _ = _recv_until(
                        ws_body, lambda m: m.get('type') == 'speak'
                        and m.get('event') == 'start')
                    assert 'Hello there.' in spk['text']
                    done, _ = _recv_until(
                        ws_cli, lambda m: m.get('type') == 'job_event'
                        and m.get('status') == 'done' and m.get('job') == job)
                    assert done['text'] == 'Hello there. Raphael speaking.'

                    # multi-turn: second turn carries the history
                    job2 = _command(ws_cli, 'and then what?')
                    done2, _ = _recv_until(
                        ws_cli, lambda m: m.get('type') == 'job_event'
                        and m.get('status') == 'done' and m.get('job') == job2)

    # persona came from config.voice_personality
    sys_msg = calls[0]['messages'][0]
    assert sys_msg['role'] == 'system'
    assert 'raphael_great_sage' in sys_msg['content']
    assert 'Never say or act like' in sys_msg['content']
    assert 'calm, precise, analytical' in sys_msg['content']
    # prompt_block fallback (pc-control item 2) rides in the system prompt
    assert 'Tool calling:' in sys_msg['content']
    assert '- shell:' in sys_msg['content']
    # streamed + tools offered natively, tool-capable turns tagged purpose=tool
    assert calls[0]['stream'] is True
    assert calls[0]['purpose'] == 'tool'
    tool_names = {t['function']['name'] for t in (calls[0]['tools'] or [])}
    assert 'shell' in tool_names
    assert calls[0]['messages'][-1] == {'role': 'user',
                                        'content': 'tell me something interesting'}
    # history: second call sees the first exchange, trimmed oldest-first
    roles = [m['role'] for m in calls[1]['messages']]
    assert roles.count('user') >= 2 and 'assistant' in roles, roles
    first_user = [m for m in calls[1]['messages'] if m['role'] == 'user'][0]
    assert first_user['content'] == 'tell me something interesting'


# ---- task 2: tool-calling loop --------------------------------------------
def test_tool_loop_executes_and_feeds_back_untrusted(token_path, fake_chat):
    from brain import tools as reg

    reg.register('t_agent_echo',
                 lambda q: f'RESULT:{q}', description='test tool',
                 schema={'type': 'object',
                         'properties': {'q': {'type': 'string',
                                              'description': 'query'}},
                         'required': ['q'], 'additionalProperties': False})
    try:
        calls = fake_chat([
            {'text': '', 'tool_calls': [{
                'id': 'c1', 'type': 'function',
                'function': {'name': 't_agent_echo',
                             'arguments': json.dumps({'q': '42'})}}]},
            {'text': 'The answer is 42.'},
        ])
        with TestClient(app) as client:
            with client.websocket_connect('/ws') as ws_ui:
                assert _auth(ws_ui, 'ui')['type'] == 'auth_ok'
                with client.websocket_connect('/ws') as ws_cli:
                    assert _auth(ws_cli, 'cli')['type'] == 'auth_ok'
                    job = _command(ws_cli, 'what is the answer')
                    done, _ = _recv_until(
                        ws_cli, lambda m: m.get('type') == 'job_event'
                        and m.get('status') == 'done' and m.get('job') == job)
                    assert done['text'] == 'The answer is 42.'
        assert len(calls) == 2
        # strict spec offered to the model
        spec = {t['function']['name']: t for t in calls[0]['tools']}
        assert spec['t_agent_echo']['function']['parameters'][
            'additionalProperties'] is False
        # turn 2: assistant tool_calls + UNTRUSTED tool result (§9)
        msgs = calls[1]['messages']
        tool_msgs = [m for m in msgs if m.get('role') == 'tool']
        assert len(tool_msgs) == 1
        assert tool_msgs[0]['content'].startswith(
            '[UNTRUSTED t_agent_echo output')
        assert 'RESULT:42' in tool_msgs[0]['content']
        asst = [m for m in msgs if m.get('role') == 'assistant'
                and m.get('tool_calls')]
        assert asst and asst[0]['tool_calls'][0]['function']['name'] == 't_agent_echo'
    finally:
        reg._registry.pop('t_agent_echo', None)
        reg._META.pop('t_agent_echo', None)


def test_tool_args_are_strictly_validated(token_path, fake_chat):
    from brain import tools as reg
    seen = {}

    reg.register('t_agent_strict',
                 lambda q: seen.setdefault('q', q) or 'ok',
                 description='strict tool',
                 schema={'type': 'object',
                         'properties': {'q': {'type': 'string',
                                              'description': 'query'}},
                         'required': ['q'], 'additionalProperties': False})
    try:
        calls = fake_chat([
            {'text': '', 'tool_calls': [{
                'id': 'c1', 'type': 'function',
                'function': {'name': 't_agent_strict',
                             'arguments': json.dumps({'q': 'ok',
                                                      'bogus': 1})}}]},
            {'text': 'Fixed it.'},
        ])
        with TestClient(app) as client:
            with client.websocket_connect('/ws') as ws_cli:
                assert _auth(ws_cli, 'cli')['type'] == 'auth_ok'
                job = _command(ws_cli, 'run the strict tool')
                done, _ = _recv_until(
                    ws_cli, lambda m: m.get('type') == 'job_event'
                    and m.get('status') == 'done' and m.get('job') == job)
                assert done['text'] == 'Fixed it.'
        assert seen == {}, 'unknown arg must NOT reach the tool'
        tool_msg = [m for m in calls[1]['messages'] if m.get('role') == 'tool'][0]
        assert 'ERROR' in tool_msg['content'] and 'unknown args' in tool_msg['content']
    finally:
        reg._registry.pop('t_agent_strict', None)
        reg._META.pop('t_agent_strict', None)


def test_tool_step_cap_fails_honestly(token_path, fake_chat):
    from brain import tools as reg
    reg.register('t_agent_loop', lambda q: 'x', description='loop tool',
                 schema={'type': 'object',
                         'properties': {'q': {'type': 'string',
                                              'description': 'q'}},
                         'required': ['q'], 'additionalProperties': False})
    try:
        def tool_step(messages):
            return {'text': '', 'tool_calls': [{
                'id': 'c', 'type': 'function',
                'function': {'name': 't_agent_loop',
                             'arguments': json.dumps({'q': 'again'})}}]}
        calls = fake_chat([tool_step])
        with TestClient(app) as client:
            with client.websocket_connect('/ws') as ws_ui:
                assert _auth(ws_ui, 'ui')['type'] == 'auth_ok'
                with client.websocket_connect('/ws') as ws_cli:
                    assert _auth(ws_cli, 'cli')['type'] == 'auth_ok'
                    job = _command(ws_cli, 'loop forever please')
                    failed, _ = _recv_until(
                        ws_cli, lambda m: m.get('type') == 'job_event'
                        and m.get('status') == 'failed' and m.get('job') == job)
                    assert 'step cap' in (failed.get('text') or '').lower() or \
                        'Step limit' in (failed.get('text') or ''), failed
                    # honest notice reaches the user (subtitle + spoken)
                    _recv_until(ws_ui, lambda m: m.get('type') == 'subtitle'
                                and 'Step limit' in m.get('text', ''))
        # step cap from config.d/brain-core.yaml is respected
        assert len(calls) == 6, len(calls)
    finally:
        reg._registry.pop('t_agent_loop', None)
        reg._META.pop('t_agent_loop', None)


# ---- task 4: Private Mode = fast path only ---------------------------------
def test_private_mode_no_llm_fastpath_only_with_notice(token_path, fake_chat):
    calls = fake_chat([{'text': 'SHOULD NEVER BE CALLED'}])
    get_mode().set('private_on', persist=False)
    try:
        with TestClient(app) as client:
            with client.websocket_connect('/ws') as ws_ui:
                assert _auth(ws_ui, 'ui')['type'] == 'auth_ok'
                with client.websocket_connect('/ws') as ws_cli:
                    assert _auth(ws_cli, 'cli')['type'] == 'auth_ok'
                    job = _command(ws_cli, 'what is the meaning of life')
                    done, _ = _recv_until(
                        ws_cli, lambda m: m.get('type') == 'job_event'
                        and m.get('status') == 'done' and m.get('job') == job)
                    assert 'Private mode is on' in done['text']
                    # spoken/subtitled notice (speak JSON mirrors to ui too)
                    _recv_until(ws_ui, lambda m: m.get('type') == 'subtitle'
                                and 'Private mode is on' in m.get('text', ''))
                    _recv_until(ws_ui, lambda m: m.get('type') == 'speak')
        assert calls == [], 'Private Mode must make ZERO LLM calls'
    finally:
        get_mode().set('private_off', persist=False)


def test_fastpath_still_first_in_private_mode(token_path, fake_chat):
    """fast path stays FIRST even under Private Mode (deterministic intents)."""
    calls = fake_chat([{'text': 'x'}])
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as ws_cli:
            assert _auth(ws_cli, 'cli')['type'] == 'auth_ok'
            job = _command(ws_cli, 'echo still fast')
            done, _ = _recv_until(
                ws_cli, lambda m: m.get('type') == 'job_event'
                and m.get('status') == 'done' and m.get('job') == job)
            assert done['text'] == 'Echo: still fast'
    assert calls == []


# ---- task 2/3: typed + orb input channels ---------------------------------
def test_orb_submit_text_end_to_end(token_path, fake_chat):
    fake_chat([{'text': 'ignored'}])   # echo never reaches the model
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as ws_ui:
            assert _auth(ws_ui, 'ui')['type'] == 'auth_ok'
            ws_ui.send_text(json.dumps({'type': 'orb_input', 'v': 1,
                                        'kind': 'submit_text',
                                        'value': 'echo typed on the orb'}))
            ack, _ = _recv_until(ws_ui, lambda m: m.get('type') == 'ack')
            assert ack['job'].startswith('j_')
            done, _ = _recv_until(
                ws_ui, lambda m: m.get('type') == 'job_event'
                and m.get('status') == 'done' and m.get('job') == ack['job'])
            assert done['text'] == 'Echo: typed on the orb'
            # empty value is refused
            ws_ui.send_text(json.dumps({'type': 'orb_input', 'v': 1,
                                        'kind': 'submit_text', 'value': '  '}))
            err, _ = _recv_until(ws_ui, lambda m: m.get('type') == 'error')
            assert err['code'] == 'E_BAD_MSG'


def test_orb_menu_click_confirms_high_risk(token_path, fake_chat):
    fake_chat([{'text': 'never reached'}])
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as ws_ui:
            assert _auth(ws_ui, 'ui')['type'] == 'auth_ok'
            with client.websocket_connect('/ws') as ws_cli:
                assert _auth(ws_cli, 'cli')['type'] == 'auth_ok'
                job = _command(ws_cli, 'delete the project folder')
                conf, _ = _recv_until(
                    ws_cli, lambda m: m.get('type') == 'needs_confirm'
                    and m.get('job') == job)
                assert conf['risk'] == 'high'      # config-list action
                # the ORB sees the `confirm` state (INTERFACES §e) — real
                # store status now transitions to awaiting_confirm
                orb, _ = _recv_until(ws_ui, lambda m: m.get('type') == 'orb_state'
                                     and m.get('state') == 'confirm')
                assert orb['jobs_active'] >= 1
                # orb click (NON-voice) approves
                ws_ui.send_text(json.dumps({'type': 'orb_input', 'v': 1,
                                            'kind': 'menu', 'value': 'yes'}))
                ack, _ = _recv_until(ws_ui, lambda m: m.get('type') == 'ack'
                                     and m.get('accepted') is True)
                assert ack['job'] == job
                # confirm resolved: job leaves awaiting_confirm (provider path)
                st, _ = _recv_until(
                    ws_cli, lambda m: m.get('type') == 'job_event'
                    and m.get('job') == job
                    and m.get('status') in ('running', 'failed', 'done'))
                assert st['status'] != 'awaiting_confirm'


# ---- task 3: voice confirmation hardening ----------------------------------
def test_high_risk_voice_yes_rejected_typed_yes_granted(token_path, fake_chat):
    fake_chat([{'text': 'proceeding'}])
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as ws_body:
            assert _auth(ws_body, 'body')['type'] == 'auth_ok'
            with client.websocket_connect('/ws') as ws_cli:
                assert _auth(ws_cli, 'cli')['type'] == 'auth_ok'
                job = _command(ws_cli, 'delete my downloads folder')
                conf, _ = _recv_until(
                    ws_cli, lambda m: m.get('type') == 'needs_confirm'
                    and m.get('job') == job)
                assert conf['risk'] == 'high'
                # 1) VOICE "yes" (role body = STT) on HIGH risk -> rejected
                ws_body.send_text(json.dumps({'type': 'confirm_resp', 'v': 1,
                                              'job': job, 'answer': 'yes'}))
                ack, _ = _recv_until(ws_body, lambda m: m.get('type') == 'ack'
                                     and m.get('accepted') is False)
                assert ack['job'] == job
                from brain.jobs import store
                assert store.get_job(store.parse_job_ref(job))[
                    'status'] == 'awaiting_confirm'   # still pending!
                # 2) TYPED "yes" (role cli) -> granted
                ws_cli.send_text(json.dumps({'type': 'confirm_resp', 'v': 1,
                                             'job': job, 'answer': 'yes'}))
                ack2, _ = _recv_until(ws_cli, lambda m: m.get('type') == 'ack'
                                      and m.get('accepted') is True)
                assert ack2['job'] == job
                st, _ = _recv_until(
                    ws_cli, lambda m: m.get('type') == 'job_event'
                    and m.get('job') == job
                    and m.get('status') in ('running', 'failed', 'done'))
                assert st['status'] != 'awaiting_confirm'


def test_high_risk_voice_no_still_denies(token_path, fake_chat):
    fake_chat([{'text': 'never'}])
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as ws_body:
            assert _auth(ws_body, 'body')['type'] == 'auth_ok'
            with client.websocket_connect('/ws') as ws_cli:
                assert _auth(ws_cli, 'cli')['type'] == 'auth_ok'
                job = _command(ws_cli, 'purchase a new laptop on amazon')
                _recv_until(ws_cli, lambda m: m.get('type') == 'needs_confirm'
                            and m.get('job') == job)
                # voice "no" is always allowed (denying is safe)
                ws_body.send_text(json.dumps({'type': 'confirm_resp', 'v': 1,
                                              'job': job, 'answer': 'no'}))
                ack, _ = _recv_until(ws_body, lambda m: m.get('type') == 'ack'
                                     and m.get('accepted') is True)
                assert ack['answer'] == 'no'
                cancelled, _ = _recv_until(
                    ws_cli, lambda m: m.get('type') == 'job_event'
                    and m.get('status') == 'cancelled' and m.get('job') == job)
                assert cancelled['error_code'] == 'E_CANCELLED'


def test_low_risk_voice_yes_is_allowed(token_path, fake_chat):
    fake_chat([{'text': 'fetching'}])
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as ws_body:
            assert _auth(ws_body, 'body')['type'] == 'auth_ok'
            with client.websocket_connect('/ws') as ws_cli:
                assert _auth(ws_cli, 'cli')['type'] == 'auth_ok'
                # 'curl ...' -> network action -> NOT on safety.confirm_actions
                job = _command(ws_cli, 'curl the endpoint')
                conf, _ = _recv_until(
                    ws_cli, lambda m: m.get('type') == 'needs_confirm'
                    and m.get('job') == job)
                assert conf['risk'] == 'low'
                ws_body.send_text(json.dumps({'type': 'confirm_resp', 'v': 1,
                                              'job': job, 'answer': 'yes'}))
                ack, _ = _recv_until(ws_body, lambda m: m.get('type') == 'ack'
                                     and m.get('accepted') is True)
                assert ack['answer'] == 'yes'
                st, _ = _recv_until(
                    ws_cli, lambda m: m.get('type') == 'job_event'
                    and m.get('job') == job
                    and m.get('status') in ('running', 'failed', 'done'))
                assert st['status'] != 'awaiting_confirm'


def test_voice_command_clear_yes_no_answers_pending_confirm(token_path,
                                                            fake_chat):
    """Wake-gated voice command ('Raphael, yes') resolves the pending confirm
    (low-risk here: voice yes is allowed only off the high-risk config list)."""
    fake_chat([{'text': 'fetching'}])
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as ws_cli:
            assert _auth(ws_cli, 'cli')['type'] == 'auth_ok'
            job = _command(ws_cli, 'curl the endpoint')
            conf, _ = _recv_until(ws_cli, lambda m: m.get('type') == 'needs_confirm'
                                  and m.get('job') == job)
            assert conf['risk'] == 'low'
            # voice-source command that clearly says yes (post-wake-gate)
            ws_cli.send_text(json.dumps({'type': 'command', 'v': 1,
                                         'text': 'yes', 'source': 'voice'}))
            ack, _ = _recv_until(ws_cli, lambda m: m.get('type') == 'ack'
                                 and m.get('confirm_answer') is True)
            assert ack.get('accepted') is True
            st, _ = _recv_until(
                ws_cli, lambda m: m.get('type') == 'job_event'
                and m.get('job') == job
                and m.get('status') in ('running', 'failed', 'done'))
            assert st['status'] != 'awaiting_confirm'


def test_audio_path_listening_and_voice_confirm(token_path, fake_chat,
                                                monkeypatch):
    """INTERFACES §e audio_start -> `listening` (real ws handler) + the
    STT-path voice confirmation: low-risk yes GRANTED, high-risk yes REJECTED
    (hint subtitle, pending survives until typed/orb confirmation)."""
    import struct
    from types import SimpleNamespace

    from brain.voice import get_voice
    voice = get_voice()
    monkeypatch.setattr(
        voice, 'transcribe_result',
        lambda buf, sample_rate=None, reason=None: SimpleNamespace(
            text='yes', lang='en', rtf=0.1))
    fake_chat([{'text': 'on it'}])
    from brain.jobs import store as job_store

    def _mic_yes(ws):
        payload = b'\x00\x00' * 1600            # 0.1 s silence (s16le mono)
        ws.send_bytes(b'RAPH' + struct.pack('>BI', 1, 1) + payload)
        ws.send_text(json.dumps({'type': 'audio_end', 'v': 1}))

    with TestClient(app) as client:
        with client.websocket_connect('/ws') as ws_ui:
            assert _auth(ws_ui, 'ui')['type'] == 'auth_ok'
            with client.websocket_connect('/ws') as ws_body:
                assert _auth(ws_body, 'body')['type'] == 'auth_ok'
                with client.websocket_connect('/ws') as ws_cli:
                    assert _auth(ws_cli, 'cli')['type'] == 'auth_ok'
                    # audio_start -> orb `listening`
                    ws_body.send_text(json.dumps({'type': 'audio_start',
                                                  'v': 1, 'reason': 'wake'}))
                    _recv_until(ws_body, lambda m: m.get('type') == 'ack')
                    _recv_until(ws_ui, lambda m: m.get('type') == 'orb_state'
                                and m.get('state') == 'listening')

                    # LOW risk: voice yes from the mic is granted
                    job1 = _command(ws_cli, 'curl the endpoint')
                    conf1, _ = _recv_until(
                        ws_cli, lambda m: m.get('type') == 'needs_confirm'
                        and m.get('job') == job1)
                    assert conf1['risk'] == 'low'
                    _mic_yes(ws_body)
                    _recv_until(ws_body, lambda m: m.get('type') == 'ack'
                                and m.get('audio') == 'end')
                    st1, _ = _recv_until(
                        ws_cli, lambda m: m.get('type') == 'job_event'
                        and m.get('job') == job1
                        and m.get('status') in ('running', 'failed', 'done'))
                    assert st1['status'] != 'awaiting_confirm'

                    # HIGH risk: voice yes from the mic is REJECTED
                    job2 = _command(ws_cli, 'delete my downloads folder')
                    conf2, _ = _recv_until(
                        ws_cli, lambda m: m.get('type') == 'needs_confirm'
                        and m.get('job') == job2)
                    assert conf2['risk'] == 'high'
                    _mic_yes(ws_body)
                    hint, _ = _recv_until(
                        ws_cli, lambda m: m.get('type') == 'subtitle'
                        and 'High-risk action' in m.get('text', ''))
                    assert job_store.get_job(
                        job_store.parse_job_ref(job2))['status'] == \
                        'awaiting_confirm'          # pending survives
                    # typed confirmation still works
                    ws_cli.send_text(json.dumps({'type': 'confirm_resp',
                                                 'v': 1, 'job': job2,
                                                 'answer': 'yes'}))
                    ack, _ = _recv_until(ws_cli, lambda m: m.get('type') == 'ack'
                                         and m.get('accepted') is True)
                    assert ack['job'] == job2
                    st2, _ = _recv_until(
                        ws_cli, lambda m: m.get('type') == 'job_event'
                        and m.get('job') == job2
                        and m.get('status') in ('running', 'failed', 'done'))
                    assert st2['status'] != 'awaiting_confirm'


# ---- pc-control items 2 + 3 (approved 2026-10-06) ---------------------------
def test_textual_fallback_extracts_embedded_tool_call(token_path, fake_chat):
    """Provider WITHOUT native tools: the prompt_block JSON the model echoes
    back is parsed (incl. nested args) and executed."""
    from brain import tools as reg

    reg.register('t_fb_nested',
                 lambda q, opts: f'{q}/{opts["depth"]}',
                 description='nested-args tool',
                 schema={'type': 'object',
                         'properties': {
                             'q': {'type': 'string', 'description': 'query'},
                             'opts': {'type': 'object',
                                      'description': 'options'},
                         },
                         'required': ['q', 'opts'],
                         'additionalProperties': False})
    try:
        calls = fake_chat([
            {'text': 'Looking it up: {"tool": "t_fb_nested", '
                     '"args": {"q": "hi", "opts": {"depth": 2}}}'},
            {'text': 'All done.'},
        ])
        with TestClient(app) as client:
            with client.websocket_connect('/ws') as ws_cli:
                assert _auth(ws_cli, 'cli')['type'] == 'auth_ok'
                job = _command(ws_cli, 'nested fallback please')
                done, _ = _recv_until(
                    ws_cli, lambda m: m.get('type') == 'job_event'
                    and m.get('status') == 'done' and m.get('job') == job)
                assert done['text'] == 'All done.'
        # the embedded call actually executed and was fed back
        tool_msg = [m for m in calls[1]['messages'] if m.get('role') == 'tool']
        assert tool_msg and 'hi/2' in tool_msg[0]['content']
        assert tool_msg[0]['content'].startswith('[UNTRUSTED t_fb_nested output')
    finally:
        reg._registry.pop('t_fb_nested', None)
        reg._META.pop('t_fb_nested', None)


def test_extract_tool_call_handles_nested_args_unit():
    text = 'x {"tool": "a", "args": {"b": {"c": 1}, "d": [1, 2]}} y'
    name, args = loop_mod._extract_tool_call(text)
    assert name == 'a' and args == {'b': {'c': 1}, 'd': [1, 2]}
    # args object appearing BEFORE the tool key still parses
    text2 = '{"args": {"x": 1}, "tool": "b"}'
    name, args = loop_mod._extract_tool_call(text2)
    assert name == 'b' and args == {'x': 1}
    assert loop_mod._extract_tool_call('no call here') == (None, {})


def test_registry_risky_metadata_gates_dispatch(token_path, fake_chat):
    """Item 3: a tool flagged risky=True in the REGISTRY but NOT in
    confirm.RISKY_TOOLS still prompts for confirmation at dispatch."""
    from brain import tools as reg

    reg.register('t_registry_risky', lambda q: f'ran {q}',
                 description='risky by registry metadata', risky=True,
                 schema={'type': 'object',
                         'properties': {'q': {'type': 'string',
                                              'description': 'query'}},
                         'required': ['q'], 'additionalProperties': False})
    try:
        calls = fake_chat([
            {'text': '', 'tool_calls': [{
                'id': 'c1', 'type': 'function',
                'function': {'name': 't_registry_risky',
                             'arguments': json.dumps({'q': 'x'})}}]},
            {'text': 'Finished.'},
        ])
        with TestClient(app) as client:
            with client.websocket_connect('/ws') as ws_cli:
                assert _auth(ws_cli, 'cli')['type'] == 'auth_ok'
                job = _command(ws_cli, 'do the benign thing')
                conf, _ = _recv_until(
                    ws_cli, lambda m: m.get('type') == 'needs_confirm'
                    and m.get('job') == job)
                assert 't_registry_risky' in conf['question']
                ws_cli.send_text(json.dumps({'type': 'confirm_resp', 'v': 1,
                                             'job': job, 'answer': 'yes'}))
                _recv_until(ws_cli, lambda m: m.get('type') == 'ack'
                            and m.get('accepted') is True)
                done, _ = _recv_until(
                    ws_cli, lambda m: m.get('type') == 'job_event'
                    and m.get('status') == 'done' and m.get('job') == job)
                assert done['text'] == 'Finished.'
        # tool ran only AFTER the grant (result present in the feedback turn)
        tool_msg = [m for m in calls[1]['messages'] if m.get('role') == 'tool']
        assert tool_msg and 'ran x' in tool_msg[0]['content']
    finally:
        reg._registry.pop('t_registry_risky', None)
        reg._META.pop('t_registry_risky', None)


def test_tool_decision_helper_maps_risk():
    from brain import confirm as confirm_mod
    d = confirm_mod.tool_decision('powershell')
    assert d.needs and d.action == 'system_command' and d.risk == 'low'
    d = confirm_mod.tool_decision('files_delete', 'delete the thing')
    assert d.needs and d.action == 'delete_files' and d.risk == 'high'
    assert 'files_delete' in d.question and 'delete the thing' in d.question


# ---- computer-use hooks: fastpath see_screen + no-b64 journaling -----------
def test_fastpath_see_screen_intents():
    """ACCEPTED hook: the six screen phrases resolve instantly (no LLM) to
    the see_screen tool with the FULL utterance as the vision question."""
    from brain import fastpath
    ctx = fastpath.IntentCtx()
    for phrase in ('What am I looking at', "what's on my screen right now",
                   'What is on my screen', 'describe my screen',
                   'look at my screen', 'see my screen please'):
        res = fastpath.run_intent(phrase, ctx)
        assert res is not None, phrase
        assert res.tool == 'see_screen', phrase
        assert res.tool_args == {'question': phrase}, phrase
        assert res.needs_lock is False
        assert res.text == 'Let me look.'
        assert res.done is True
    # unrelated text still falls through to the LLM path
    assert fastpath.run_intent('tell me about screens', ctx) is None


def test_act_res_journal_never_persists_screenshot_b64(token_path, fake_chat):
    """PROTOCOL §7(4) + computer-use request ACCEPTED: the act_res journal
    stores a summary, never base64 image bytes (delivery stays full)."""
    fake_chat([{'text': 'ignored'}])
    fake_b64 = 'QUJD' * 50                     # 200 chars of "image"
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as ws_body:
            assert _auth(ws_body, 'body')['type'] == 'auth_ok'
            with client.websocket_connect('/ws') as ws_cli:
                assert _auth(ws_cli, 'cli')['type'] == 'auth_ok'
                # fastpath 'screenshot' -> gui tool -> act_req to the body
                job = _command(ws_cli, 'screenshot')
                req, _ = _recv_until(ws_body, lambda m: m.get('type') == 'act_req'
                                     and m.get('job') == job)
                assert req['action'] == 'screenshot'
                ws_body.send_text(json.dumps({
                    'type': 'act_res', 'v': 1, 'job': job, 'ok': True,
                    'result': {'b64': fake_b64, 'bytes': 99}}))
                done, _ = _recv_until(
                    ws_cli, lambda m: m.get('type') == 'job_event'
                    and m.get('status') in ('done', 'failed')
                    and m.get('job') == job)
                assert done['status'] == 'done'
                assert done['seq'] > 0

    # journal must contain the summary, never the b64 payload
    from brain.jobs import store as job_store
    from brain.memory import get_conn
    rowid = job_store.parse_job_ref(job)
    conn = get_conn()
    try:
        rows = conn.execute('SELECT event FROM journal WHERE job_id=?',
                            (rowid,)).fetchall()
    finally:
        conn.close()
    blob = ' '.join(str(r['event']) for r in rows)
    assert fake_b64[:50] not in blob, 'b64 fragment leaked into the journal'
    assert '<omitted 200 b64 chars>' in blob, blob[-300:]
    assert '"delivered": true' in blob, 'delivery must be unaffected'

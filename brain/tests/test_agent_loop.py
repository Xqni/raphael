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


@pytest.fixture(autouse=True)
def _policy_default_auto(monkeypatch):
    """P3 (Wave 5P): the live config now declares safety.confirm_policy
    default=confirm for MODEL-picked tools. This module tests the tool LOOP
    plumbing, not the gate — gate behavior is pinned in
    test_confirm_policy.py / test_confirm_hardening.py / qa's regression
    suite. Unclassified model-picked tools run act-first HERE by design."""
    from brain import config as _cfg
    cfg = dict(_cfg.get_config())
    safety = dict(cfg.get('safety') or {})
    pol = dict(safety.get('confirm_policy') or {})
    pol['default'] = 'auto'
    safety['confirm_policy'] = pol
    cfg['safety'] = safety
    monkeypatch.setattr(_cfg, 'get_config', lambda: cfg)
    yield


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
    # streamed + tools offered natively; purpose labels: INTENT turn = chat
    # (tools merely offered), tool-EXECUTION turns = tool (router request)
    assert calls[0]['stream'] is True
    assert calls[0]['purpose'] == 'chat'
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
        assert calls[1]['purpose'] == 'tool'   # actual tool execution step
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
        # SEC-3: each segment needs its own local decision (audio_start) and
        # must clear the local gate (non-silent, >=0.15s)
        ws.send_text(json.dumps({'type': 'audio_start', 'v': 1,
                                 'reason': 'wake'}))
        _recv_json(ws, timeout=5)                  # ack
        payload = struct.pack('<h', 2500) * 8000    # 0.5 s non-silent tone
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
    # AUD-09 (P0): tool_decision is ALWAYS non-voice — mapped or unknown
    d = confirm_mod.tool_decision('powershell')
    assert d.needs and d.action == 'system_command' and d.risk == 'high'
    d = confirm_mod.tool_decision('files_delete', 'delete the thing')
    assert d.needs and d.action == 'delete_files' and d.risk == 'high'
    d = confirm_mod.tool_decision('some_future_mcp_tool')
    assert d.needs and d.risk == 'high'      # unknown names: non-voice too
    assert 'files_delete' not in d.question
    d = confirm_mod.tool_decision('files_delete', 'delete the thing')
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


# ---- Wave-3: conversation-memory hook (seam to tools-memory) ----------------
def test_conversation_hook_offers_turns_to_memory(token_path, fake_chat,
                                                  monkeypatch):
    """Every finished turn is offered to brain.memory.conversation.on_turn —
    present: recorded with job + task_kind; broken: job still completes."""
    import types
    from brain import memory as memory_pkg

    turns = []
    fake_conv = types.ModuleType('brain.memory.conversation')
    fake_conv.on_turn = lambda **kw: turns.append(kw)
    # ONE patch point for the whole test: monkeypatch restores it at teardown
    monkeypatch.setattr(memory_pkg, 'conversation', fake_conv, raising=False)
    if True:
        fake_chat([{'text': 'Hook answer one.'}])
        with TestClient(app) as client:
            with client.websocket_connect('/ws') as ws_cli:
                assert _auth(ws_cli, 'cli')['type'] == 'auth_ok'
                job = _command(ws_cli, 'say the hook thing')
                done, _ = _recv_until(
                    ws_cli, lambda m: m.get('type') == 'job_event'
                    and m.get('status') == 'done' and m.get('job') == job)
                assert done['text'] == 'Hook answer one.'
        assert len(turns) == 1
        t = turns[0]
        assert t['user'] == 'say the hook thing'
        assert t['assistant'] == 'Hook answer one.'
        assert t['job'] == job
        assert t['task_kind'] in ('system', 'files', 'web', 'media', 'llm',
                                  'gui', 'none')

    # a RAISING memory hook must never fail the job
    turns.clear()
    fake_conv.on_turn = lambda **kw: (_ for _ in ()).throw(RuntimeError('db locked'))
    if True:
        fake_chat([{'text': 'Still fine.'}])
        with TestClient(app) as client:
            with client.websocket_connect('/ws') as ws_cli:
                assert _auth(ws_cli, 'cli')['type'] == 'auth_ok'
                job = _command(ws_cli, 'another turn')
                done, _ = _recv_until(
                    ws_cli, lambda m: m.get('type') == 'job_event'
                    and m.get('status') == 'done' and m.get('job') == job)
                assert done['text'] == 'Still fine.'



# ---- voice STT-outage subtitle (APPROVED 2026-10-07) ------------------------
def _mic_bytes(ws, silent=False, start=True):
    import struct
    # SEC-3: audio_start IS the local wake/PTT decision — audio_end without it
    # never reaches STT (fail-closed). Non-silent >=0.15s payloads pass the
    # local gate (silence/short segments are dropped before any upload).
    if start:
        ws.send_text(json.dumps({'type': 'audio_start', 'v': 1,
                                 'reason': 'wake'}))
        _recv_json(ws, timeout=5)                   # ack
    payload = (b'\x00\x00' * 8000 if silent
               else struct.pack('<h', 2500) * 8000)   # 0.5 s
    ws.send_bytes(b'RAPH' + struct.pack('>BI', 1, 1) + payload)
    ws.send_text(json.dumps({'type': 'audio_end', 'v': 1}))


def test_stt_outage_broadcasts_surfaceable_subtitle(token_path, monkeypatch):
    """An STT outage must not swallow the utterance silently: the §10
    surfaceable-code notice reaches ui+cli; error_frame still reaches body+ui."""
    from brain.voice import VoiceSTTError, get_voice

    def boom(buf, sample_rate=None, reason=None):
        raise VoiceSTTError('E_OFFLINE', 'groq whisper unreachable')

    monkeypatch.setattr(get_voice(), 'transcribe_result', boom)
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as ws_ui:
            assert _auth(ws_ui, 'ui')['type'] == 'auth_ok'
            with client.websocket_connect('/ws') as ws_cli:
                assert _auth(ws_cli, 'cli')['type'] == 'auth_ok'
                with client.websocket_connect('/ws') as ws_body:
                    assert _auth(ws_body, 'body')['type'] == 'auth_ok'
                    _mic_bytes(ws_body)
                    # body: the typed error frame
                    err, _ = _recv_until(ws_body, lambda m: m.get('type') == 'error')
                    assert err['code'] == 'E_OFFLINE'
                    # ui: error frame AND the human subtitle
                    sub, _ = _recv_until(ws_ui, lambda m: m.get('type') == 'subtitle'
                                         and 'Voice input unavailable' in m.get('text', ''))
                    assert 'E_OFFLINE' in sub['text'] and sub['job'] is None
                    # cli: subtitle only (error_frame is body+ui)
                    sub2, _ = _recv_until(ws_cli, lambda m: m.get('type') == 'subtitle'
                                          and 'Voice input unavailable' in m.get('text', ''))
                    assert sub2['fade_ms'] == 6000
                    # body must NOT receive the ui/cli outage subtitle
                    try:
                        extra = _recv_json(ws_body, timeout=1.0)
                        assert extra.get('type') != 'subtitle', extra
                    except Exception:  # noqa: BLE001 — no further frames = pass
                        pass


def test_stt_fatal_code_sends_no_subtitle(token_path, monkeypatch):
    """Non-surfaceable codes (fatal/internal) keep today's behavior: error
    frame only — raw detail never becomes a subtitle."""
    from brain.voice import VoiceSTTError, get_voice

    def boom(buf, sample_rate=None, reason=None):
        raise VoiceSTTError('E_AUTH', 'raw provider detail must not surface')

    monkeypatch.setattr(get_voice(), 'transcribe_result', boom)
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as ws_ui:
            assert _auth(ws_ui, 'ui')['type'] == 'auth_ok'
            with client.websocket_connect('/ws') as ws_body:
                assert _auth(ws_body, 'body')['type'] == 'auth_ok'
                _mic_bytes(ws_body)
                err, _ = _recv_until(ws_body, lambda m: m.get('type') == 'error')
                assert err['code'] == 'E_AUTH'
                seen = []
                try:
                    # wide harvest: auth/refresh orb_states queue up before
                    # the error frame — read until the stream goes quiet
                    for _ in range(8):
                        seen.append(_recv_json(ws_ui, timeout=1.0))
                except Exception:  # noqa: BLE001 — timeout ends the harvest
                    pass
                subtitles = [m for m in seen if m.get('type') == 'subtitle']
                assert subtitles == [], subtitles
                assert any(m.get('type') == 'error' for m in seen), seen


# ---- Wave-5: Analysis + Simulation job kinds --------------------------------
def test_fastpath_analyze_and_simulate_classification():
    from brain import fastpath
    ctx = fastpath.IntentCtx()
    res = fastpath.run_intent('analyze my disk usage', ctx)
    assert res is not None and res.done is False
    # task_kind uses the APPROVED analysis/simulation enum (shape_map octagram/
    # triangle) — not the generic 'llm'
    assert res.job_kind == 'analysis' and res.task_kind == 'analysis'
    res = fastpath.run_intent('simulate a dual-boot layout', ctx)
    assert res is not None and res.done is False
    assert res.job_kind == 'simulation' and res.task_kind == 'simulation'
    res = fastpath.run_intent('analyse the crash log', ctx)
    assert res is not None and res.job_kind == 'analysis'
    # falls through to the agent loop (done=False) — no tool, no narration
    assert res.text == ''
    # unrelated commands unaffected
    assert fastpath.run_intent('echo hi', ctx).job_kind is None


def test_simulation_job_runs_with_tools_off(token_path, fake_chat):
    """Wave-5 Simulation kind: fastpath classifies -> agent loop runs with
    tools=[] and NO prompt-block (no side effects are ever possible)."""
    calls = fake_chat([{'text': 'If we assume 8 % growth…'}])
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as ws_cli:
            assert _auth(ws_cli, 'cli')['type'] == 'auth_ok'
            job = _command(ws_cli, 'simulate the 2027 budget outlook')
            done, _ = _recv_until(
                ws_cli, lambda m: m.get('type') == 'job_event'
                and m.get('status') == 'done' and m.get('job') == job)
            assert done['text'].startswith('If we assume')
    assert len(calls) == 1
    # tools suppressed for simulation (None/empty) and no textual catalog
    assert not calls[0]['tools']
    sys_prompt = calls[0]['messages'][0]['content']
    assert 'Tool calling:' not in sys_prompt
    # the kind rode the runner snapshot end-to-end
    from brain.jobs.engine import get_engine
    assert get_engine().kind_of(job) == 'simulation'


def test_analysis_job_keeps_tools_and_records_kind(token_path, fake_chat):
    calls = fake_chat([
        {'text': '', 'tool_calls': [{
            'id': 'c1', 'type': 'function',
            'function': {'name': 't_an_probe',
                         'arguments': json.dumps({'q': 'du'})}}]},
        {'text': 'Analysis complete — 3 large directories.'},
    ])
    from brain import tools as reg
    reg.register('t_an_probe', lambda q: '82% /home', description='probe',
                 schema={'type': 'object',
                         'properties': {'q': {'type': 'string',
                                              'description': 'target'}},
                         'required': ['q'], 'additionalProperties': False})
    try:
        with TestClient(app) as client:
            with client.websocket_connect('/ws') as ws_cli:
                assert _auth(ws_cli, 'cli')['type'] == 'auth_ok'
                job = _command(ws_cli, 'analyze my disk usage')
                done, _ = _recv_until(
                    ws_cli, lambda m: m.get('type') == 'job_event'
                    and m.get('status') == 'done' and m.get('job') == job)
                assert done['text'] == 'Analysis complete — 3 large directories.'
        # analysis keeps READ-ONLY tools; risky/lock tools are stripped
        # (evolution contract: read-only, lock:false) — shell is risky
        tool_names = {t['function']['name'] for t in (calls[0]['tools'] or [])}
        assert 't_an_probe' in tool_names
        assert 'shell' not in tool_names and 'uia' not in tool_names
        from brain.jobs.engine import get_engine
        assert get_engine().kind_of(job) == 'analysis'
    finally:
        reg._registry.pop('t_an_probe', None)
        reg._META.pop('t_an_probe', None)


# ---- Wave-5: answer/report emitters e2e (APPROVED 2026-10-07) ---------------
def test_answer_frame_fastpath_roles_ui_cli_only(token_path, fake_chat):
    fake_chat([{'text': 'never'}])                 # echo never reaches the model
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as ws_ui:
            assert _auth(ws_ui, 'ui')['type'] == 'auth_ok'
            with client.websocket_connect('/ws') as ws_cli:
                assert _auth(ws_cli, 'cli')['type'] == 'auth_ok'
                with client.websocket_connect('/ws') as ws_body:
                    assert _auth(ws_body, 'body')['type'] == 'auth_ok'
                    job = _command(ws_cli, 'echo answer frame')
                    ans, _ = _recv_until(ws_ui, lambda m: m.get('type') == 'answer')
                    assert ans['job'] == job
                    assert ans['text'] == 'Echo: answer frame'
                    assert ans['format'] == 'answer' and ans['v'] == 1
                    assert 'provider' not in ans and 'model' not in ans
                    # cli gets it too
                    _recv_until(ws_cli, lambda m: m.get('type') == 'answer'
                                and m.get('job') == job)
                    # body never does (ui+cli only — decision condition 5)
                    try:
                        bodyf = _recv_json(ws_body, timeout=1.0)
                        assert bodyf.get('type') != 'answer', bodyf
                    except Exception:  # noqa: BLE001 — quiet body = pass
                        pass


def test_answer_frame_agent_reply_carries_provider(token_path, fake_chat):
    calls = fake_chat([{'text': 'Four is the answer.'}])
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as ws_ui:
            assert _auth(ws_ui, 'ui')['type'] == 'auth_ok'
            with client.websocket_connect('/ws') as ws_cli:
                assert _auth(ws_cli, 'cli')['type'] == 'auth_ok'
                job = _command(ws_cli, 'what is two plus two')
                ans, _ = _recv_until(ws_ui, lambda m: m.get('type') == 'answer'
                                     and m.get('job') == job)
                assert ans['text'] == 'Four is the answer.'
                assert ans['provider'] == 'fake-provider'
                assert ans['model'] == 'fake-model'
    assert len(calls) == 1


def test_analysis_emits_answer_and_capped_report(token_path, fake_chat):
    long_body = '\n\n'.join(f'Finding {i}: ' + ('data ' * 120)
                            for i in range(25))
    fake_chat([{'text': long_body}])
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as ws_ui:
            assert _auth(ws_ui, 'ui')['type'] == 'auth_ok'
            with client.websocket_connect('/ws') as ws_cli:
                assert _auth(ws_cli, 'cli')['type'] == 'auth_ok'
                job = _command(ws_cli, 'analyze the telemetry dump')
                ans, _ = _recv_until(ws_ui, lambda m: m.get('type') == 'answer'
                                     and m.get('job') == job)
                rep, _ = _recv_until(ws_ui, lambda m: m.get('type') == 'report'
                                     and m.get('job') == job)
                assert ans['format'] == 'answer'
                assert rep['format'] == 'report'
                assert rep['title'].startswith('Analysis —')
                assert len(rep['summary']) <= 500
                assert len(rep['sections']) <= 10
                assert all(len(s['text']) <= 2000 for s in rep['sections'])
                # job_event now echoes kind (APPROVED additive field)
                ev, _ = _recv_until(ws_cli, lambda m: m.get('type') == 'job_event'
                                    and m.get('status') == 'done'
                                    and m.get('job') == job)
                assert ev.get('kind') == 'analysis'


def test_ws_command_kind_parent_echo_and_validation(token_path, fake_chat):
    fake_chat([{'text': 'tagged reply'}])
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as ws_cli:
            assert _auth(ws_cli, 'cli')['type'] == 'auth_ok'
            # invalid kind -> loud E_BAD_MSG, no job
            ws_cli.send_text(json.dumps({'type': 'command', 'v': 1,
                                         'text': 'x', 'kind': 'bogus'}))
            err, _ = _recv_until(ws_cli, lambda m: m.get('type') == 'error')
            assert err['code'] == 'E_BAD_MSG' and 'kind' in err['detail']
            # valid kind + parent -> job_event echoes both
            ws_cli.send_text(json.dumps({'type': 'command', 'v': 1,
                                         'text': 'parented analysis',
                                         'kind': 'analysis',
                                         'parent': 'j_20261007_0009'}))
            ack, _ = _recv_until(ws_cli, lambda m: m.get('type') == 'ack')
            job = ack['job']
            done, _ = _recv_until(ws_cli, lambda m: m.get('type') == 'job_event'
                                  and m.get('status') == 'done'
                                  and m.get('job') == job)
            assert done['kind'] == 'analysis'
            assert done['parent'] == 'j_20261007_0009'
            # plain command: kind/parent ABSENT from job_event (additive)
            job2 = _command(ws_cli, 'plain echo now')
            done2, _ = _recv_until(ws_cli, lambda m: m.get('type') == 'job_event'
                                   and m.get('status') == 'done'
                                   and m.get('job') == job2)
            assert 'kind' not in done2 and 'parent' not in done2


# ---- AUD-21: SAFE MODE blocks tool dispatch --------------------------------
def test_safe_mode_blocks_tool_dispatch(token_path, fake_chat):
    from brain import coreguard, tools as reg
    executed = []
    reg.register('t_safe_probe', lambda q: executed.append(q) or 'ok',
                 description='would run',
                 schema={'type': 'object',
                         'properties': {'q': {'type': 'string',
                                              'description': 'q'}},
                         'required': ['q'], 'additionalProperties': False})
    coreguard.SAFE_MODE = {'active': True}
    try:
        calls = fake_chat([
            {'text': '', 'tool_calls': [{
                'id': 'c1', 'type': 'function',
                'function': {'name': 't_safe_probe',
                             'arguments': json.dumps({'q': 'x'})}}]},
            {'text': 'Understood.'},
        ])
        with TestClient(app) as client:
            with client.websocket_connect('/ws') as ws_cli:
                assert _auth(ws_cli, 'cli')['type'] == 'auth_ok'
                job = _command(ws_cli, 'probe under safe mode')
                done, _ = _recv_until(
                    ws_cli, lambda m: m.get('type') == 'job_event'
                    and m.get('status') == 'done' and m.get('job') == job)
                assert done['text'] == 'Understood.'
        # the tool NEVER executed; the refusal was fed back to the model
        assert executed == [], 'SAFE MODE must block tool execution'
        tool_msg = [m for m in calls[1]['messages'] if m.get('role') == 'tool']
        assert tool_msg and 'SAFE MODE' in tool_msg[0]['content']
    finally:
        coreguard.SAFE_MODE = {'active': False}
        reg._registry.pop('t_safe_probe', None)
        reg._META.pop('t_safe_probe', None)


# ---- AUD-22: memory/skills injection + schedule re-arm ----------------------
def test_memory_and_skills_injected_as_untrusted_context(token_path, fake_chat,
                                                         monkeypatch):
    import brain.memory as mempkg
    import brain.memory.skills as skillsmod
    monkeypatch.setattr(
        mempkg, 'retrieve',
        lambda q, k=None, owner=None: [
            {'id': 1, 'text': 'user prefers dark mode', 'category': 'pref',
             'pinned': True, 'ts': 0, 'source': 'test', 'score': 1.0}],
        raising=False)
    monkeypatch.setattr(
        skillsmod, 'active_skills',
        lambda min_confidence=None: [
            {'id': 9, 'text': 'skill: summarize clips', 'category': 'skill',
             'ts': 0, 'source': 'skills', 'score': 1.0}])
    calls = fake_chat([{'text': 'Noted.'}])
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as ws_cli:
            assert _auth(ws_cli, 'cli')['type'] == 'auth_ok'
            job = _command(ws_cli, 'remembers anything?')
            done, _ = _recv_until(
                ws_cli, lambda m: m.get('type') == 'job_event'
                and m.get('status') == 'done' and m.get('job') == job)
            assert done['text'] == 'Noted.'
    msgs = calls[0]['messages']
    # context sits BETWEEN history and the live question, untrusted-framed
    ctx = [m for m in msgs if m.get('role') == 'user'
           and 'UNTRUSTED' in m.get('content', '')]
    assert ctx, [m.get('content', '')[:60] for m in msgs]
    assert 'user prefers dark mode' in ctx[0]['content']
    assert 'summarize clips' in ctx[0]['content']       # skills same turn
    assert msgs[-1] == {'role': 'user', 'content': 'remembers anything?'}
    # NEVER injected as a system instruction (AGENTS §9 framing)
    assert all('UNTRUSTED' not in m.get('content', '')
               for m in msgs if m.get('role') == 'system')


def test_personal_memory_excluded_for_free_provider_chains(token_path,
                                                           fake_chat,
                                                           monkeypatch):
    """providers.allow_free_models_for_personal_data=false (repo config):
    personal categories never enter prompts (free providers are in chain)."""
    import brain.memory as mempkg
    monkeypatch.setattr(
        mempkg, 'retrieve',
        lambda q, k=None, owner=None: [
            {'id': 1, 'text': 'user lives at 12 Main Stsecret Road',
             'category': 'identity', 'pinned': True, 'ts': 0,
             'source': 'test', 'score': 1.0},
            {'id': 2, 'text': 'prefers metric units', 'category': 'pref',
             'pinned': False, 'ts': 0, 'source': 'test', 'score': 0.9}],
        raising=False)
    calls = fake_chat([{'text': 'Understood.'}])
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as ws_cli:
            assert _auth(ws_cli, 'cli')['type'] == 'auth_ok'
            job = _command(ws_cli, 'any personal context?')
            done, _ = _recv_until(
                ws_cli, lambda m: m.get('type') == 'job_event'
                and m.get('status') == 'done' and m.get('job') == job)
            assert done['text'] == 'Understood.'
    blob = json.dumps(calls[0]['messages'])
    assert '12 Main Stsecret Road' not in blob, 'personal row leaked to prompt'
    assert 'prefers metric units' in blob           # non-personal still there


def test_memory_failure_injects_nothing_and_turn_still_works(token_path,
                                                             fake_chat,
                                                             monkeypatch):
    import brain.memory as mempkg

    def _boom(q, k=None, owner=None):
        raise RuntimeError('db locked')

    monkeypatch.setattr(mempkg, 'retrieve', _boom, raising=False)
    calls = fake_chat([{'text': 'Still fine.'}])
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as ws_cli:
            assert _auth(ws_cli, 'cli')['type'] == 'auth_ok'
            job = _command(ws_cli, 'quick question')
            done, _ = _recv_until(
                ws_cli, lambda m: m.get('type') == 'job_event'
                and m.get('status') == 'done' and m.get('job') == job)
            assert done['text'] == 'Still fine.'
    assert 'UNTRUSTED' not in json.dumps(calls[0]['messages'])


def test_schedule_arm_all_called_at_startup(monkeypatch):
    import brain.tools.schedule as sched
    calls = []
    monkeypatch.setattr(sched, 'arm_all',
                        lambda loop=None: calls.append(True) or True)
    with TestClient(app) as client:
        r = client.get('/status', headers={'X-Raphael-Token': TEST_TOKEN})
        assert r.status_code == 200
    assert calls, 'arm_all must run once at startup (timers survive restart)'


# ---- AUD-08: body session CANNOT claim a non-voice channel ------------------
def test_body_cannot_claim_click_or_text_via(token_path, fake_chat):
    """Channel derives ONLY from the authenticated role: a body session
    sending via:'click'/'text' is still treated as VOICE — a high-risk yes
    from it is rejected, never granted."""
    fake_chat([{'text': 'never'}])
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as ws_body:
            assert _auth(ws_body, 'body')['type'] == 'auth_ok'
            with client.websocket_connect('/ws') as ws_cli:
                assert _auth(ws_cli, 'cli')['type'] == 'auth_ok'
                job = _command(ws_cli, 'delete my downloads folder')
                _recv_until(ws_cli, lambda m: m.get('type') == 'needs_confirm'
                            and m.get('job') == job)
                # attacker-style: body claims a trusted channel
                ws_body.send_text(json.dumps({'type': 'confirm_resp', 'v': 1,
                                              'job': job, 'answer': 'yes',
                                              'via': 'click'}))
                ack, _ = _recv_until(ws_body, lambda m: m.get('type') == 'ack'
                                     and m.get('accepted') is False)
                # role=body => voice => high-risk affirmative REJECTED
                assert ack.get('accepted') is False, ack
                from brain.jobs import store as job_store
                assert job_store.get_job(job_store.parse_job_ref(job))[
                    'status'] == 'awaiting_confirm'
                # the trusted cli channel still works afterwards
                ws_cli.send_text(json.dumps({'type': 'confirm_resp', 'v': 1,
                                             'job': job, 'answer': 'yes'}))
                ack2, _ = _recv_until(ws_cli, lambda m: m.get('type') == 'ack'
                                      and m.get('accepted') is True)
                assert ack2['job'] == job


# ---- AUD-09: registry confirm category propagates (voice_ok = reviewed low)
def test_registry_confirm_category_voice_ok_downgrades(token_path, fake_chat):
    from brain import tools as reg
    reg.register('t_reviewed_low', lambda q: 'ok',
                 description='reviewed voice-ok tool', confirm='voice_ok',
                 schema={'type': 'object',
                         'properties': {'q': {'type': 'string',
                                              'description': 'q'}},
                         'required': ['q'], 'additionalProperties': False})
    try:
        calls = fake_chat([
            {'text': '', 'tool_calls': [{
                'id': 'c1', 'type': 'function',
                'function': {'name': 't_reviewed_low',
                             'arguments': json.dumps({'q': 'x'})}}]},
            {'text': 'Done.'},
        ])
        with TestClient(app) as client:
            with client.websocket_connect('/ws') as ws_cli:
                assert _auth(ws_cli, 'cli')['type'] == 'auth_ok'
                job = _command(ws_cli, 'use the reviewed tool')
                conf, _ = _recv_until(ws_cli, lambda m: m.get('type') == 'needs_confirm'
                                      and m.get('job') == job)
                # explicit reviewed policy downgrades to LOW (voice-eligible)
                assert conf['risk'] == 'low', conf
                ws_cli.send_text(json.dumps({'type': 'confirm_resp', 'v': 1,
                                             'job': job, 'answer': 'yes'}))
                ack, _ = _recv_until(ws_cli, lambda m: m.get('type') == 'ack'
                                     and m.get('accepted') is True)
                assert ack['job'] == job
                done, _ = _recv_until(ws_cli, lambda m: m.get('type') == 'job_event'
                                      and m.get('status') == 'done'
                                      and m.get('job') == job)
                assert done['text'] == 'Done.'
        # ...and an unreviewed category stays NON-voice (action overridden)
        fake_chat([{'text': '', 'tool_calls': [{
            'id': 'c9', 'type': 'function',
            'function': {'name': 't_unreviewed',
                         'arguments': json.dumps({'q': 'x'})}}]},
            {'text': 'Done.'}])
        reg.register('t_unreviewed', lambda q: 'ok',
                     description='has a confirm category, not voice_ok',
                     confirm='system_settings_change',
                     schema={'type': 'object',
                             'properties': {'q': {'type': 'string',
                                                  'description': 'q'}},
                             'required': ['q'], 'additionalProperties': False})
        with TestClient(app) as client:
            with client.websocket_connect('/ws') as ws_cli:
                assert _auth(ws_cli, 'cli')['type'] == 'auth_ok'
                job = _command(ws_cli, 'use the unreviewed tool')
                conf, _ = _recv_until(ws_cli, lambda m: m.get('type') == 'needs_confirm'
                                      and m.get('job') == job)
                assert conf['risk'] == 'high'
                assert conf['question']  # gated, non-voice
                ws_cli.send_text(json.dumps({'type': 'cancel', 'v': 1,
                                             'job': job, 'scope': 'full'}))
                _recv_until(ws_cli, lambda m: m.get('type') == 'ack'
                            and m.get('cancelled') is True)
    finally:
        reg._registry.pop('t_reviewed_low', None)
        reg._META.pop('t_reviewed_low', None)
        reg._registry.pop('t_unreviewed', None)
        reg._META.pop('t_unreviewed', None)

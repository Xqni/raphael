"""Router seam tests (INTERFACES §a): llm.py talks ONLY to brain.router.chat;
the stub degrades structured when the facade hasn't landed; RouterError codes
map to PROTOCOL §10; stream frames normalize. No network, no keys, no providers.
"""
import asyncio

import pytest

from brain import llm


@pytest.fixture(autouse=True)
def _enable_router(monkeypatch):
    monkeypatch.delenv('RAPHAEL_DISABLE_ROUTER', raising=False)
    monkeypatch.setenv('RAPHAEL_LLM_TIMEOUT_S', '5')
    yield


async def _collect(agen):
    return [f async for f in agen]


# ---- stub until the router lane lands ---------------------------------------
@pytest.mark.asyncio
async def test_stub_when_facade_missing(monkeypatch):
    import brain.router as router
    monkeypatch.delattr(router, 'chat', raising=False)
    monkeypatch.delenv('RAPHAEL_DISABLE_ROUTER', raising=False)
    res = await llm.chat([{'role': 'user', 'content': 'hi'}])
    assert res.ok is False
    assert res.code == 'E_OFFLINE'
    assert 'chat' in (res.error or '')


@pytest.mark.asyncio
async def test_disabled_router_is_offline(monkeypatch):
    monkeypatch.setenv('RAPHAEL_DISABLE_ROUTER', '1')
    res = await llm.chat([{'role': 'user', 'content': 'hi'}])
    assert res.ok is False and res.code == 'E_OFFLINE'
    assert 'RAPHAEL_DISABLE_ROUTER' in res.error


@pytest.mark.asyncio
async def test_disabled_router_stream_yields_error_frame(monkeypatch):
    monkeypatch.setenv('RAPHAEL_DISABLE_ROUTER', '1')
    agen = await llm.chat([{'role': 'user', 'content': 'hi'}], stream=True)
    frames = await _collect(agen)
    assert frames[-1]['finish'] == 'error'
    assert frames[-1]['code'] == 'E_OFFLINE'


# ---- facade present: normalised results ------------------------------------
@pytest.mark.asyncio
async def test_facade_dict_normalized(monkeypatch):
    import brain.router as router

    async def chat(messages, tools=None, stream=False, purpose='chat'):
        assert purpose in ('chat', 'tool', 'plan', 'ack')
        assert messages[0]['role'] == 'user'
        return {'text': 'hello', 'tool_calls': [], 'finish': 'stop',
                'provider': 'groq', 'model': 'llama-x',
                'usage': {'input': 3, 'output': 5}}

    monkeypatch.setattr(router, 'chat', chat, raising=False)
    res = await llm.chat([{'role': 'user', 'content': 'hi'}], purpose='chat')
    assert res.ok is True
    assert res.text == 'hello'
    assert res.provider == 'groq' and res.model == 'llama-x'
    assert res.finish == 'stop' and res.usage == {'input': 3, 'output': 5}


@pytest.mark.asyncio
async def test_facade_error_frame_becomes_failed_result(monkeypatch):
    import brain.router as router

    async def chat(messages, tools=None, stream=False, purpose='chat'):
        return {'error': 'rate limited', 'code': 'E_PROVIDER_429',
                'provider': 'groq', 'model': 'x'}

    monkeypatch.setattr(router, 'chat', chat, raising=False)
    res = await llm.chat([{'role': 'user', 'content': 'hi'}])
    assert res.ok is False
    assert res.code == 'E_PROVIDER_429'
    assert 'rate limited' in res.error


@pytest.mark.asyncio
async def test_router_exception_maps_to_protocol_code(monkeypatch):
    import brain.router as router

    class RouterError(Exception):
        def __init__(self):
            super().__init__('circuit open')
            self.code = 'E_PROVIDER_429'

    async def chat(messages, tools=None, stream=False, purpose='chat'):
        raise RouterError()

    monkeypatch.setattr(router, 'chat', chat, raising=False)
    res = await llm.chat([{'role': 'user', 'content': 'hi'}])
    assert res.ok is False and res.code == 'E_PROVIDER_429'


@pytest.mark.asyncio
async def test_provider_exception_never_raises(monkeypatch):
    import brain.router as router

    async def chat(messages, tools=None, stream=False, purpose='chat'):
        raise ConnectionError('boom')

    monkeypatch.setattr(router, 'chat', chat, raising=False)
    res = await llm.chat([{'role': 'user', 'content': 'hi'}])
    assert res.ok is False and res.code == 'E_OFFLINE'


# ---- streaming --------------------------------------------------------------
@pytest.mark.asyncio
async def test_stream_yields_deltas_then_final_frame(monkeypatch):
    import brain.router as router

    async def chat(messages, tools=None, stream=False, purpose='chat'):
        async def _gen():
            yield {'delta': 'Hel'}
            yield {'delta': 'lo.'}
            yield {'finish': 'stop', 'provider': 'groq', 'model': 'x'}
        return _gen()

    monkeypatch.setattr(router, 'chat', chat, raising=False)
    agen = await llm.chat([{'role': 'user', 'content': 'hi'}], stream=True)
    frames = await _collect(agen)
    assert frames[0] == {'delta': 'Hel'}
    assert ''.join(f.get('delta', '') for f in frames) == 'Hello.'
    assert frames[-1]['finish'] == 'stop'
    assert frames[-1]['provider'] == 'groq'


@pytest.mark.asyncio
async def test_stream_failure_yields_error_frame_not_exception(monkeypatch):
    import brain.router as router

    async def chat(messages, tools=None, stream=False, purpose='chat'):
        async def _gen():
            yield {'delta': 'partial'}
            raise ConnectionError('mid-stream drop')
        return _gen()

    monkeypatch.setattr(router, 'chat', chat, raising=False)
    agen = await llm.chat([{'role': 'user', 'content': 'hi'}], stream=True)
    frames = await _collect(agen)
    assert frames[0] == {'delta': 'partial'}
    assert frames[-1]['finish'] == 'error'
    assert frames[-1]['code'] == 'E_OFFLINE'


# ---- plan() compat ----------------------------------------------------------
@pytest.mark.asyncio
async def test_plan_compat_uses_chat(monkeypatch):
    import brain.router as router
    seen = {}

    async def chat(messages, tools=None, stream=False, purpose='chat'):
        seen['messages'] = messages
        seen['purpose'] = purpose
        return {'text': 'planned', 'finish': 'stop', 'provider': 'p',
                'model': 'm'}

    monkeypatch.setattr(router, 'chat', chat, raising=False)
    res = await llm.plan('do the thing', task_kind='llm')
    assert res.ok and res.text == 'planned'
    assert seen['messages'][0] == {'role': 'user', 'content': 'do the thing'}
    assert seen['purpose'] == 'plan'

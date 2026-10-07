"""Router seam — brain-core's adapter over the INTERFACES §a facade.

**Rule (INTERFACES §a): no lane calls a provider HTTP API directly.** This
module only ever talks to `brain.router.chat()` (the facade the router lane
exports). Until that lane lands, a STUB answers with a structured
`LLMResult(ok=False, code='E_OFFLINE')` — the agent loop degrades, never
crashes, and never reaches around the facade.

Contract for loop.py:
  chat(messages, tools=None, stream=False, purpose="chat") -> LLMResult | async-iterator
  plan(text, task_kind=None)                                -> LLMResult (compat)

Any provider failure (facade missing, discovery failure, circuit open, rate
limit, timeout, RouterError) degrades to LLMResult(ok=False, code=PROTOCOL
§10 code) — the loop maps these to job errors, never a crash.

RAPHAEL_DISABLE_ROUTER=1 forces the stub (tests use this; also the kill
switch when providers are misbehaving).
"""
import asyncio
import os
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional


@dataclass
class LLMResult:
    ok: bool
    text: str = ''
    provider: Optional[str] = None
    model: Optional[str] = None
    code: Optional[str] = None   # PROTOCOL §10 error code when not ok
    error: Optional[str] = None
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    finish: Optional[str] = None        # 'stop' | 'tool_calls' | 'length'
    usage: Dict[str, int] = field(default_factory=dict)


def router_available() -> bool:
    """The INTERFACES §a facade (`brain.router.chat`) present and enabled?"""
    if os.environ.get('RAPHAEL_DISABLE_ROUTER') == '1':
        return False
    try:
        import brain.router as router
        return callable(getattr(router, 'chat', None))
    except Exception:  # noqa: BLE001 — router package may be broken/absent
        return False


def _facade():
    import brain.router as router
    return getattr(router, 'chat', None)


def _code_for(exc: BaseException) -> str:
    """Map a router-lane exception to a PROTOCOL §10 code (INTERFACES §a:
    RouterError carries its own code)."""
    code = getattr(exc, 'code', None)
    if isinstance(code, str) and code.startswith('E_'):
        return code
    name = type(exc).__name__
    if 'RouterError' in name:
        return 'E_INTERNAL'
    if 'ProviderUnavailable' in name:
        return 'E_OFFLINE'
    if 'ProviderError' in name:
        return getattr(exc, 'code', None) or 'E_PROVIDER_5XX'
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return 'E_TIMEOUT'
    if isinstance(exc, ConnectionError):
        return 'E_OFFLINE'
    return 'E_INTERNAL'


def _stub(reason: str) -> LLMResult:
    return LLMResult(ok=False, code='E_OFFLINE', error=reason)


def _normalize(res: Any) -> LLMResult:
    """chat() returns a dict per INTERFACES §a — normalize leniently so a
    partially-shaped facade result still degrades instead of raising."""
    if isinstance(res, LLMResult):
        return res
    if not isinstance(res, dict):
        return _stub(f'router facade returned {type(res).__name__}, expected dict')
    if res.get('error') and not res.get('text'):
        return LLMResult(ok=False,
                         code=res.get('code') or 'E_INTERNAL',
                         error=str(res.get('error'))[:300],
                         provider=res.get('provider'), model=res.get('model'))
    return LLMResult(
        ok=True,
        text=res.get('text') or '',
        provider=res.get('provider'),
        model=res.get('model'),
        finish=res.get('finish') or 'stop',
        tool_calls=list(res.get('tool_calls') or []),
        usage=dict(res.get('usage') or {}),
    )


async def chat(messages: List[Dict[str, Any]],
               tools: Optional[List[Dict[str, Any]]] = None,
               stream: bool = False,
               purpose: str = 'chat',
               task_kind: Optional[str] = None,
               timeout: Optional[float] = None):
    """INTERFACES §a facade call. Non-stream -> LLMResult; stream -> async
    iterator of {'delta': str, ...} dicts ending in a final frame carrying
    {'finish', 'provider', 'model', 'tool_calls'?}."""
    timeout = timeout or float(os.environ.get('RAPHAEL_LLM_TIMEOUT_S', '45'))
    if not router_available():
        reason = ('router disabled (RAPHAEL_DISABLE_ROUTER=1)'
                  if os.environ.get('RAPHAEL_DISABLE_ROUTER') == '1'
                  else 'router facade brain.router.chat not available yet '
                       '(router lane pending)')
        if stream:
            async def _stub_stream():
                yield {'finish': 'error', 'provider': None, 'model': None,
                       'code': 'E_OFFLINE', 'error': reason}
            return _stub_stream()
        return _stub(reason)

    facade = _facade()
    if stream:
        return _stream_via_facade(facade, messages, tools, purpose, task_kind,
                                  timeout)
    try:
        res = await asyncio.wait_for(
            facade(messages, tools=tools, stream=False, purpose=purpose),
            timeout=timeout)
        out = _normalize(res)
        if out.ok and task_kind and not out.provider:
            out.provider = None  # provider/model always reported by the facade
        return out
    except Exception as e:  # noqa: BLE001 — degradation, never a crash
        return LLMResult(ok=False, code=_code_for(e), error=str(e)[:300])


async def _stream_via_facade(facade, messages, tools, purpose, task_kind,
                             timeout) -> AsyncIterator[Dict[str, Any]]:
    """Await the facade's async iterator (it may be a coroutine returning an
    iterator), enforce the timeout over the WHOLE stream, normalize frames."""
    deadline = asyncio.get_event_loop().time() + timeout
    try:
        agen = facade(messages, tools=tools, stream=True, purpose=purpose)
        if asyncio.iscoroutine(agen):
            agen = await agen
        async for frame in agen:
            if asyncio.get_event_loop().time() > deadline:
                yield {'finish': 'error', 'provider': None, 'model': None,
                       'code': 'E_TIMEOUT', 'error': f'stream >{timeout}s'}
                return
            if isinstance(frame, dict):
                yield frame
            else:
                yield {'delta': str(frame)}
    except Exception as e:  # noqa: BLE001 — degradation, never a crash
        yield {'finish': 'error', 'provider': None, 'model': None,
               'code': _code_for(e), 'error': str(e)[:300]}


async def plan(text: str, task_kind: Optional[str] = None,
               timeout: Optional[float] = None) -> LLMResult:
    """Legacy single-shot entry (loop.py pre-persona callers, tests)."""
    return await chat([{'role': 'user', 'content': text}],
                      purpose='plan', task_kind=task_kind, timeout=timeout)

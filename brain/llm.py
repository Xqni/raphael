"""Router seam — thin adapter over brain/router/core.py (router-dev owns that
package; this file stays on brain-dev's side of the boundary).

Contract for loop.py: `plan(text, task_kind) -> LLMResult`. ANY provider
failure (import error, discovery failure, circuit open, rate limit, timeout)
degrades to a structured LLMResult(ok=False, code=PROTOCOL §10 code) — the
agent loop NEVER crashes on providers.

RAPHAEL_DISABLE_ROUTER=1 forces the fallback path (tests use this; also the
kill switch when providers are misbehaving).
"""
import asyncio
import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class LLMResult:
    ok: bool
    text: str = ''
    provider: Optional[str] = None
    model: Optional[str] = None
    code: Optional[str] = None   # PROTOCOL §10 error code when not ok
    error: Optional[str] = None


def router_available() -> bool:
    if os.environ.get('RAPHAEL_DISABLE_ROUTER') == '1':
        return False
    try:
        import brain.router.core  # noqa: F401
        return True
    except Exception:  # noqa: BLE001 — router package may be broken/absent
        return False


def _code_for(exc: BaseException) -> str:
    name = type(exc).__name__
    if 'ProviderUnavailable' in name:
        return 'E_OFFLINE'
    if 'ProviderError' in name:
        return getattr(exc, 'code', None) or 'E_PROVIDER_5XX'
    code = getattr(exc, 'code', None)
    if isinstance(code, str) and code.startswith('E_'):
        return code
    return 'E_INTERNAL'


async def plan(text: str, task_kind: Optional[str] = None,
               timeout: Optional[float] = None) -> LLMResult:
    timeout = timeout or float(os.environ.get('RAPHAEL_LLM_TIMEOUT_S', '45'))  # long replies need generation time
    if not router_available():
        return LLMResult(ok=False, code='E_OFFLINE',
                         error='no provider (router disabled or unavailable)')
    try:
        from brain.router import core as router_core
        provider, model = await asyncio.wait_for(
            router_core.acquire_model(task_kind=task_kind), timeout=timeout)
        res = await asyncio.wait_for(
            router_core.complete(provider, model, prompt=text, task_kind=task_kind),
            timeout=timeout,
        )
        if getattr(res, 'ok', False):
            return LLMResult(ok=True, text=res.text or '',
                             provider=getattr(res, 'provider', provider),
                             model=getattr(res, 'model', model))
        return LLMResult(ok=False,
                         code=getattr(res, 'error_code', None) or 'E_INTERNAL',
                         error=getattr(res, 'error', None))
    except asyncio.TimeoutError:
        return LLMResult(ok=False, code='E_TIMEOUT',
                         error=f'provider timeout >{timeout}s')
    except Exception as e:  # noqa: BLE001 — degradation, never a crash
        return LLMResult(ok=False, code=_code_for(e), error=str(e)[:200])

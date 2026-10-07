"""Call seams that may be sync (blocking HTTP) or async — ARCHITECTURE §4:
blocking work never runs ON the brain's main loop.

- coroutine function  -> awaited directly
- plain function      -> executed in a worker thread (asyncio.to_thread),
                         then awaited if it returned an awaitable anyway
Used for router.vision / router.chat so the same code works with the real
router, a scripted test double, and either shipping style.
"""
from __future__ import annotations

import asyncio
import inspect
from typing import Any, Awaitable, Callable


async def maybe_await(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Invoke `fn` off-loop when it is synchronous; await when it is async."""
    if fn is None:
        raise RuntimeError("no seam callable configured")
    if inspect.iscoroutinefunction(fn):
        return await fn(*args, **kwargs)
    res = fn(*args, **kwargs)
    if inspect.isawaitable(res):
        return await res
    return res


async def maybe_await_offloop(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Like maybe_await, but a SYNC `fn` runs in a worker thread first (never
    block the main loop — use for anything that touches network/HTTP)."""
    if fn is None:
        raise RuntimeError("no seam callable configured")
    if inspect.iscoroutinefunction(fn):
        return await fn(*args, **kwargs)
    res = await asyncio.to_thread(lambda: fn(*args, **kwargs))
    if inspect.isawaitable(res):
        return await res
    return res

"""Dependency wiring + the sync→main-loop bridge for the computer-use tools.

loop.py runs local tools in a worker thread (`asyncio.to_thread`), but the act
pipeline only works ON the brain's main loop. `run_sync` bridges:

    sync tool fn (worker thread) --run_coroutine_threadsafe--> main loop

Main-loop resolution order (AGENT_RULES §2 keeps me out of brain-core files):
  1. bind_loop(...) / deps.main_loop   — explicit hook (tests; future app.py call)
  2. engine._queue_loop                — loop where the job workers started
  3. hub._ping_task.get_loop()         — loop where the WS hub started
  none -> structured RuntimeError (never a hang, never a wrong loop)

All seams (gateway/chat/vision/mode/confirm) are injectable for tests via
set_deps(); production defaults resolve lazily so importing this package at
auto-discovery time needs no running loop, no network, and no .env.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class Deps:
    config: Any = None                      # VisionConfig
    gate: Any = None                        # CloudVisionGate
    gateway: Any = None                     # BodyGateway-like (async seam)
    chat_fn: Optional[Callable[..., Any]] = None       # brain.router.chat
    vision_fn: Optional[Callable[..., Any]] = None     # brain.router.vision
    is_private: Optional[Callable[[], bool]] = None    # brain.mode.get_mode().private
    confirm_fn: Optional[Callable[[str], Any]] = None  # question -> 'yes'|'no'|'timeout'
    emit_fn: Optional[Callable[..., Any]] = None       # step progress (generic text only)
    cancelled_fn: Optional[Callable[[], bool]] = None  # per-job cancel polling
    main_loop: Optional[asyncio.AbstractEventLoop] = None
    chat_timeout_s: float = 60.0
    vision_timeout_s: float = 60.0
    job_rowid: Optional[int] = None    # owning job rowid (None = no job context)


_deps: Optional[Deps] = None


def fill_defaults(d: Deps) -> Deps:
    """Fill every None seam with its production default (lazy, loop-free,
    network-free at fill time). confirm/emit/cancel stay None on purpose —
    the runner supplies safe built-ins (fail-closed / no-op / store polling)."""
    if d.config is None:
        from brain.vision.config import load_config
        d.config = load_config()
    if d.gate is None:
        from brain.vision.gate import CloudVisionGate
        d.gate = CloudVisionGate(d.config)
    if d.gateway is None:
        from .gateway import BodyGateway
        d.gateway = BodyGateway()
    if d.is_private is None:
        def _is_private() -> bool:
            from brain.mode import get_mode
            return bool(get_mode().private)
        d.is_private = _is_private
    if d.chat_fn is None:
        def _chat(messages, tools=None, purpose="tool", **kw):
            from brain.router import chat          # router lane seam (INTERFACES §a)
            return chat(messages, tools=tools, purpose=purpose, **kw)
        d.chat_fn = _chat
    if d.vision_fn is None:
        def _vision(image, question, purpose="vision", **kw):
            from brain.router import vision        # router lane seam (INTERFACES §a)
            return vision(image, question, purpose=purpose, **kw)
        d.vision_fn = _vision
    return d


def set_deps(**kwargs: Any) -> Deps:
    """Replace/override deps (tests). Unknown keys -> TypeError (loud)."""
    global _deps
    d = Deps(**kwargs)
    _deps = d
    return d


def get_deps() -> Deps:
    """Effective deps — defaults filled lazily (safe at import time)."""
    global _deps
    if _deps is None:
        _deps = Deps()
    return fill_defaults(_deps)


def reset_deps() -> None:
    global _deps
    _deps = None


# ---- main-loop bridge ------------------------------------------------------
def bind_loop(loop: Optional[asyncio.AbstractEventLoop]) -> None:
    """Explicit main-loop hook (tests now; brain-core app.py later — request
    computer-use__to__brain-core__tool-integration-hooks.md)."""
    d = get_deps()
    d.main_loop = loop


def resolve_main_loop() -> Optional[asyncio.AbstractEventLoop]:
    d = _deps
    if d is not None and d.main_loop is not None and not d.main_loop.is_closed():
        return d.main_loop
    # engine._queue_loop: set when job workers start (they run on the main loop)
    try:
        from brain.jobs.engine import get_engine
        loop = getattr(get_engine(), "_queue_loop", None)
        if loop is not None and not loop.is_closed():
            return loop
    except Exception:    # noqa: BLE001 — fallback probing must never raise
        pass
    # hub._ping_task: created by hub.start() on the main loop
    try:
        from brain.ws import get_hub
        task = get_hub()._ping_task
        if task is not None:
            loop = task.get_loop()
            if not loop.is_closed():
                return loop
    except Exception:    # noqa: BLE001
        pass
    return None


def run_sync(coro, timeout: Optional[float] = None):
    """Run `coro` on the brain's main loop from a worker thread and block for
    its result. Raises (and closes the coro) when no loop can be resolved —
    never silently runs the act pipeline on the wrong loop."""
    loop = resolve_main_loop()
    if loop is None:
        coro.close()
        raise RuntimeError("brain main loop unavailable — cannot drive GUI tools")
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    if running is loop:
        coro.close()
        raise RuntimeError("run_sync called ON the main loop — use the async entrypoint")
    fut = asyncio.run_coroutine_threadsafe(coro, loop)
    return fut.result(timeout)

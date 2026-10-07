"""computer-use tools — `see_screen` and `computer_use` (INTERFACES §(b)
self-registration).

Discovery contract (brain-core's `brain.tools.discover()` pkgutil walk): a
module exposing `register()` is CALLED with the registry module when its
signature takes a positional arg (or with nothing otherwise). Our module-level
`register(_reg=None)` below satisfies both — import-time registration and the
discovery re-call are idempotent (registry dict overwrite). Spec validation is
the registry's own `validate_schema` (runs inside register(), loud on error).

- see_screen(question): PROTOCOL §7-gated screenshot -> cloud vision answer
  (brain/vision/service.py). Never writes images to disk/logs.
- computer_use(task):   observe -> reason -> act -> verify loop, UIA-first,
  step cap jobs.gui_steps_cap, no-progress detection, per-step Core Guard
  confirmations, per-job cancellation (brain/tools/computer_use/runner.py).

Sync entrypoints because loop.py dispatches local tools via asyncio.to_thread;
wiring.run_sync bridges to the brain's main loop where the act pipeline lives.
"""
from __future__ import annotations

import brain.tools as _tool_reg

from .spec import SPECS  # noqa: F401 — spec convention (see request file)

_DESCRIPTIONS = {
    "see_screen": "answer a question about the current screen "
                  "(PROTOCOL §7-gated screenshot -> vision)",
    "computer_use": "multi-step GUI task: observe (UIA-first) -> reason -> "
                    "act -> verify (step-capped, confirm-gated)",
}


def see_screen(question: str) -> str:
    """Look at the screen and answer `question` (cloud-vision gated)."""
    from . import wiring
    from brain.vision.service import see_screen as _impl

    d = wiring.get_deps()
    coro = _impl(question, gateway=d.gateway, config=d.config, gate=d.gate,
                 vision_fn=d.vision_fn, is_private=d.is_private)
    return wiring.run_sync(coro)


def computer_use(task: str) -> str:
    """Drive the GUI to complete `task` (observe->reason->act->verify)."""
    from . import wiring
    from .runner import run_task

    return wiring.run_sync(run_task(task, wiring.get_deps()))


def register(_reg=None) -> None:
    """Discovery hook (INTERFACES §b): brain-core's walker calls this with the
    registry module. Also callable with no args (import-time path below)."""
    reg = _reg if _reg is not None and hasattr(_reg, "register") else _tool_reg
    reg.register("see_screen", see_screen,
                 risky=False, needs_lock=False, category="local",
                 description=_DESCRIPTIONS["see_screen"],
                 schema=SPECS["see_screen"])
    reg.register("computer_use", computer_use,
                 risky=True, needs_lock=True, category="local",
                 description=_DESCRIPTIONS["computer_use"],
                 schema=SPECS["computer_use"])


# import-time registration (direct imports, tests, discovery's first walk)
register()

__all__ = ["SPECS", "see_screen", "computer_use", "register"]

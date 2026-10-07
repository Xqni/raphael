"""computer-use tools — `see_screen` and `computer_use` (INTERFACES §(b)
self-registration: importing this package registers the tools; brain-core's
auto-discovery walks brain.tools.* and never edits a central registry).

- see_screen(question): PROTOCOL §7-gated screenshot -> cloud vision answer
  (brain/vision/service.py). Never writes images to disk/logs.
- computer_use(task):   observe -> reason -> act -> verify loop, UIA-first,
  step cap jobs.gui_steps_cap, no-progress detection, per-step Core Guard
  confirmations, per-job cancellation (brain/tools/computer_use/runner.py).

Sync entrypoints because loop.py dispatches local tools via asyncio.to_thread;
wiring.run_sync bridges to the brain's main loop where the act pipeline lives.
"""
from __future__ import annotations

from typing import Any, Dict

from brain.tools import register

from .spec import SPECS  # noqa: F401 — spec convention (see request file)


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


register("see_screen", see_screen,
         risky=False, needs_lock=False, category="local",
         description="answer a question about the current screen (gated screenshot -> vision)")

register("computer_use", computer_use,
         risky=True, needs_lock=True, category="local",
         description="multi-step GUI task: observe (UIA-first) -> reason -> act -> verify")

__all__ = ["SPECS", "see_screen", "computer_use"]

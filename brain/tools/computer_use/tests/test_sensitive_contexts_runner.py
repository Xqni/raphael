"""Wave 5H item 2 — runner-side sensitive-context refusals (computer_use
loop): focused password field + sensitive foreground, both refused BEFORE
the UIA probe / pixels / any model call."""
import asyncio

from brain.tools.computer_use.gateway import ActError
from brain.tools.computer_use.runner import PASSWORD_FOCUS_REASON, run_task
from brain.vision.gate import PASSWORD_FOCUS_REASON as GATE_REASON

try:
    from .harness import DEFAULT_TREE, ScriptedChat, ScriptedGateway, make_deps
except ImportError:  # bare-module collection (no tests/__init__.py — e16ca0f)
    from harness import (DEFAULT_TREE, ScriptedChat, ScriptedGateway,
                         make_deps)

assert PASSWORD_FOCUS_REASON == GATE_REASON  # single source in gate.py


def run(coro):
    return asyncio.run(coro)


def test_password_focus_from_fg_probe_refuses_before_uia():
    gw = ScriptedGateway(foreground="Notepad - Login", trees=[DEFAULT_TREE],
                         fg_password_focus=True)
    chat = ScriptedChat([])
    d = make_deps(gateway=gw, chat=chat)
    out = run(run_task("log in", d))
    assert out == GATE_REASON
    assert gw.uia_calls == 0 and gw.screenshot_calls == 0
    assert chat.calls == [] and gw.acts == []


def test_password_focus_from_tree_refuses_before_accepting_observation():
    class TreeSetsFlag(ScriptedGateway):
        async def uia_tree(self, **kw):
            self.uia_calls += 1
            self.password_focus = True          # tree saw focused IsPassword
            return DEFAULT_TREE

    gw = TreeSetsFlag(foreground="Notepad - Login")
    chat = ScriptedChat([])
    d = make_deps(gateway=gw, chat=chat)
    out = run(run_task("log in", d))
    assert out == GATE_REASON
    assert gw.screenshot_calls == 0
    assert chat.calls == [] and gw.acts == []


def test_uia_crash_cannot_linger_a_password_flag():
    """fg probe resets the flag each cycle: stale True never leaks into the
    next step's decision (no false refusal loop)."""

    class Crashy(ScriptedGateway):
        async def uia_tree(self, **kw):
            self.uia_calls += 1
            raise ActError("E_TIMEOUT", "gone")

    gw = Crashy(foreground="Notepad")
    gw.password_focus = True                    # stale from a prior probe
    chat = ScriptedChat([{"text": '{"final": "done"}'}])
    d = make_deps(gateway=gw, chat=chat, vision=lambda *a, **k: {
        "text": "a screen"})
    out = run(run_task("look", d))
    # fg probe reset the flag -> observation proceeds (vision fallback)
    assert out == "done"


def test_sensitive_browser_fg_refuses_before_uia():
    gw = ScriptedGateway(foreground="My Bank — Accounts | chrome.exe",
                         trees=[DEFAULT_TREE])
    chat = ScriptedChat([])
    d = make_deps(gateway=gw, chat=chat)
    out = run(run_task("check my balance", d))
    assert "sensitive context" in out and "bank" in out
    assert gw.uia_calls == 0 and gw.screenshot_calls == 0
    assert chat.calls == []

"""Wave 5H item 1 — the egress tripwire extended to the computer_use loop
(blocklist composite scenario: no capture, no model reach, no disk, no log).
Shared helpers come from the vision-side tripwire (single source of truth)."""
import asyncio

from brain.tools.computer_use.runner import run_task
from brain.vision.tests.test_egress_tripwire import (GW, MARKER, VisionSpy,
                                                     disk_guard)

try:
    from .harness import ScriptedChat, make_deps
except ImportError:  # bare-module collection (no tests/__init__.py)
    from harness import ScriptedChat, make_deps


def test_tripwire_runner_blocklist_refuses_everything(capsys):
    spy = VisionSpy()
    gw = GW("KeePass.exe | KeePass")            # composite identity, blocked
    chat = ScriptedChat([])                     # model must never be reached
    d = make_deps(gateway=gw, chat=chat, vision=spy)
    with disk_guard():
        out = asyncio.run(run_task("look at the screen", d))
    assert "KeePass" in out and "won't send" in out
    assert gw.screenshot_calls == 0
    assert chat.calls == []                     # no prompt ever left the box
    assert spy.calls == []                      # SEND sink silent
    console = capsys.readouterr()
    assert MARKER.decode() not in console.out + console.err + out

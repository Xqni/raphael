"""Sync tool entrypoints as loop.py actually calls them: asyncio.to_thread
-> wiring.run_sync -> main loop (mocked seams only — AGENT_RULES §5)."""
import asyncio

import brain.tools.computer_use as cu
from brain.tools.computer_use import wiring

try:
    from .harness import (CHANGED_TREE, DEFAULT_TREE, ScriptedChat,
                          ScriptedGateway, final_reply, action_reply)
except ImportError:  # bare-module collection (no tests/__init__.py)
    from harness import (CHANGED_TREE, DEFAULT_TREE, ScriptedChat,
                          ScriptedGateway, final_reply, action_reply)
from brain.vision.config import VisionConfig
from brain.vision.image import make_jpeg


def test_see_screen_entry_bridge_to_main_loop():
    gw = ScriptedGateway(foreground="Notepad - untitled")

    def fake_vision(image, question, purpose="vision"):
        assert isinstance(image, (bytes, bytearray))
        return {"text": "A blank Notepad window.", "provider": "mock"}

    async def main():
        wiring.set_deps(gateway=gw, vision_fn=fake_vision,
                        is_private=lambda: False)
        wiring.bind_loop(asyncio.get_running_loop())
        return await asyncio.to_thread(cu.see_screen, "what app is this?")

    out = asyncio.run(main())
    assert out == "A blank Notepad window."
    assert gw.screenshot_calls == 1


def test_computer_use_entry_bridge_to_main_loop():
    gw = ScriptedGateway(trees=[DEFAULT_TREE, CHANGED_TREE])
    chat = ScriptedChat([action_reply("input", {"keys": "ctrl+s"}),
                         final_reply("Document saved.")])

    async def main():
        cfg = VisionConfig(gui_steps_cap=10)
        wiring.set_deps(gateway=gw, chat_fn=chat, is_private=lambda: False,
                        config=cfg)
        wiring.bind_loop(asyncio.get_running_loop())
        return await asyncio.to_thread(cu.computer_use, "save the document")

    out = asyncio.run(main())
    assert out == "Document saved."
    gw.assert_all_allowed()
    assert gw.action_names() == ["input"]


def test_private_mode_short_circuit_at_entry():
    class ExplodingGateway(ScriptedGateway):
        async def foreground_window(self):
            raise AssertionError("no screen access in private mode")

    gw = ExplodingGateway()

    async def main():
        wiring.set_deps(gateway=gw, is_private=lambda: True)
        wiring.bind_loop(asyncio.get_running_loop())
        return await asyncio.to_thread(cu.see_screen, "what is this?")

    out = asyncio.run(main())
    assert "Private mode" in out
    assert gw.foreground_calls == 0 and gw.screenshot_calls == 0


def test_gate_blocks_at_entry_without_model_call():
    gw = ScriptedGateway(foreground="Bitwarden - Vault")

    def exploding_vision(*a, **k):
        raise AssertionError("vision must not run for a blocked window")

    async def main():
        wiring.set_deps(gateway=gw, vision_fn=exploding_vision,
                        is_private=lambda: False)
        wiring.bind_loop(asyncio.get_running_loop())
        return await asyncio.to_thread(cu.see_screen, "what is this?")

    out = asyncio.run(main())
    assert "Bitwarden" in out
    assert gw.screenshot_calls == 0

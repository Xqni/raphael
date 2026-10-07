"""Wave 4 observation hardening — loop-side: UIA crash recovery, blocklist
bypass via the composite identity, fg-probe matrix at runner level, and
redaction re-verify for UIA text + action feedback (everything screen-derived
is redacted before any cloud chat). Mock only; live stack untouched."""
import asyncio

from brain.tools.computer_use.gateway import ActError
from brain.tools.computer_use.runner import run_task
from brain.vision.config import VisionConfig

from .harness import (CHANGED_TREE, DEFAULT_TREE, ScriptedChat,
                      ScriptedGateway, final_reply, make_deps)

SECRET_TREE = (
    'window KeePassX\n'
    '  edit "user me@example.com"\n'
    '  text "card 4111 1111 1111 1111"\n'
    '  text "call +1 416 555 0123"\n'
)


def run(coro):
    return asyncio.run(coro)


class UiaCrash(ScriptedGateway):
    async def uia_tree(self, **kw):
        self.uia_calls += 1
        raise ActError("E_TIMEOUT", "element not found: {}")


# ---- UIA crash recovery ----------------------------------------------------
def test_uia_crash_recovers_via_gated_vision():
    gw = UiaCrash(foreground="Chrome - Docs")

    def fake_vision(image, question, purpose="vision"):
        assert isinstance(image, (bytes, bytearray))
        return {"text": "A browser showing a doc.", "provider": "mock"}

    chat = ScriptedChat([final_reply("You are in a browser.")])
    d = make_deps(gateway=gw, chat=chat, vision=fake_vision)
    out = run(run_task("what am i looking at", d))
    assert out == "You are in a browser."
    assert gw.screenshot_calls == 1           # crashed UIA -> gated pixels
    gw.assert_all_allowed()


def test_uia_crash_with_debug_capture_refuses_before_pixels():
    gw = UiaCrash(foreground="Chrome - Docs")
    cfg = VisionConfig(debug_capture=True, blocklist_apps=(), redact=())
    chat = ScriptedChat([])                   # never reached
    d = make_deps(gateway=gw, chat=chat,
                  vision=lambda *a, **k: {"text": "never"},
                  config=cfg)
    out = run(run_task("look", d))
    assert "stay on this machine" in out
    assert gw.screenshot_calls == 0


def test_uia_crash_and_body_gone_reports_unreachable():
    class AlsoGone(UiaCrash):
        async def screenshot(self, max_px, quality):
            self.screenshot_calls += 1
            raise ActError("E_INTERNAL", "no body session connected")

    gw = AlsoGone(foreground="Chrome - Docs")
    chat = ScriptedChat([])
    d = make_deps(gateway=gw, chat=chat,
                  vision=lambda *a, **k: {"text": "never"})
    out = run(run_task("look", d))
    assert "can't reach the Body" in out
    assert "no body session connected" in out
    assert chat.calls == []


# ---- blocklist bypass attempts at the loop seam ---------------------------
def test_blocklist_matches_composite_identity():
    for ident in ("Enter Master Key | KeePass.exe", "KeePass.exe",
                  "  keepass  "):
        gw = ScriptedGateway(foreground=ident, trees=[DEFAULT_TREE])
        chat = ScriptedChat([])
        d = make_deps(gateway=gw, chat=chat)
        out = run(run_task("do the thing", d))
        assert "KeePass" in ident or "keepass" in ident
        assert "sensitive window" in out, (ident, out)
        assert gw.uia_calls == 0 and gw.acts == []
        assert chat.calls == []               # screen text never reaches chat


def test_terminal_composite_still_runs():
    gw = ScriptedGateway(foreground="Ubuntu-26.04 | WindowsTerminal.exe",
                         trees=[DEFAULT_TREE])
    chat = ScriptedChat([final_reply("A terminal window is in front.")])
    d = make_deps(gateway=gw, chat=chat)
    out = run(run_task("what is on screen", d))
    assert out == "A terminal window is in front."
    assert gw.foreground_calls == 1           # Rule 15: one probe


# ---- foreground-probe matrix at runner level ------------------------------
def test_runner_probe_matrix():
    cases = [
        (ActError("E_ACT_TIMEOUT", "E_ACT_TIMEOUT"), "E_ACT_TIMEOUT"),
        (ActError("E_INTERNAL", "no body session connected"),
         "no body session connected"),
        (RuntimeError("boom"), "RuntimeError"),
        (None, "can't verify which window"),   # vanished window -> seam None
    ]
    for exc, needle in cases:
        gw = ScriptedGateway(foreground=exc if exc is not None else None,
                             trees=[DEFAULT_TREE])
        chat = ScriptedChat([])
        d = make_deps(gateway=gw, chat=chat)
        out = run(run_task("look", d))
        assert needle in out, (needle, out)
        assert gw.uia_calls == 0 and gw.screenshot_calls == 0
        assert chat.calls == []


# ---- redaction re-verify ---------------------------------------------------
def test_uia_tree_is_redacted_before_chat():
    gw = ScriptedGateway(foreground="Notepad", trees=[SECRET_TREE])
    chat = ScriptedChat([final_reply("Done.")])
    d = make_deps(gateway=gw, chat=chat)
    run(run_task("read the entries", d))
    obs = [m for m in chat.calls[0] if m["role"] == "user"][-1]["content"]
    for leak in ("me@example.com", "4111", "416 555"):
        assert leak not in obs, leak
    assert obs.count("[REDACTED:") >= 3
    assert "KeePassX" in obs                  # window content itself is kept


def test_action_feedback_is_redacted_before_chat():
    class ClipboardRead(ScriptedGateway):
        async def run_action(self, name, args, *, lock=False):
            self.acts.append({"name": name, "args": dict(args), "lock": lock})
            return {"text": "mail me@example.com token: abc123secret456"}

    gw = ClipboardRead(trees=[DEFAULT_TREE])
    chat = ScriptedChat([{"text": '{"action": {"name": "clipboard", '
                                  '"args": {"op": "read"}}}'},
                         final_reply("Read it.")])
    d = make_deps(gateway=gw, chat=chat)
    run(run_task("read the clipboard", d))
    fb = [m for m in chat.calls[1] if m["role"] == "user"
          and "<action_result>" in m["content"]]
    assert fb, "action feedback block missing from the 2nd model call"
    feedback = fb[0]["content"]
    assert "me@example.com" not in feedback
    assert "abc123secret456" not in feedback   # token: pattern masked
    assert "[REDACTED:" in feedback

"""Recorded-scenario harness: scripted Body gateway + scripted chat/vision.

These doubles record every interaction so tests can assert exactly what was
observed, dispatched, and sent to the model — no network, no real UI, no
sleeps (AGENT_RULES §5: prefer mocks; real runs are the integrator's).
"""
from __future__ import annotations

import copy
from typing import Any, Callable, Dict, List, Optional

from brain.tools.computer_use.runner import ALLOWED_ACTIONS
from brain.vision.image import make_jpeg

DEFAULT_TREE = (
    "window Notepad\n"
    "  editor \"untitled\"\n"
    "    button \"Save\"\n"
    "    menu \"File Edit View\""
)
CHANGED_TREE = (
    "window Notepad\n"
    "  editor \"saved document\"\n"
    "    status \"Document saved\"\n"
    "    button \"Save\""
)


class ScriptedGateway:
    """Fake Body: records acts, serves scripted foreground/UIA/screenshot.

    trees: observation script — one entry per uia_tree() call (last repeats).
           Use [''] to force the gated-vision fallback.
    on_act: optional hook(name, args, lock) — mutate state / flags.
    advance_on_act: when True, `trees` is indexed by act count (screen changes
           only after an action); otherwise by observation count.
    """

    def __init__(self, foreground: Any = "Notepad - untitled",
                 trees: Optional[List[str]] = None,
                 image: Optional[bytes] = None,
                 on_act: Optional[Callable[..., None]] = None,
                 advance_on_act: bool = True,
                 act_error: Optional[Exception] = None,
                 fg_password_focus: bool = False):
        self.foreground = foreground
        self.trees = list(trees) if trees is not None else [DEFAULT_TREE]
        self.image = image if image is not None else make_jpeg(1280, 720)
        self.on_act = on_act
        self.advance_on_act = advance_on_act
        self.act_error = act_error
        # Wave 5H: emulates BodyGateway.password_focus — the probe RESETS
        # then refreshes the flag (fresh per probe, stale True never lingers).
        self.fg_password_focus = fg_password_focus
        self.password_focus = False
        self.acts: List[Dict[str, Any]] = []
        self.screenshot_calls = 0
        self.foreground_calls = 0
        self.uia_calls = 0
        self._obs = 0

    def _tree_index(self) -> int:
        idx = len(self.acts) if self.advance_on_act else self._obs
        return min(idx, len(self.trees) - 1)

    async def foreground_window(self) -> Any:
        self.foreground_calls += 1
        self.password_focus = bool(self.fg_password_focus)
        if isinstance(self.foreground, Exception):
            raise self.foreground
        return self.foreground

    async def uia_tree(self, **kw: Any) -> str:
        self.uia_calls += 1
        idx = self._tree_index()
        if self.advance_on_act:
            pass                              # index = acts (stable per state)
        else:
            self._obs += 1
        return self.trees[idx]

    async def screenshot(self, max_px: int, quality: int) -> bytes:
        self.screenshot_calls += 1
        return self.image

    async def run_action(self, name: str, args: Dict[str, Any], *,
                         lock: bool = False) -> Any:
        if self.act_error is not None:
            self.acts.append({"name": name, "args": dict(args), "lock": lock})
            raise self.act_error
        self.acts.append({"name": name, "args": dict(args), "lock": lock})
        if self.on_act is not None:
            self.on_act(name, dict(args), lock)
        return {"ok": True}

    # -- assertions ----------------------------------------------------------
    def action_names(self) -> List[str]:
        return [a["name"] for a in self.acts]

    def assert_all_allowed(self) -> None:
        for a in self.acts:
            assert a["name"] in ALLOWED_ACTIONS, f"non-allow-listed act: {a}"


class ScriptedChat:
    """Fake router.chat: returns queued replies, records every call."""

    def __init__(self, replies: List[Any]):
        self.replies = list(replies)
        self.calls: List[List[Dict[str, str]]] = []

    def __call__(self, messages, tools=None, purpose="tool", **kw):
        self.calls.append(copy.deepcopy(messages))
        if not self.replies:
            raise AssertionError("chat script exhausted (loop ran too long)")
        return self.replies.pop(0)


def action_reply(name: str, args: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    import json
    return {"text": json.dumps({"action": {"name": name, "args": args or {}}})}


def final_reply(text: str) -> Dict[str, str]:
    import json
    return {"text": json.dumps({"final": text})}


def make_deps(gateway=None, chat=None, vision=None, *, private=False,
              config=None, confirm=None, cancelled=None, emit=None,
              rowid=None, chat_timeout_s=30.0):
    """Build a fully-seeded Deps for direct run_task() calls (hermetic:
    no global wiring, no real config load when `config` is given)."""
    from brain.tools.computer_use.wiring import Deps, fill_defaults
    from brain.vision.config import VisionConfig
    from brain.vision.gate import CloudVisionGate

    cfg = config if config is not None else VisionConfig(
        profile="cloud_temp", provider="cloud", max_px=1280, quality=70,
        blocklist_apps=("1Password", "KeePass", "Bitwarden", "Banking"),
        redact=("api_key", "token", "password", "card", "email", "phone"),
        gui_steps_cap=25)
    d = Deps(
        config=cfg,
        gate=CloudVisionGate(cfg),
        gateway=gateway if gateway is not None else ScriptedGateway(),
        chat_fn=chat if chat is not None else ScriptedChat([final_reply("ok")]),
        vision_fn=vision,
        is_private=lambda: private,
        confirm_fn=confirm,
        emit_fn=emit,
        cancelled_fn=cancelled,
        chat_timeout_s=chat_timeout_s,
        job_rowid=rowid,
    )
    return fill_defaults(d)

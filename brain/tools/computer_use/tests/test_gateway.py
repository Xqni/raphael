"""BodyGateway act-pipeline contract (PROTOCOL §7 as amended 2026-10-06):
exact frames on the wire, result parsing, fail-closed foreground handling,
UIA-tree -> text rendering. Fake hub/engine only — no sockets, no body
(AGENT_RULES §5)."""
import asyncio

import pytest

from brain.tools.computer_use.gateway import ActError, BodyGateway, render_tree


class FakeHub:
    def __init__(self, has_body=True):
        self.has_body = has_body
        self.frames = []

    def get_body_session(self):
        return object() if self.has_body else None

    def broadcast(self, frame, roles=None, exclude_sid=None):
        self.frames.append((frame, roles))


class FakeEngine:
    """Immediately-resolved act pipeline: records refs, returns scripted
    results in order (dict with ok/result/error — the ws deliver shape)."""

    def __init__(self, *results):
        self.results = list(results)
        self.refs = []

    def expect_act(self, ref):
        self.refs.append(ref)
        return object()          # unused by the fake

    async def await_act_res(self, fut, ref, timeout=None):
        if not self.results:
            return {"ok": False, "error": "E_ACT_TIMEOUT"}
        return self.results.pop(0)


def make(*results, has_body=True):
    hub, eng = FakeHub(has_body), FakeEngine(*results)
    return BodyGateway(hub=hub, engine=eng), hub, eng


def run(coro):
    return asyncio.run(coro)


# ---- foreground_info (blocklist pre-egress) --------------------------------
def test_foreground_window_uses_foreground_info_action():
    gw, hub, eng = make({"ok": True, "result": {
        "window": {"title": "1Password - Browser", "process": "1Password",
                   "pid": 123, "foreground": True}}})
    ident = run(gw.foreground_window())
    # composite identity: blocklist must be able to match title AND process
    assert ident == "1Password - Browser | 1Password"
    frame, roles = hub.frames[0]
    assert frame["action"] == "foreground_info"
    assert frame["args"] == {}
    assert frame["lock"] is False           # read-only inspection (§7)
    assert roles == {"body"}
    assert eng.refs == [frame["job"]]       # journaled under one coherent ref


def test_foreground_identity_matrix():
    # vanished window / no fg window -> None (gate fails closed)
    gw, _, _ = make({"ok": True, "result": {"window": None}})
    assert run(gw.foreground_window()) is None
    # hidden-ish: empty title but resolvable process -> process alone
    gw2, _, _ = make({"ok": True, "result": {
        "window": {"title": "", "process": "KeePass.exe"}}})
    assert run(gw2.foreground_window()) == "KeePass.exe"
    # real window with ZERO identity -> None (cannot be verified -> closed)
    gw3, _, _ = make({"ok": True, "result": {
        "window": {"title": "", "process": None}}})
    assert run(gw3.foreground_window()) is None
    # malformed shape -> None
    gw4, _, _ = make({"ok": True, "result": {"weird": 1}})
    assert run(gw4.foreground_window()) is None
    # whitespace-normalized composite
    gw5, _, _ = make({"ok": True, "result": {
        "window": {"title": "  Ubuntu-26.04 ", "process": "WindowsTerminal.exe"}}})
    assert run(gw5.foreground_window()) == "Ubuntu-26.04 | WindowsTerminal.exe"


def test_foreground_window_none_when_no_window_or_unsupported():
    gw, _, _ = make({"ok": True, "result": {"window": None}})
    assert run(gw.foreground_window()) is None      # {'window': None}
    gw2, _, _ = make({"ok": True, "result": {"weird": 1}})
    assert run(gw2.foreground_window()) is None     # unexpected shape -> closed
    gw3, _, _ = make({"ok": False, "error": "E_UNSUPPORTED"})
    with pytest.raises(ActError):
        run(gw3.foreground_window())                # op missing -> loud, caller closes


def test_no_body_session_fails_loudly():
    gw, _, _ = make(has_body=False)
    with pytest.raises(ActError) as ei:
        run(gw.foreground_window())
    assert ei.value.code == "E_INTERNAL"


# ---- uia tree (UIA-first observe) ------------------------------------------
TREE = {
    "name": "Notepad", "control_type": "Window", "automation_id": "",
    "class_name": "Notepad",
    "children": [
        {"name": "File", "control_type": "MenuBar", "automation_id": "",
         "children": []},
        {"name": "untitled", "control_type": "Edit", "automation_id": "editor",
         "children": [
             {"name": "Save", "control_type": "Button",
              "automation_id": "", "children": []},
         ]},
    ],
    "truncated": False,
}


def test_uia_tree_sends_shipped_contract_and_renders_text():
    gw, hub, eng = make({"ok": True, "result": TREE})
    text = run(gw.uia_tree())
    frame, roles = hub.frames[0]
    assert frame["action"] == "uia"
    assert frame["args"]["op"] == "tree"
    assert frame["args"]["element"] == {"control_type": "window"}  # fg = first candidate
    assert frame["args"]["args"]["depth"] == 2                     # clamped 1..3
    assert 0.5 <= frame["args"]["args"]["timeout_s"] <= 15
    assert frame["lock"] is False
    # rendered as TEXT (lane rule): role "name" lines, indented
    assert 'Window "Notepad"' in text
    assert '  MenuBar "File"' in text
    assert '  Edit "untitled" [editor]' in text
    assert '    Button "Save"' in text


def test_uia_tree_result_garbage_renders_empty():
    gw, _, _ = make({"ok": True, "result": None})
    assert run(gw.uia_tree()) == ""


def test_render_tree_bounded_by_max_chars():
    out = render_tree(TREE, max_chars=30)
    assert len(out) <= 32
    assert out.endswith("…")


def test_render_tree_marks_body_truncation():
    node = dict(TREE, truncated=True)
    out = render_tree(node, max_chars=4000)
    assert out.endswith("…")


def test_uia_tree_depth_clamped():
    gw, hub, _ = make({"ok": True, "result": TREE})
    run(gw.uia_tree(depth=99))
    assert hub.frames[0][0]["args"]["args"]["depth"] == 3
    gw2, hub2, _ = make({"ok": True, "result": TREE})
    run(gw2.uia_tree(depth=-5))
    assert hub2.frames[0][0]["args"]["args"]["depth"] == 1


# ---- screenshot ------------------------------------------------------------
def test_screenshot_decodes_b64_and_passes_config():
    import base64
    payload = base64.b64encode(b"\xff\xd8fakejpeg").decode()
    gw, hub, _ = make({"ok": True, "result": {"b64": payload, "bytes": 10}})
    data = run(gw.screenshot(1280, 70))
    assert data == b"\xff\xd8fakejpeg"
    frame = hub.frames[0][0]
    assert frame["action"] == "screenshot"
    assert frame["args"] == {"max_px": 1280, "quality": 70}
    assert frame["lock"] is False


def test_screenshot_missing_or_empty_payload_is_structured_error():
    gw, _, _ = make({"ok": True, "result": {"bytes": 0}})
    with pytest.raises(ActError) as ei:
        run(gw.screenshot(1280, 70))
    assert ei.value.code == "E_INTERNAL"
    gw2, _, _ = make({"ok": True, "result": {"b64": ""}})
    with pytest.raises(ActError):
        run(gw2.screenshot(1280, 70))


def test_act_error_maps_body_error_codes():
    gw, _, _ = make({"ok": False, "error": "E_LOCK_BUSY"})
    with pytest.raises(ActError) as ei:
        run(gw.run_action("input", {"keys": "a"}, lock=True))
    assert ei.value.code == "E_LOCK_BUSY"
    # non-E_ detail still yields a PROTOCOL code, keeps detail
    gw2, _, _ = make({"ok": False, "error": "element not found: {}"})
    with pytest.raises(ActError) as ei2:
        run(gw2.run_action("uia", {"op": "tree"}, lock=False))
    assert ei2.value.code == "E_INTERNAL"
    assert "element not found" in ei2.value.detail


def test_run_action_lock_flag_follows_caller():
    gw, hub, _ = make({"ok": True, "result": None})
    run(gw.run_action("input", {"keys": "ctrl+s"}, lock=True))
    assert hub.frames[0][0]["lock"] is True

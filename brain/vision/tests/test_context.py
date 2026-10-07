"""Wave 5: Analysis-mode context gathering — screen + foreground + window
history, redaction discipline on every payload, blocklist filtering of window
titles/history, Private-Mode zero-probe, probe-failure honesty."""
import asyncio

import pytest

from brain.vision import context as ctx
from brain.vision.config import VisionConfig
from brain.vision.gate import CloudVisionGate
from brain.vision.image import make_jpeg

IMG = make_jpeg(1280, 720)


def cfg(**kw):
    base = dict(profile="cloud_temp", provider="cloud", max_px=1280, quality=70,
                blocklist_apps=("1Password", "KeePass", "Bitwarden", "Banking"),
                redact=("api_key", "token", "password", "card", "email", "phone"))
    base.update(kw)
    return VisionConfig(**base)


class FakeGateway:
    def __init__(self, fg="Ubuntu-26.04 | WindowsTerminal.exe",
                 windows=None, fg_exc=None, win_exc=None, shot_exc=None):
        self.fg, self.windows = fg, windows
        self.fg_exc, self.win_exc, self.shot_exc = fg_exc, win_exc, shot_exc
        self.probes = []

    async def foreground_window(self):
        self.probes.append("fg")
        if self.fg_exc:
            raise self.fg_exc
        return self.fg

    async def list_windows(self):
        self.probes.append("wins")
        if self.win_exc:
            raise self.win_exc
        return {"count": len(self.windows or []),
                "windows": self.windows or []}

    async def screenshot(self, max_px, quality):
        self.probes.append("shot")
        if self.shot_exc:
            raise self.shot_exc
        return IMG


WINDOWS = [
    {"title": "Report.docx", "process": "WINWORD.EXE", "foreground": True},
    {"title": "Master Key", "process": "KeePass.exe", "foreground": False},
    {"title": "", "process": "KeePass.exe", "foreground": False},
    {"title": "me@example.com - Mail", "process": "Outlook", "foreground": False},
]


def gather(gw, **kw):
    c = cfg(**kw.pop("cfg", {}))
    is_private = kw.pop("is_private", lambda: False)
    vision_fn = kw.pop("vision_fn", lambda *a, **k: {
        "text": "A terminal running WSL with a build log."})
    return asyncio.run(ctx.gather_context(
        gateway=gw, gate=CloudVisionGate(c), config=c, vision_fn=vision_fn,
        is_private=is_private, **kw))


@pytest.fixture(autouse=True)
def _clean_history():
    ctx.reset_history()
    yield
    ctx.reset_history()


# ---- happy path: all sections, redacted, bounded ---------------------------
def test_full_context_block():
    out = gather(FakeGateway(windows=WINDOWS), question="deep dive please")
    assert "Foreground: Ubuntu-26.04 | WindowsTerminal.exe" in out
    assert "Report.docx | WINWORD.EXE" in out
    assert "[foreground]" in out
    assert "Recent foreground window history" in out
    assert "Screen: A terminal running WSL" in out
    assert len(out) <= 3001


def test_blocklist_titles_and_history_filtered_from_payload():
    out = gather(FakeGateway(fg="Notepad", windows=WINDOWS))
    assert "KeePass" not in out                       # no sensitive titles
    # sensitive fg itself is withheld but announced generically
    out2 = gather(FakeGateway(fg="Master Key | KeePass.exe", windows=WINDOWS))
    assert "KeePass" not in out2
    assert "sensitive app is in front" in out2
    # history entries too: seed a blocked identity, then gather
    ctx.record_foreground("KeePass.exe | KeePass")
    out3 = gather(FakeGateway(fg="Notepad", windows=[]))
    assert "KeePass" not in out3


def test_redaction_applies_to_all_sections():
    ws = [{"title": "mail me@example.com", "process": "thunderbird",
           "foreground": True}]
    out = gather(FakeGateway(fg="Notepad", windows=ws),
                 vision_fn=lambda *a, **k: {
                     "text": "card 4111 1111 1111 1111 password: hunter2"})
    assert "me@example.com" not in out
    assert "4111" not in out and "hunter2" not in out
    assert out.count("[REDACTED:") >= 3


# ---- Private Mode: zero probes ---------------------------------------------
def test_private_mode_probes_nothing():
    class Exploding(FakeGateway):
        async def foreground_window(self):
            raise AssertionError("no probe in private mode")

        async def list_windows(self):
            raise AssertionError("no probe in private mode")

        async def screenshot(self, *a, **k):
            raise AssertionError("no probe in private mode")

    out = gather(Exploding(), is_private=lambda: True)
    assert "private mode" in out


# ---- probe failures are availability, honestly ------------------------------
def test_fg_probe_failure_aborts_with_unreachable():
    class ProbeErr(Exception):
        def __init__(self):
            super().__init__("gone")
            self.code = "E_INTERNAL"
            self.detail = "no body session connected"

    gw = FakeGateway(fg_exc=ProbeErr())
    out = gather(gw)
    assert "Context unavailable" in out
    assert "no body session connected" in out
    assert gw.probes == ["fg"]                         # nothing after fg fails


def test_windows_probe_failure_degrades_gracefully():
    gw = FakeGateway(fg="Notepad", win_exc=RuntimeError("boom"))
    out = gather(gw, include_screen=False)
    assert "Windows: unavailable (RuntimeError)" in out
    assert "Foreground: Notepad" in out                # other sections intact


def test_screen_disabled_makes_no_screenshot_probe():
    gw = FakeGateway(fg="Notepad", windows=[])
    out = gather(gw, include_screen=False)
    assert "Screen:" not in out
    assert "shot" not in gw.probes


def test_screen_gated_paths():
    # blocklisted fg -> withheld notes, no screenshot, name never leaks
    gw = FakeGateway(fg="KeePass.exe", windows=[])
    out = gather(gw)
    assert "sensitive app is in front" in out
    assert "KeePass" not in out                     # name never reaches models
    assert "shot" not in gw.probes
    # debug_capture -> refusal note, no screenshot
    gw2 = FakeGateway(fg="Notepad", windows=[])
    out2 = gather(gw2, cfg={"debug_capture": True})
    assert "stay on this machine" in out2
    assert "shot" not in gw2.probes
    # oversized image -> refused, vision never called
    gw3 = FakeGateway(fg="Notepad", windows=[])

    def no_vision(*a, **k):
        raise AssertionError("vision must not run on refused image")
    out3 = gather(gw3, vision_fn=no_vision,
                  cfg={"max_px": 100})                 # IMG is 1280 -> too big
    assert "larger than the size limit" in out3


# ---- history ring behavior --------------------------------------------------
def test_history_records_dedups_and_caps():
    ctx.record_foreground("A | a.exe")
    ctx.record_foreground("A | a.exe")                 # consecutive dup collapses
    ctx.record_foreground("B | b.exe")
    ctx.record_foreground(None)                        # ignored
    hist = ctx.recent_history()
    assert [h[1] for h in hist] == ["A | a.exe", "B | b.exe"]
    for i in range(50):
        ctx.record_foreground("W%d" % i)
    assert len(ctx.recent_history()) == 12             # emit cap
    assert len(ctx.recent_history(100)) <= 32          # ring cap


def test_gateway_probe_feeds_history(monkeypatch):
    """The production hook: BodyGateway.foreground_window records identity."""
    import asyncio as aio

    from brain.tools.computer_use.gateway import BodyGateway

    class Hub:
        def get_body_session(self):
            return object()

        def broadcast(self, frame, roles=None, exclude_sid=None):
            pass

    class Eng:
        def __init__(self):
            self.result = {"ok": True, "result": {
                "window": {"title": "Terminal", "process": "conhost.exe"}}}

        def expect_act(self, ref):
            return object()

        async def await_act_res(self, fut, ref, timeout=None):
            return self.result

    gw = BodyGateway(hub=Hub(), engine=Eng())
    ident = aio.run(gw.foreground_window())
    assert ident == "Terminal | conhost.exe"
    assert [h[1] for h in ctx.recent_history()] == ["Terminal | conhost.exe"]

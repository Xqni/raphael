"""AUD-05 (AUDIT-2026-10-07 P0, router half): foreground gate FAILS CLOSED.

Pre-audit: `privacy.foreground_window()` returned None for BOTH "no hook
registered" and "hook could not determine the window", and `blocklist_hit`
treated None as "no block" → cloud chat/vision egress with an UNVERIFIED
focused window (privacy.py:53-69 fail-open).

Now: unknown → REFUSE (reason `foreground_unknown`, `require_foreground`
default true), known+blocklisted → `blocked_window`, known+normal → allowed.
Deliberate exception: `transcribe()` (audio has no focused-window semantics).
"""
from __future__ import annotations

import pytest

import brain.router as router
from brain.router import RouterError
from brain.router import privacy
from brain.router.tests.conftest import make_config

IMAGE = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


@pytest.fixture(autouse=True)
def _production_path(monkeypatch):
    """These tests must exercise the LIVE (non-pytest) semantics: no hook +
    no pytest-window default = unknown = refuse (AUD-05)."""
    monkeypatch.setattr(privacy, "_pytest_session", lambda: False)


def _rt(tmp_path, srv_url="http://127.0.0.1:9", **kw):
    cfg = make_config(tmp_path, ["groq"], groq_url=srv_url, **kw)
    router.reset_router()
    return router.init_router(cfg)


@pytest.mark.asyncio
async def test_unknown_foreground_refuses_chat_with_zero_egress(
        tmp_path, make_server, keys) -> None:
    """No hook wired (today's stack) → cloud chat must NOT egress."""
    srv = make_server(free_suffix=False)
    rt = _rt(tmp_path, srv.url)
    privacy.set_foreground_check(None)            # unwired = unknown
    with pytest.raises(RouterError) as exc:
        await rt.chat([{"role": "user", "content": "hi"}])
    assert exc.value.code == "E_OFFLINE"
    assert exc.value.reason == "foreground_unknown"
    assert isinstance(exc.value.spoken, str)
    assert srv.requests == []                     # zero egress


@pytest.mark.asyncio
async def test_hook_returning_none_is_unknown_too(tmp_path, make_server, keys) -> None:
    """A registered hook that cannot determine the window also refuses."""
    srv = make_server(free_suffix=False)
    rt = _rt(tmp_path, srv.url)
    privacy.set_foreground_check(lambda: None)
    with pytest.raises(RouterError) as exc:
        await rt.chat([{"role": "user", "content": "hi"}])
    assert exc.value.reason == "foreground_unknown"
    privacy.set_foreground_check(lambda: "   ")    # blank = unknown as well
    with pytest.raises(RouterError) as exc2:
        await rt.chat([{"role": "user", "content": "hi"}])
    assert exc2.value.reason == "foreground_unknown"
    assert srv.requests == []


@pytest.mark.asyncio
async def test_unknown_foreground_refuses_vision_and_stream(
        tmp_path, make_server, keys) -> None:
    srv = make_server(free_suffix=False)
    rt = _rt(tmp_path, srv.url)
    privacy.set_foreground_check(None)
    with pytest.raises(RouterError) as exc:
        await rt.vision(IMAGE, "what is this?")
    assert exc.value.reason == "foreground_unknown"
    events = []
    with pytest.raises(RouterError) as exc2:
        async for ev in rt.chat([{"role": "user", "content": "hi"}], stream=True):
            events.append(ev)
    assert exc2.value.reason == "foreground_unknown"
    assert events == []
    assert srv.requests == []


@pytest.mark.asyncio
async def test_unknown_foreground_fails_closed_on_legacy_complete(
        tmp_path, make_server, keys) -> None:
    srv = make_server(free_suffix=False)
    rt = _rt(tmp_path, srv.url)
    privacy.set_foreground_check(None)
    res = await rt.complete("groq", "some-model", prompt="hi")
    assert res.ok is False
    assert res.error_code == "E_OFFLINE"
    assert res.reason == "foreground_unknown"
    assert srv.requests == []


@pytest.mark.asyncio
async def test_known_normal_window_allows_chat(tmp_path, make_server, keys) -> None:
    srv = make_server(free_suffix=False)
    rt = _rt(tmp_path, srv.url)
    privacy.set_foreground_check(lambda: "Normal Editor Window")   # conftest default
    out = await rt.chat([{"role": "user", "content": "hi"}])
    assert out["provider"] == "groq"
    assert len(srv.chat_requests) == 1


@pytest.mark.asyncio
async def test_known_blocklisted_still_refused(tmp_path, make_server, keys) -> None:
    srv = make_server(free_suffix=False)
    rt = _rt(tmp_path, srv.url)
    privacy.set_foreground_check(lambda: "KeePass - Password Safe")
    with pytest.raises(RouterError) as exc:
        await rt.chat([{"role": "user", "content": "hi"}])
    assert exc.value.reason == "blocked_window"
    with pytest.raises(RouterError) as exc2:
        await rt.vision(IMAGE, "q")
    assert exc2.value.reason == "blocked_window"
    assert srv.requests == []


@pytest.mark.asyncio
async def test_config_escape_hatch(tmp_path, make_server, keys) -> None:
    """require_foreground=false (documented integrator interim escape) →
    unknown no longer refuses, but known-blocklisted still does."""
    srv = make_server(free_suffix=False)
    rt = _rt(tmp_path, srv.url, require_foreground=False)
    privacy.set_foreground_check(None)
    out = await rt.chat([{"role": "user", "content": "hi"}])
    assert out["provider"] == "groq"
    privacy.set_foreground_check(lambda: "Banking - Overview")
    with pytest.raises(RouterError) as exc:
        await rt.chat([{"role": "user", "content": "hi"}])
    assert exc.value.reason == "blocked_window"


@pytest.mark.asyncio
async def test_transcribe_is_deliberately_not_window_gated(
        tmp_path, make_server, keys) -> None:
    """Audio carries no focused-window semantics → STT works unwired."""
    srv = make_server(free_suffix=False)
    rt = _rt(tmp_path, srv.url)
    privacy.set_foreground_check(None)
    out = await rt.transcribe(b"RIFF" + b"\x00" * 64)
    assert out["text"]


@pytest.mark.asyncio
async def test_broken_hook_never_crashes_and_refuses(tmp_path, make_server, keys) -> None:
    srv = make_server(free_suffix=False)
    rt = _rt(tmp_path, srv.url)

    def _boom():
        raise RuntimeError("hook exploded")

    privacy.set_foreground_check(_boom)
    with pytest.raises(RouterError) as exc:       # guarded call → unknown
        await rt.chat([{"role": "user", "content": "hi"}])
    assert exc.value.reason == "foreground_unknown"
    assert srv.requests == []


# --------------------------------------------------------------------------- #
# harness default (documented exception)
# --------------------------------------------------------------------------- #
def test_pytest_sessions_get_a_synthetic_known_window(monkeypatch) -> None:
    """Under PYTEST_CURRENT_TEST an unwired hook = known 'pytest-window'
    (harnesses can't query a real foreground); production path refuses."""
    privacy.set_foreground_check(None)
    monkeypatch.setattr(privacy, "_pytest_session", lambda: True)
    assert privacy.foreground_status() == (True, "pytest-window")
    monkeypatch.setattr(privacy, "_pytest_session", lambda: False)
    assert privacy.foreground_status() == (False, None)   # production = refuse

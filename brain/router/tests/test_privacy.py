"""Wave 2 task 4: privacy gates — redaction, Private Mode, blocklist, no logs.

These tests prove the three router-side gates (brain/router/privacy.py) fire
BEFORE anything leaves the process: no key in any body/log/usage line, no
cloud call at all in Private Mode, and vision refusal on a blocklisted
foreground window.
"""
from __future__ import annotations

import logging

import pytest

import brain.router as router
from brain.router import RouterError
from brain.router.privacy import (
    describe_image,
    redact_categories,
    redact_secrets,
    set_foreground_check,
    set_private_mode,
)
from brain.router.tests.conftest import make_config

SENTINEL = "gsk_thisKeyMustNeverLeaveTheLaptop12345"


def _msgs(text: str):
    return [{"role": "user", "content": text}]


# --------------------------------------------------------------------------- #
# Private Mode (PROTOCOL §7: disables ALL model calls)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_private_mode_blocks_every_cloud_call(tmp_path, make_server) -> None:
    import os
    os.environ["GROQ_API_KEY"] = SENTINEL
    srv = make_server(free_suffix=False)
    try:
        cfg = make_config(tmp_path, ["groq"], groq_url=srv.url)
        router.reset_router()
        router.init_router(cfg)
        set_private_mode(True)
        for op, coro in (
            ("chat", router.chat(_msgs("hi"))),
            ("vision", router.vision(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8, "q")),
            ("transcribe", router.transcribe(b"RIFF" + b"\x00" * 8)),
        ):
            with pytest.raises(RouterError) as exc:
                await coro
            assert exc.value.code == "E_OFFLINE"
            assert exc.value.reason == "private_mode"
            assert isinstance(exc.value.spoken, str)
        assert srv.requests == []                  # zero egress in Private Mode
    finally:
        os.environ.pop("GROQ_API_KEY", None)
        set_private_mode(False)


@pytest.mark.asyncio
async def test_private_mode_health_makes_no_network_calls(tmp_path, make_server) -> None:
    import os
    os.environ["GROQ_API_KEY"] = SENTINEL
    srv = make_server(free_suffix=False)
    try:
        cfg = make_config(tmp_path, ["groq"], groq_url=srv.url)
        router.reset_router()
        router.init_router(cfg)
        set_private_mode(True)
        out = await router.health()
        assert out["ok"] is False
        assert "private mode" in out["providers"]["groq"]["last_error"]
        assert srv.requests == []                  # health must not egress either
    finally:
        os.environ.pop("GROQ_API_KEY", None)
        set_private_mode(False)


# --------------------------------------------------------------------------- #
# foreground-window blocklist (PROTOCOL §7(2))
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_blocklist_always_refuses_vision(tmp_path, make_server) -> None:
    import os
    os.environ["GROQ_API_KEY"] = SENTINEL
    srv = make_server(free_suffix=False)
    try:
        cfg = make_config(tmp_path, ["groq"], groq_url=srv.url)
        router.reset_router()
        router.init_router(cfg)
        set_foreground_check(lambda: "KeePass - Password Safe")
        with pytest.raises(RouterError) as exc:
            await router.vision(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8, "what is this?")
        assert exc.value.reason == "blocked_window"
        assert exc.value.code == "E_OFFLINE"
        assert srv.requests == []
        set_foreground_check(lambda: "Normal Window")   # known + not blocklisted
        out = await router.vision(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8, "what is this?")
        assert out["provider"] == "groq"            # unblocked → cloud call runs
    finally:
        os.environ.pop("GROQ_API_KEY", None)
        set_foreground_check(None)


@pytest.mark.asyncio
async def test_blocklist_blocks_chat_only_when_configured(tmp_path, make_server) -> None:
    import os
    os.environ["GROQ_API_KEY"] = SENTINEL
    srv = make_server(free_suffix=False)
    try:
        cfg = make_config(tmp_path, ["groq"], groq_url=srv.url,
                          block_chat_on_blocklist=False)
        router.reset_router()
        router.init_router(cfg)
        set_foreground_check(lambda: "Banking - Overview")
        out = await router.chat(_msgs("hello"))    # explicitly allowed by config
        assert out["provider"] == "groq"
        set_foreground_check(lambda: "Normal Window")
        cfg2 = make_config(tmp_path, ["groq"], groq_url=srv.url,
                           block_chat_on_blocklist=True)
        router.reset_router()
        router.init_router(cfg2)
        set_foreground_check(lambda: "Banking - Overview")
        with pytest.raises(RouterError) as exc:
            await router.chat(_msgs("hello"))
        assert exc.value.reason == "blocked_window"
    finally:
        os.environ.pop("GROQ_API_KEY", None)
        set_foreground_check(None)


# --------------------------------------------------------------------------- #
# secret redaction before egress
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_key_value_never_reaches_request_body_or_logs(
        tmp_path, make_server, monkeypatch, caplog) -> None:
    import os
    os.environ["GROQ_API_KEY"] = SENTINEL
    srv = make_server(free_suffix=False)
    try:
        cfg = make_config(tmp_path, ["groq"], groq_url=srv.url)
        router.reset_router()
        router.init_router(cfg)
        with caplog.at_level(logging.DEBUG, logger="raphael.router"):
            await router.chat(_msgs(f"my key is {SENTINEL} please ignore it"))
        # Authorization header carries the key (that's the point) …
        auth = srv.chat_requests[0]["headers"].get("authorization", "")
        assert auth == f"Bearer {SENTINEL}"
        # … but no body, log line or usage record may
        for body in srv.bodies():
            assert SENTINEL.encode() not in body
        assert SENTINEL not in caplog.text
        usage = cfg.usage_log_path.read_text(encoding="utf-8")
        assert SENTINEL not in usage
        # outbound text was actually redacted before sending
        assert SENTINEL.encode() not in srv.chat_requests[0]["body"]
        assert b"[REDACTED]" in srv.chat_requests[0]["body"]
    finally:
        os.environ.pop("GROQ_API_KEY", None)


def test_redact_secrets_patterns() -> None:
    cases = [
        ("sk-abcdefghijklmnop", "[REDACTED]"),
        ("gsk_abcdefghijklmnop", "[REDACTED]"),
        ("ghp_abcdefghijklmnopqrst123456", "[REDACTED]"),
        ("Authorization: Bearer abc.def.ghi", "Authorization: Bearer [REDACTED]"),
        ("password=hunter2", "password=[REDACTED]"),
        ("api_key: ZZZZ9999", "api_key: [REDACTED]"),
    ]
    for text, expected in cases:
        assert expected in redact_secrets(text), text
    # Luhn-valid card dies, ordinary digit runs survive
    assert "[REDACTED]" in redact_secrets("card 4111 1111 1111 1111 ok")
    assert "2026" in redact_secrets("year 2026")
    # never raises on odd input
    assert redact_secrets("") == ""


def test_redact_categories_for_extracted_screen_text() -> None:
    text = "contact ada@example.com or +1 (555) 123-4567 card 4111111111111111"
    out = redact_categories(text, ["email", "phone", "card"])
    assert "ada@example.com" not in out
    assert "123-4567" not in out
    assert "4111111111111111" not in out


# --------------------------------------------------------------------------- #
# images: metadata only, never logged, never oversized
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_image_bytes_never_logged(tmp_path, make_server, caplog, keys) -> None:
    image = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 4
    srv = make_server(free_suffix=False)
    cfg = make_config(tmp_path, ["groq"], groq_url=srv.url)
    router.reset_router()
    router.init_router(cfg)
    with caplog.at_level(logging.DEBUG):
        out = await router.vision(image, "describe this")
    assert out["text"]
    assert image not in caplog.text.encode()
    assert image.hex() not in caplog.text
    import base64
    assert base64.b64encode(image).decode() not in caplog.text
    # only metadata may be described
    assert describe_image(image) == f"<image {len(image)} bytes>"
    # but the wire DID carry the image (that's the cloud_temp exception)
    import base64 as b64
    assert b64.b64encode(image) in srv.chat_requests[0]["body"]


@pytest.mark.asyncio
async def test_vision_refuses_oversized_image(tmp_path, make_server) -> None:
    srv = make_server(free_suffix=False)
    cfg = make_config(tmp_path, ["groq"], groq_url=srv.url,
                      vision_max_bytes=64)
    router.reset_router()
    router.init_router(cfg)
    with pytest.raises(RouterError) as exc:
        await router.vision(b"\x89PNG\r\n\x1a\n" + b"\x00" * 512, "q")
    assert exc.value.code == "E_BAD_MSG"
    assert exc.value.reason == "image_too_large"
    assert srv.requests == []


@pytest.mark.asyncio
async def test_vision_refused_when_profile_is_not_cloud(tmp_path, make_server) -> None:
    """profile local: vision.provider=local → cloud vision must never run."""
    srv = make_server(free_suffix=False)
    cfg = make_config(tmp_path, ["groq"], groq_url=srv.url,
                      vision_provider="local")
    router.reset_router()
    router.init_router(cfg)
    with pytest.raises(RouterError) as exc:
        await router.vision(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8, "q")
    assert exc.value.reason == "cloud_vision_disabled"
    assert srv.requests == []


@pytest.mark.asyncio
async def test_bad_image_type_is_e_bad_msg(tmp_path, make_server) -> None:
    srv = make_server(free_suffix=False)
    cfg = make_config(tmp_path, ["groq"], groq_url=srv.url)
    router.reset_router()
    router.init_router(cfg)
    with pytest.raises(RouterError) as exc:
        await router.vision(12345, "q")             # type: ignore[arg-type]
    assert exc.value.code == "E_BAD_MSG"
    assert srv.requests == []


# --------------------------------------------------------------------------- #
# Private Mode tripwire (Wave 5H re-verify): STREAM path is covered too
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_private_mode_blocks_stream_with_zero_egress(tmp_path,
                                                           make_server) -> None:
    import os
    os.environ["GROQ_API_KEY"] = SENTINEL
    srv = make_server(free_suffix=False)
    try:
        cfg = make_config(tmp_path, ["groq"], groq_url=srv.url)
        router.reset_router()
        rt = router.init_router(cfg)
        set_private_mode(True)
        events = []
        with pytest.raises(RouterError) as exc:
            async for ev in rt.chat([{"role": "user", "content": "hi"}],
                                    stream=True):
                events.append(ev)
        assert exc.value.code == "E_OFFLINE"
        assert exc.value.reason == "private_mode"
        assert events == []                         # refused before any delta
        assert srv.requests == []                   # zero egress, streamed or not
        # and the legacy seam degrades instead of raising
        res = await rt.complete("groq", "some-model", prompt="hi")
        assert res.ok is False and res.error_code == "E_OFFLINE"
        assert srv.requests == []
    finally:
        os.environ.pop("GROQ_API_KEY", None)
        set_private_mode(False)

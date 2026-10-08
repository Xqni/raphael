"""AUD-04 (AUDIT-2026-10-07 P0): free-model policy + configured redaction.

Pins the REAL policy (now honestly implemented + documented):
1. configured `privacy.redact` categories (email/phone/card/…) are scrubbed
   from EVERY outbound chat path (chat, stream, legacy complete, vision
   question) — secrets always;
2. PII detected BEFORE redaction + `allow_free_models_for_personal_data=false`
   (repo default) → FREE-tier providers are skipped for that call (routed to
   paid/local), and if nothing paid/local exists the call fails CLOSED with
   `E_OFFLINE / personal_data_free_only` — zero egress to free tiers;
3. flag=true restores free-tier use for personal content.
"""
from __future__ import annotations

import pytest

import brain.router as router
from brain.router import RouterError
from brain.router.privacy import detect_personal_data, redact_messages
from brain.router.tests.conftest import make_config

PII = "reach me at ada@example.com or +1 (555) 123-4567, card 4111 1111 1111 1111"
CLEAN = "hello there"


def _pair(tmp_path, make_server, **kw):
    """free tier (zen) + billed tier (go) servers, chain [zen_free, go]."""
    free = make_server(models=[{"id": "mimo-flash"}], free_suffix=True)
    paid = make_server(models=[{"id": "opencode-go/gpt-6-sol"}], free_suffix=False)
    cfg = make_config(tmp_path, ["zen_free", "go"],
                      zen_url=free.url, go_url=paid.url,
                      allow_go_runtime=True, allow_paid_runtime=True, **kw)
    router.reset_router()
    return router.init_router(cfg), free, paid


# --------------------------------------------------------------------------- #
# detection + configured redaction (units)
# --------------------------------------------------------------------------- #
def test_detect_personal_data_pii_trio_only() -> None:
    assert detect_personal_data(CLEAN) == set()
    assert detect_personal_data(f"mail {PII}") == {"email", "phone", "card"}
    assert detect_personal_data("password=hunter2 ok") == set()   # secrets ≠ PII trio
    # detection honours the CONFIGURED subset
    assert detect_personal_data("a@b.co", categories=("email",)) == {"email"}
    assert detect_personal_data("a@b.co", categories=()) == set()


def test_configured_categories_scrubbed() -> None:
    out = redact_messages([{"role": "user", "content": PII}],
                          categories=("api_key", "token", "password", "card",
                                      "email", "phone"))
    text = out[0]["content"]
    assert "ada@example.com" not in text
    assert "555" not in text
    assert "4111" not in text
    assert "[REDACTED]" in text


def test_repo_flag_defaults_to_no_free_models_for_personal_data() -> None:
    import os
    saved = os.environ.pop("RAPHAEL_PROFILE", None)
    try:
        cfg = router.load_config()
    finally:
        if saved is not None:
            os.environ["RAPHAEL_PROFILE"] = saved
    assert cfg.providers.allow_free_models_for_personal_data is False


# --------------------------------------------------------------------------- #
# routing: personal → free tier skipped (paid serves)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_personal_data_skips_free_tier(tmp_path, make_server, keys) -> None:
    rt, free, paid = _pair(tmp_path, make_server)
    out = await rt.chat([{"role": "user", "content": PII}])
    assert out["provider"] == "go"                 # paid endpoint serves
    assert free.chat_requests == []                # FREE tier untouched
    assert len(paid.chat_requests) == 1
    assert b"ada@example.com" not in paid.chat_requests[0]["body"]


@pytest.mark.asyncio
async def test_clean_content_still_uses_free_tier_first(tmp_path, make_server,
                                                        keys) -> None:
    rt, free, paid = _pair(tmp_path, make_server)
    out = await rt.chat([{"role": "user", "content": CLEAN}])
    assert out["provider"] == "zen_free"
    assert len(free.chat_requests) == 1
    assert paid.requests == []


@pytest.mark.asyncio
async def test_flag_true_restores_free_tier_for_personal(tmp_path, make_server,
                                                         keys) -> None:
    rt, free, paid = _pair(tmp_path, make_server,
                           allow_free_models_for_personal_data=True)
    out = await rt.chat([{"role": "user", "content": PII}])
    assert out["provider"] == "zen_free"           # policy allows it now
    assert len(free.chat_requests) == 1


@pytest.mark.asyncio
async def test_personal_with_free_only_chain_fails_closed(tmp_path, make_server,
                                                          keys) -> None:
    free = make_server(models=[{"id": "mimo-flash"}], free_suffix=True)
    cfg = make_config(tmp_path, ["zen_free"], zen_url=free.url)
    router.reset_router()
    rt = router.init_router(cfg)
    with pytest.raises(RouterError) as exc:
        await rt.chat([{"role": "user", "content": PII}])
    assert exc.value.code == "E_OFFLINE"
    assert exc.value.reason == "personal_data_free_only"
    assert isinstance(exc.value.spoken, str)
    assert free.requests == []                     # zero egress to the free tier


@pytest.mark.asyncio
async def test_stream_also_skips_free_tier(tmp_path, make_server, keys) -> None:
    rt, free, paid = _pair(tmp_path, make_server)
    events = [ev async for ev in rt.chat([{"role": "user", "content": PII}],
                                         stream=True)]
    final = [e for e in events if "finish" in e][0]
    assert final["provider"] == "go"
    assert free.chat_requests == []


@pytest.mark.asyncio
async def test_legacy_complete_fails_closed_on_free_provider(tmp_path,
                                                             make_server, keys) -> None:
    rt, free, paid = _pair(tmp_path, make_server)
    res = await rt.complete("zen_free", "mimo-flash-free", prompt=PII)
    assert res.ok is False
    assert res.error_code == "E_OFFLINE"
    assert free.requests == []


# --------------------------------------------------------------------------- #
# configured redaction on every outbound path
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_pii_scrubbed_on_chat_stream_vision_and_complete(
        tmp_path, make_server, keys) -> None:
    free = make_server(models=[{"id": "mimo-flash"},
                               {"id": "tiny-vision-8b"},
                               {"id": "whisper-large-v3"}], free_suffix=True)
    cfg = make_config(tmp_path, ["zen_free", "go"],
                      zen_url=free.url, go_url=free.url,
                      allow_go_runtime=True, allow_paid_runtime=True)
    router.reset_router()
    rt = router.init_router(cfg)

    await rt.chat([{"role": "user", "content": PII}])
    async for _ in rt.chat([{"role": "user", "content": PII}], stream=True):
        pass
    # legacy seam on the PAID tier: allowed (paid), still scrubbed
    res = await rt.complete("go", "opencode-go/gpt-6-sol", prompt=PII)
    assert res.ok
    await rt.vision(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32,
                    f"screenshot of {PII}")
    await rt.transcribe(b"RIFF" + b"\x00" * 64)

    bodies = b"".join(free.bodies())
    for leak in ("ada@example.com", "555) 123-4567", "4111 1111 1111 1111"):
        assert leak.encode() not in bodies, f"PII leaked outbound: {leak}"
    assert b"[REDACTED]" in bodies                  # redaction actually ran

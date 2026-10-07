"""Wave 4 regression: whisper prompt-bias seam (Wave-3 live gate, glue 07cadcb).

The live gate added prompt biasing: `Router.transcribe()` passes
`prompt="<voice.wake_word>."` to Groq Whisper so the wake word survives
accented/looped speech (that fix is what made acoustic wake work). This pins
the whole seam — config → router → provider multipart — so a refactor cannot
silently drop it (and the no-prompt path stays honest).
"""
from __future__ import annotations

import inspect

import pytest

import brain.router as router
from brain.router.tests.conftest import make_config

def _wav() -> bytes:
    import struct
    rate, channels, bits = 16000, 1, 16
    byte_rate = rate * channels * bits // 8
    data_size = byte_rate  # 1 s
    fmt = struct.pack("<HHIIHH", 1, channels, rate, byte_rate,
                      channels * bits // 8, bits)
    return (b"RIFF" + struct.pack("<I", 4 + 8 + len(fmt) + 8 + data_size)
            + b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt
            + b"data" + struct.pack("<I", data_size) + b"\x00" * data_size)


@pytest.mark.asyncio
async def test_wake_word_reaches_provider_as_prompt(tmp_path) -> None:
    """config.voice.wake_word → prompt field ("<wake>." ) on the STT call."""
    cfg = make_config(tmp_path, ["mock"], wake_word="raphael")
    router.reset_router()
    rt = router.init_router(cfg)
    out = await rt.transcribe(_wav(), language="en")
    assert out["text"]
    call = [c for c in rt._providers["mock"].calls
            if c["kind"] == "transcribe"][-1]
    assert call["prompt"] == "raphael."               # additive prompt kwarg
    assert call["language"] == "en"                   # language still forwarded


@pytest.mark.asyncio
async def test_no_prompt_when_wake_word_absent(tmp_path) -> None:
    cfg = make_config(tmp_path, ["mock"], wake_word="")
    router.reset_router()
    rt = router.init_router(cfg)
    await rt.transcribe(_wav(), language="en")
    call = [c for c in rt._providers["mock"].calls
            if c["kind"] == "transcribe"][-1]
    assert call["prompt"] is None                     # nothing to bias on


@pytest.mark.asyncio
async def test_prompt_goes_only_to_stt_never_to_chat(tmp_path) -> None:
    cfg = make_config(tmp_path, ["mock"], wake_word="raphael")
    router.reset_router()
    rt = router.init_router(cfg)
    await rt.chat([{"role": "user", "content": "hello"}])
    chat_calls = [c for c in rt._providers["mock"].calls if c["kind"] == "chat"]
    assert chat_calls
    assert "prompt" not in chat_calls[-1]             # whisper-only knob


def test_groq_multipart_carries_prompt(tmp_path, make_server, keys) -> None:
    """End of the seam: the Groq multipart BODY actually contains prompt=."""
    import asyncio
    srv = make_server(free_suffix=False)
    cfg = make_config(tmp_path, ["groq"], groq_url=srv.url, wake_word="raphael")
    router.reset_router()
    rt = router.init_router(cfg)
    asyncio.run(rt.transcribe(_wav(), language="en"))
    body = srv.transcribe_requests[0]["body"]
    assert b'name="prompt"' in body
    assert b"raphael." in body
    assert b'name="language"' in body


@pytest.mark.asyncio
async def test_facade_signature_matches_interfaces(tmp_path) -> None:
    """INTERFACES §a: transcribe(audio, language=None) — the prompt comes from
    CONFIG (voice.wake_word), never from the caller, so voice's
    `fn(audio, language=lang)` call keeps working unchanged."""
    params = list(inspect.signature(router.transcribe).parameters)
    assert params == ["audio", "language"]


@pytest.mark.asyncio
async def test_repo_config_supplies_wake_word() -> None:
    """Glue config wiring: voice.wake_word (config.yaml) reaches VoiceSettings."""
    import os
    saved = os.environ.pop("RAPHAEL_PROFILE", None)
    try:
        cfg = router.load_config()
    finally:
        if saved is not None:
            os.environ["RAPHAEL_PROFILE"] = saved
    assert cfg.voice.wake_word == "raphael"           # repo default
    assert cfg.voice.stt_engine == "groq"             # cloud_temp STT path

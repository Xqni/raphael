"""Wave 2 task 0+5: interface contract, deterministic mock, placeholder guard.

The interface lands FIRST (INTERFACES §a) so every other lane can build
against `brain.router.chat/vision/transcribe/health` with zero keys and zero
network via `RAPHAEL_ROUTER_MOCK=1`.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

import brain.router as router
from brain.router import RouterError
from brain.router.tests.conftest import make_config

# Any leftover "[provider:model] response" style stub (the bug that shipped
# nonsense spoken text) fails the build — see docs/status/router.md.
PLACEHOLDER_RE = re.compile(r"\[[^\]\s]*:[^\]\s]*\]\s*response", re.IGNORECASE)

ROUTER_SRC = Path(__file__).resolve().parents[1]


def _check_no_placeholder(*texts: str) -> None:
    for text in texts:
        assert not PLACEHOLDER_RE.search(text or ""), (
            f"placeholder text leaked into output: {text!r}"
        )


@pytest.fixture
def mock_router(tmp_path):
    cfg = make_config(tmp_path, ["mock"])
    router.reset_router()
    rt = router.init_router(cfg)
    yield rt
    router.reset_router()


# --------------------------------------------------------------------------- #
# interface shape (INTERFACES §a)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_chat_returns_documented_shape(mock_router) -> None:
    out = await router.chat([{"role": "user", "content": "hello"}])
    assert set(out) >= {"text", "tool_calls", "finish", "provider", "model", "usage"}
    assert out["provider"] == "mock"
    assert out["model"] == "mock-instant"          # role mapping, not hardcoding
    assert out["finish"] in ("stop", "tool_calls")
    assert isinstance(out["usage"], dict)
    assert set(out["usage"]) == {"input", "output"}
    _check_no_placeholder(out["text"])


@pytest.mark.asyncio
async def test_chat_stream_yields_deltas_then_final_frame(mock_router) -> None:
    events = []
    async for ev in router.chat([{"role": "user", "content": "stream me"}],
                                stream=True):
        events.append(ev)
    deltas = [e["delta"] for e in events if "delta" in e]
    finals = [e for e in events if "finish" in e]
    assert deltas, "stream must yield at least one delta"
    assert len(finals) == 1
    assert set(finals[0]) >= {"finish", "provider", "model", "tool_calls"}
    _check_no_placeholder("".join(deltas))


@pytest.mark.asyncio
async def test_chat_stream_with_tools_returns_tool_calls(mock_router) -> None:
    out = []
    async for ev in router.chat(
        [{"role": "user", "content": 'mock_call:launch_app{"name": "notepad"}'}],
        tools=[{"type": "function",
                "function": {"name": "launch_app",
                             "parameters": {"type": "object"}}}],
        stream=True,
    ):
        out.append(ev)
    final = [e for e in out if "finish" in e][0]
    assert final["finish"] == "tool_calls"
    assert final["tool_calls"][0]["function"]["name"] == "launch_app"
    assert final["tool_calls"][0]["function"]["arguments"] == {"name": "notepad"}


@pytest.mark.asyncio
async def test_vision_returns_documented_shape(mock_router) -> None:
    out = await router.vision(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32,
                              "what is on screen?")
    assert set(out) == {"text", "provider", "model"}
    assert out["model"] == "mock-vision"
    _check_no_placeholder(out["text"])


@pytest.mark.asyncio
async def test_transcribe_returns_documented_shape(mock_router) -> None:
    out = await router.transcribe(b"RIFF" + b"\x00" * 64, language="en")
    assert set(out) == {"text", "rtf"}
    assert isinstance(out["text"], str) and out["text"]
    _check_no_placeholder(out["text"])


@pytest.mark.asyncio
async def test_health_returns_documented_shape(mock_router) -> None:
    out = await router.health()
    assert set(out) == {"ok", "providers"}
    assert out["ok"] is True
    info = out["providers"]["mock"]
    assert set(info) == {"ok", "models", "last_error"}
    assert info["models"] == 4


# --------------------------------------------------------------------------- #
# determinism + error contract
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_mock_is_deterministic(mock_router) -> None:
    msgs = [{"role": "user", "content": "same input"}]
    first = await router.chat(msgs)
    second = await router.chat(msgs)
    assert first["text"] == second["text"]
    assert first["model"] == second["model"]


@pytest.mark.asyncio
async def test_errors_are_router_errors_with_protocol_codes(mock_router) -> None:
    with pytest.raises(RouterError) as exc:
        await router.chat([{"role": "user", "content": "mock_fail:E_PROVIDER_429"}])
    assert exc.value.code == "E_PROVIDER_429"
    assert exc.value.retryable is True
    # spoken-friendly detail only for §10 spoken codes
    assert isinstance(exc.value.spoken, str)


@pytest.mark.asyncio
async def test_bad_payload_is_e_bad_msg(mock_router) -> None:
    with pytest.raises(RouterError) as exc:
        await router.chat([])
    assert exc.value.code == "E_BAD_MSG"
    with pytest.raises(RouterError) as exc2:
        await router.transcribe(b"")
    assert exc2.value.code == "E_BAD_MSG"


# --------------------------------------------------------------------------- #
# placeholder guard (task 5)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_no_placeholder_text_in_any_facade_output(tmp_path) -> None:
    cfg = make_config(tmp_path, ["mock"])
    router.reset_router()
    router.init_router(cfg)
    chat_out = await router.chat([{"role": "user", "content": "hi"}])
    vision_out = await router.vision(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8, "q?")
    stt_out = await router.transcribe(b"RIFF" + b"\x00" * 8)
    _check_no_placeholder(chat_out["text"], vision_out["text"], stt_out["text"])


def test_no_placeholder_stub_in_router_source() -> None:
    """Regression: the old stub literally replied '[provider:model] response'."""
    offenders = []
    for py in sorted(ROUTER_SRC.glob("*.py")):
        text = py.read_text(encoding="utf-8")
        for line in text.splitlines():
            if PLACEHOLDER_RE.search(line) and "PLACEHOLDER" not in line:
                offenders.append(f"{py.name}: {line.strip()}")
    assert not offenders, "placeholder stub text found in router source:\n" + "\n".join(offenders)


def test_facade_documented_in_package_docstring() -> None:
    doc = router.__doc__ or ""
    for name in ("chat", "vision", "transcribe", "health"):
        assert name in doc, f"{name} missing from brain.router docstring"

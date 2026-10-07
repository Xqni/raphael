"""Wave 2 task 5: contract tests against a scripted OpenAI-compatible server.

Everything runs on 127.0.0.1 with scripted responses — tool calls, 429s,
5xx, malformed JSON, SSE streams, rate-limit headers. No external network,
no real keys (conftest isolates `.env`).
"""
from __future__ import annotations

import json
import time

import pytest

import brain.router as router
from brain.router import RouterError
from brain.router.tests.conftest import make_config
from brain.router.tests.mockserver import (
    sse_text_stream,
    sse_tool_stream,
    tool_reply,
)

def _router(tmp_path, cfg):
    router.reset_router()
    return router.init_router(cfg)


def _msgs(text: str = "hello there"):
    return [{"role": "user", "content": text}]


def _wav(seconds: float = 1.0) -> bytes:
    """Minimal valid PCM WAV (16 kHz mono 16-bit) so rtf can be computed."""
    import struct
    rate, channels, bits = 16000, 1, 16
    byte_rate = rate * channels * bits // 8
    data_size = int(byte_rate * seconds)
    fmt = struct.pack("<HHIIHH", 1, channels, rate, byte_rate,
                      channels * bits // 8, bits)
    header = (b"RIFF" + struct.pack("<I", 4 + 8 + len(fmt) + 8 + data_size)
              + b"WAVE"
              + b"fmt " + struct.pack("<I", len(fmt)) + fmt
              + b"data" + struct.pack("<I", data_size))
    return header + b"\x00" * data_size


# --------------------------------------------------------------------------- #
# discovery → role mapping (never hardcoded)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_model_choice_comes_from_live_discovery(tmp_path, make_server, keys) -> None:
    srv = make_server(models=[{"id": "custom-widget-90b"}], free_suffix=False)
    cfg = make_config(tmp_path, ["groq"], groq_url=srv.url)
    _router(tmp_path, cfg)
    out = await router.chat(_msgs())
    assert out["model"] == "custom-widget-90b"      # exactly what /models said
    assert srv.model_requests, "discovery must hit GET /models"
    # strong slot (90b hint) was picked for a tool-less chat? fast fallback:
    assert out["provider"] == "groq"


@pytest.mark.asyncio
async def test_fast_and_strong_role_mapping(tmp_path, make_server, keys) -> None:
    srv = make_server(models=[{"id": "tiny-flash-4b"}, {"id": "giant-plus-70b"}],
                      free_suffix=False)
    cfg = make_config(tmp_path, ["groq"], groq_url=srv.url)
    _router(tmp_path, cfg)
    chat = await router.chat(_msgs())
    assert chat["model"] == "tiny-flash-4b"          # fast hints win for chat
    srv.chat_script.append(tool_reply("shell", '{"command": "ls"}'))
    with_tool = await router.chat(
        _msgs(), tools=[{"type": "function",
                         "function": {"name": "shell",
                                      "parameters": {"type": "object"}}}])
    assert with_tool["model"] == "giant-plus-70b"     # tools → strong slot
    assert with_tool["finish"] == "tool_calls"
    assert with_tool["tool_calls"][0]["function"]["name"] == "shell"


@pytest.mark.asyncio
async def test_classifier_and_tts_models_never_selected(tmp_path, make_server, keys) -> None:
    """Groq's live list carries prompt-guard/orpheus — deny-hints keep them out."""
    srv = make_server(models=[{"id": "meta-llama/llama-prompt-guard-2-22m"},
                              {"id": "canopylabs/orpheus-v1-english"},
                              {"id": "allam-2-7b"}], free_suffix=False)
    cfg = make_config(tmp_path, ["groq"], groq_url=srv.url)
    _router(tmp_path, cfg)
    out = await router.chat(_msgs())
    assert out["model"] == "allam-2-7b"


# --------------------------------------------------------------------------- #
# tool calls + JSON repair (task 2)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_tool_call_normalized_with_malformed_json_repaired(
        tmp_path, make_server, keys) -> None:
    srv = make_server(free_suffix=False)
    srv.chat_script.append(tool_reply(
        "open_url", '{"url": "https://example.test", "new_tab": true,}'))
    cfg = make_config(tmp_path, ["groq"], groq_url=srv.url)
    _router(tmp_path, cfg)
    out = await router.chat(_msgs(), tools=[{"type": "function", "function": {
        "name": "open_url", "parameters": {"type": "object"}}}])
    assert out["finish"] == "tool_calls"
    tc = out["tool_calls"][0]
    assert tc["type"] == "function"
    assert tc["function"]["name"] == "open_url"
    assert tc["function"]["arguments"] == {"url": "https://example.test",
                                           "new_tab": True}
    assert tc["repaired"] is True                    # trailing comma was fixed
    assert tc["arguments_raw"]                        # original kept for audit


@pytest.mark.asyncio
async def test_tool_call_single_quoted_and_truncated_arguments(
        tmp_path, make_server, keys) -> None:
    srv = make_server(free_suffix=False)
    srv.chat_script.append(tool_reply("open_app", "{'name': 'notepad'"))
    cfg = make_config(tmp_path, ["groq"], groq_url=srv.url)
    _router(tmp_path, cfg)
    out = await router.chat(_msgs(), tools=[{"type": "function", "function": {
        "name": "open_app", "parameters": {"type": "object"}}}])
    assert out["tool_calls"][0]["function"]["arguments"] == {"name": "notepad"}


@pytest.mark.asyncio
async def test_unrecoverable_arguments_keep_raw_text(tmp_path, make_server, keys) -> None:
    srv = make_server(free_suffix=False)
    srv.chat_script.append(tool_reply("shell", "definitely not json"))
    cfg = make_config(tmp_path, ["groq"], groq_url=srv.url)
    _router(tmp_path, cfg)
    out = await router.chat(_msgs(), tools=[{"type": "function", "function": {
        "name": "shell", "parameters": {"type": "object"}}}])
    args = out["tool_calls"][0]["function"]["arguments"]
    assert args == {"_raw": "definitely not json"}   # nothing silently dropped


# --------------------------------------------------------------------------- #
# streaming (task 2)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_stream_deltas_and_final_frame(tmp_path, make_server, keys) -> None:
    srv = make_server(free_suffix=False)
    srv.chat_script.append(sse_text_stream("the quick brown fox"))
    cfg = make_config(tmp_path, ["groq"], groq_url=srv.url)
    _router(tmp_path, cfg)
    events = []
    async for ev in router.chat(_msgs(), stream=True):
        events.append(ev)
    text = "".join(e["delta"] for e in events if "delta" in e)
    assert text == "the quick brown fox"
    final = [e for e in events if "finish" in e]
    assert len(final) == 1
    assert final[0]["provider"] == "groq"
    assert final[0]["finish"] == "stop"
    assert final[0]["usage"] == {"input": 5, "output": 6}


@pytest.mark.asyncio
async def test_stream_tool_call_fragments_repaired(tmp_path, make_server, keys) -> None:
    srv = make_server(free_suffix=False)
    srv.chat_script.append(sse_tool_stream("launch_app", "{'name': 'notepad'}"))
    cfg = make_config(tmp_path, ["groq"], groq_url=srv.url)
    _router(tmp_path, cfg)
    events = [ev async for ev in router.chat(
        _msgs(), tools=[{"type": "function", "function": {
            "name": "launch_app", "parameters": {"type": "object"}}}],
        stream=True)]
    final = [e for e in events if "finish" in e][0]
    assert final["finish"] == "tool_calls"
    assert final["tool_calls"][0]["function"]["name"] == "launch_app"
    assert final["tool_calls"][0]["function"]["arguments"] == {"name": "notepad"}
    assert final["tool_calls"][0]["repaired"] is True


@pytest.mark.asyncio
async def test_stream_before_first_delta_can_fail_over(tmp_path, make_server, keys) -> None:
    groq = make_server(free_suffix=False)
    zen = make_server(models=[{"id": "mimo-flash"}], free_suffix=True)
    groq.chat_script.append((500, {}, b'{"error":"boom"}'))
    zen.chat_script.append(sse_text_stream("recovered over the failover"))
    cfg = make_config(tmp_path, ["groq", "zen_free"],
                      groq_url=groq.url, zen_url=zen.url)
    _router(tmp_path, cfg)
    events = [ev async for ev in router.chat(_msgs(), stream=True)]
    text = "".join(e["delta"] for e in events if "delta" in e)
    assert text == "recovered over the failover"
    assert [e for e in events if "finish" in e][0]["provider"] == "zen_free"


# --------------------------------------------------------------------------- #
# resilience: 429 / 5xx / auth / backoff / failover (task 3)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_429_with_retry_after_is_retried_then_succeeds(
        tmp_path, make_server, keys) -> None:
    srv = make_server(free_suffix=False)
    srv.chat_script.append((429, {"Retry-After": "0.01"},
                            b'{"error":{"message":"rate limited"}}'))
    cfg = make_config(tmp_path, ["groq"], groq_url=srv.url)
    _router(tmp_path, cfg)
    out = await router.chat(_msgs())
    assert out["provider"] == "groq"
    assert len(srv.chat_requests) == 2               # 429 then success


@pytest.mark.asyncio
async def test_long_retry_after_honored_as_cooldown_and_failed_over(
        tmp_path, make_server, keys) -> None:
    groq = make_server(free_suffix=False)
    zen = make_server(models=[{"id": "mimo-flash"}], free_suffix=True)
    groq.chat_script.append((429, {"Retry-After": "120"}, b"{}"))
    cfg = make_config(tmp_path, ["groq", "zen_free"],
                      groq_url=groq.url, zen_url=zen.url)
    rt = _router(tmp_path, cfg)
    out = await router.chat(_msgs())
    assert out["provider"] == "zen_free"
    assert len(groq.chat_requests) == 1              # no pointless 120 s wait
    assert rt._stats["groq"].cooldown_until > time.monotonic()


@pytest.mark.asyncio
async def test_5xx_fails_over_to_next_provider(tmp_path, make_server, keys) -> None:
    groq = make_server(free_suffix=False)
    zen = make_server(models=[{"id": "mimo-flash"}], free_suffix=True)
    groq.chat_script.extend([(503, {}, b"unavailable"),   # attempt 1
                             (503, {}, b"unavailable")])  # retry also fails
    cfg = make_config(tmp_path, ["groq", "zen_free"],
                      groq_url=groq.url, zen_url=zen.url)
    _router(tmp_path, cfg)
    out = await router.chat(_msgs())
    assert out["provider"] == "zen_free"
    assert len(groq.chat_requests) == 2


@pytest.mark.asyncio
async def test_401_maps_to_provider_auth(tmp_path, make_server, keys) -> None:
    srv = make_server(free_suffix=False)
    srv.chat_script.append((401, {}, b'{"error":{"message":"bad key"}}'))
    cfg = make_config(tmp_path, ["groq"], groq_url=srv.url)
    _router(tmp_path, cfg)
    with pytest.raises(RouterError) as exc:
        await router.chat(_msgs())
    assert exc.value.code == "E_PROVIDER_AUTH"
    assert exc.value.retryable is False              # §10: fatal
    assert len(srv.chat_requests) == 1               # fatal → no blind retry


@pytest.mark.asyncio
async def test_garbage_body_maps_to_provider_5xx(tmp_path, make_server, keys) -> None:
    srv = make_server(free_suffix=False)
    srv.chat_script.append(b"<html>not json</html>")
    cfg = make_config(tmp_path, ["groq"], groq_url=srv.url, max_retries=0)
    _router(tmp_path, cfg)
    with pytest.raises(RouterError) as exc:
        await router.chat(_msgs())
    assert exc.value.code == "E_PROVIDER_5XX"


@pytest.mark.asyncio
async def test_network_unreachable_maps_to_offline(tmp_path) -> None:
    cfg = make_config(tmp_path, ["groq"], groq_url="http://127.0.0.1:1",
                      keys=None)
    _router(tmp_path, cfg)
    with pytest.raises(RouterError) as exc:
        # no keys set → admission skips groq before any socket; add a key
        import os
        os.environ["GROQ_API_KEY"] = "gsk_test_key_not_real_0001"
        try:
            await router.chat(_msgs())
        finally:
            os.environ.pop("GROQ_API_KEY", None)
    assert exc.value.code == "E_OFFLINE"
    assert exc.value.reason == "chain_exhausted"


@pytest.mark.asyncio
async def test_missing_key_fails_over_without_any_request(
        tmp_path, make_server) -> None:
    """Value-blind key check: no GROQ key → groq never touched, zen serves."""
    zen = make_server(models=[{"id": "mimo-flash"}], free_suffix=True)
    groq = make_server(free_suffix=False)
    import os
    os.environ["OPENCODE_API_KEY"] = "oc_test_key_not_real_0002"
    try:
        cfg = make_config(tmp_path, ["groq", "zen_free"],
                          groq_url=groq.url, zen_url=zen.url)
        _router(tmp_path, cfg)
        out = await router.chat(_msgs())
    finally:
        os.environ.pop("OPENCODE_API_KEY", None)
    assert out["provider"] == "zen_free"
    assert groq.requests == []                       # no key → zero egress


@pytest.mark.asyncio
async def test_rate_limit_headers_set_cooldown(tmp_path, make_server, keys) -> None:
    groq = make_server(free_suffix=False)
    zen = make_server(models=[{"id": "mimo-flash"}], free_suffix=True)
    groq.chat_script.append((
        200,
        {"X-RateLimit-Remaining-Requests": "0",
         "X-RateLimit-Reset-Requests": "60"},
        json.dumps({"choices": [{"message": {"content": "ok"},
                                 "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 3, "completion_tokens": 1}}).encode(),
    ))
    cfg = make_config(tmp_path, ["groq", "zen_free"],
                      groq_url=groq.url, zen_url=zen.url)
    rt = _router(tmp_path, cfg)
    first = await router.chat(_msgs())
    assert first["provider"] == "groq"
    assert rt._stats["groq"].cooldown_until > time.monotonic()
    second = await router.chat(_msgs())
    assert second["provider"] == "zen_free"          # cooldown honored → failover
    assert len(groq.chat_requests) == 1


@pytest.mark.asyncio
async def test_local_rpm_budget_skips_provider(tmp_path, make_server, keys) -> None:
    groq = make_server(free_suffix=False)
    zen = make_server(models=[{"id": "mimo-flash"}], free_suffix=True)
    cfg = make_config(tmp_path, ["groq", "zen_free"],
                      groq_url=groq.url, zen_url=zen.url,
                      rpm={"groq": 0, "zen_free": 100, "go": 1, "ollama": 1,
                           "mock": 1})
    _router(tmp_path, cfg)
    out = await router.chat(_msgs())
    assert out["provider"] == "zen_free"
    assert groq.requests == []                       # budget stops pre-flight


@pytest.mark.asyncio
async def test_local_tpm_budget_skips_provider(tmp_path, make_server, keys) -> None:
    groq = make_server(free_suffix=False)
    zen = make_server(models=[{"id": "mimo-flash"}], free_suffix=True)
    cfg = make_config(tmp_path, ["groq", "zen_free"],
                      groq_url=groq.url, zen_url=zen.url,
                      tpm={"groq": 3, "zen_free": 1_000_000, "go": 1_000_000,
                           "ollama": 1_000_000, "mock": 1_000_000})
    _router(tmp_path, cfg)
    out = await router.chat(_msgs("a much longer message than three tokens"))
    assert out["provider"] == "zen_free"
    assert groq.requests == []


@pytest.mark.asyncio
async def test_circuit_breaker_opens_and_stops_calling(
        tmp_path, make_server, keys) -> None:
    groq = make_server(free_suffix=False)
    groq.chat_script.extend([(500, {}, b"boom")] * 50)
    cfg = make_config(tmp_path, ["groq"], groq_url=groq.url, max_retries=1)
    rt = _router(tmp_path, cfg)
    for _ in range(5):                               # failure_threshold = 5
        with pytest.raises(RouterError):
            await router.chat(_msgs())
    assert rt._stats["groq"].circuit.state.value == "open"
    before = len(groq.chat_requests)
    with pytest.raises(RouterError) as exc:
        await router.chat(_msgs())
    assert exc.value.reason in ("circuit_open", "chain_exhausted")
    assert len(groq.chat_requests) == before          # breaker: zero new calls


@pytest.mark.asyncio
async def test_model_vanished_triggers_rediscovery(tmp_path, make_server, keys) -> None:
    srv = make_server(free_suffix=False)
    srv.chat_script.append((404, {}, b'{"error":{"message":"model gone"}}'))
    cfg = make_config(tmp_path, ["groq"], groq_url=srv.url, max_retries=2)
    _router(tmp_path, cfg)
    out = await router.chat(_msgs())
    assert out["provider"] == "groq"
    assert len(srv.model_requests) >= 2              # re-discovered after 404


@pytest.mark.asyncio
async def test_go_provider_stays_gated_off(tmp_path, make_server, keys) -> None:
    srv = make_server(free_suffix=False)
    cfg = make_config(tmp_path, ["go"], go_url=srv.url, allow_go_runtime=False)
    _router(tmp_path, cfg)
    with pytest.raises(RouterError) as exc:
        await router.chat(_msgs())
    assert exc.value.code == "E_OFFLINE"
    assert exc.value.reason == "chain_exhausted"
    assert srv.requests == []                        # gated → never touched


@pytest.mark.asyncio
async def test_paid_models_filtered_from_zen(tmp_path, make_server, keys) -> None:
    """Zen returns no `free` flag — only `…-free` ids may be selected."""
    zen = make_server(models=[{"id": "claude-opus-5"}, {"id": "mimo-flash"}],
                      free_suffix=False)
    zen.models = [{"id": "claude-opus-5"}, {"id": "mimo-flash-free"}]
    cfg = make_config(tmp_path, ["zen_free"], zen_url=zen.url)
    _router(tmp_path, cfg)
    out = await router.chat(_msgs())
    assert out["model"] == "mimo-flash-free"
    # asking for the strong slot still cannot reach the paid model
    out2 = await router.chat(
        _msgs(), tools=[{"type": "function", "function": {
            "name": "x", "parameters": {"type": "object"}}}])
    assert out2["model"] == "mimo-flash-free"


# --------------------------------------------------------------------------- #
# transcription (Groq Whisper, task 2)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_transcribe_posts_multipart_to_whisper(tmp_path, make_server, keys) -> None:
    srv = make_server(free_suffix=False)
    cfg = make_config(tmp_path, ["groq"], groq_url=srv.url)
    _router(tmp_path, cfg)
    out = await router.transcribe(_wav(), language="en")
    assert out["text"] == "mock whisper transcript"
    assert out["rtf"] is not None                     # WAV duration is known
    assert len(srv.transcribe_requests) == 1
    req = srv.transcribe_requests[0]
    body = req["body"]
    assert b"multipart/form-data" in req["headers"]["content-type"].encode()
    assert b"whisper" in body                        # model came from discovery
    assert b"audio.wav" in body
    assert b"language" in body


@pytest.mark.asyncio
async def test_transcribe_picks_whisper_slot(tmp_path, make_server, keys) -> None:
    srv = make_server(models=[{"id": "allam-2-7b"}, {"id": "whisper-large-v3"}],
                      free_suffix=False)
    cfg = make_config(tmp_path, ["groq"], groq_url=srv.url)
    _router(tmp_path, cfg)
    await router.transcribe(b"RIFF" + b"\x00" * 64)
    body = srv.transcribe_requests[0]["body"]
    assert b"whisper-large-v3" in body
    assert b"allam-2-7b" not in body


@pytest.mark.asyncio
async def test_transcribe_failover_to_next_provider(tmp_path, make_server, keys) -> None:
    groq = make_server(free_suffix=False)
    zen = make_server(models=[{"id": "whisper-free"}], free_suffix=False)
    groq.transcribe_script.append((500, {}, b"boom"))
    cfg = make_config(tmp_path, ["groq", "zen_free"],
                      groq_url=groq.url, zen_url=zen.url, max_retries=0)
    _router(tmp_path, cfg)
    out = await router.transcribe(_wav())
    assert out["text"] == "mock whisper transcript"
    assert groq.transcribe_requests and zen.transcribe_requests


# --------------------------------------------------------------------------- #
# health
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_health_reports_per_provider_state(tmp_path, make_server, keys) -> None:
    groq = make_server(free_suffix=False)
    zen = make_server(models=[{"id": "mimo-flash"}], free_suffix=True)
    cfg = make_config(tmp_path, ["groq", "zen_free"],
                      groq_url=groq.url, zen_url=zen.url)
    _router(tmp_path, cfg)
    out = await router.health()
    assert out["ok"] is True
    assert out["providers"]["groq"]["ok"] is True
    assert out["providers"]["groq"]["models"] == 4   # DEFAULT_MODELS size
    assert out["providers"]["zen_free"]["ok"] is True


@pytest.mark.asyncio
async def test_health_marks_dead_provider(tmp_path, make_server, keys) -> None:
    dead = make_server(free_suffix=False)
    dead.stop()                                       # port closed → connection refused
    live = make_server(models=[{"id": "mimo-flash"}], free_suffix=True)
    cfg = make_config(tmp_path, ["groq", "zen_free"],
                      groq_url=dead.url, zen_url=live.url)
    _router(tmp_path, cfg)
    out = await router.health()
    assert out["providers"]["groq"]["ok"] is False
    assert out["providers"]["groq"]["last_error"]
    assert out["providers"]["zen_free"]["ok"] is True
    assert out["ok"] is True                          # one live provider is enough

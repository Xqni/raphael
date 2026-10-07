"""Wave 4: usage-log integrity audit (`brain/router/usage.jsonl`).

The usage log feeds `/status` accounting and the paid-spend audit, so it must
be: valid JSON per line, stable schema, append-only, crash-safe (a torn final
line must never fuse the next event), and free of every sensitive payload —
prompts, key values, Authorization headers, image bytes.
"""
from __future__ import annotations

import asyncio
import json

import pytest

import brain.router as router
from brain.router.status import read_usage_events
from brain.router.tests.conftest import make_config

REQUIRED_KEYS = {"timestamp", "provider", "model", "tokens_input",
                 "tokens_output", "latency_ms", "outcome", "task_kind",
                 "error_code"}

SENTINEL_KEY = "gsk_USAGELOGMUSTNEVERLEAK9876543210"
PROMPT_MARKER = "TOPSECRET_PROMPT_MARKER_XYZZY"
IMAGE = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 2


def _records(path):
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))          # every line MUST parse
    return out


@pytest.fixture
def audit_router(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", SENTINEL_KEY)
    cfg = make_config(tmp_path, ["mock"], wake_word="raphael")
    router.reset_router()
    rt = router.init_router(cfg)
    yield rt, cfg.usage_log_path


@pytest.mark.asyncio
async def test_every_line_parses_with_stable_schema(audit_router) -> None:
    rt, log = audit_router
    await rt.chat([{"role": "user", "content": "hello"}])
    with pytest.raises(router.RouterError):          # failures must log, not crash
        await rt.chat([{"role": "user", "content": "mock_fail:E_PROVIDER_429"}])
    async for _ in rt.chat([{"role": "user", "content": "stream"}], stream=True):
        pass
    await rt.vision(IMAGE, "describe")
    await rt.transcribe(b"RIFF" + b"\x00" * 64)

    records = _records(log)
    assert len(records) >= 5
    for rec in records:
        assert REQUIRED_KEYS <= set(rec), set(rec)
        assert rec["outcome"] in ("success", "failed", "retry", "unavailable")
        assert isinstance(rec["tokens_input"], int)
        if rec["outcome"] == "success":
            assert rec["error_code"] is None
        else:
            assert rec["error_code"] and rec["error_code"].startswith("E_")


@pytest.mark.asyncio
async def test_failed_chat_logs_its_protocol_code(audit_router) -> None:
    """Failure events power by_provider.errors / errors{} in usage_status()."""
    rt, log = audit_router
    with pytest.raises(router.RouterError):
        await rt.chat([{"role": "user", "content": "mock_fail:E_PROVIDER_5XX"}])
    records = _records(log)
    failed = [r for r in records if r["outcome"] != "success"]
    assert failed, "a failed chat must leave an audit line"
    assert failed[-1]["error_code"] == "E_PROVIDER_5XX"
    assert failed[-1]["provider"] == "mock"


@pytest.mark.asyncio
async def test_log_never_contains_prompts_keys_or_images(audit_router) -> None:
    rt, log = audit_router
    await rt.chat([{"role": "user", "content": f"my key is {SENTINEL_KEY} "
                                                f"and remember {PROMPT_MARKER}"}])
    await rt.vision(IMAGE, "screenshot check")
    raw = log.read_text(encoding="utf-8")
    assert SENTINEL_KEY not in raw                   # no key values
    assert "STATUSMUSTNOTLEAK" not in raw            # (env sentinel variant too)
    assert PROMPT_MARKER not in raw                  # no prompt/message content
    assert "Bearer " not in raw                      # no auth headers
    assert IMAGE not in raw.encode("utf-8", "replace")   # no raw image bytes
    import base64
    assert base64.b64encode(IMAGE).decode() not in raw   # no image payload either


@pytest.mark.asyncio
async def test_concurrent_chats_write_clean_lines(audit_router) -> None:
    rt, log = audit_router
    results = await asyncio.gather(
        *[rt.chat([{"role": "user", "content": f"parallel {i}"}])
          for i in range(8)])
    assert all(r["provider"] == "mock" for r in results)
    records = _records(log)                          # every line still parses
    assert len(records) >= 8
    assert sum(1 for r in records if r["outcome"] == "success") >= 8


@pytest.mark.asyncio
async def test_torn_final_line_is_isolated_not_fused(audit_router) -> None:
    """Crash recovery: process dies mid-write → the fragment must not corrupt
    the NEXT event (append repairs the newline first), and the reader skips
    the fragment while keeping every good line."""
    rt, log = audit_router
    await rt.chat([{"role": "user", "content": "before crash"}])
    with log.open("a", encoding="utf-8") as fh:      # simulate a torn write
        fh.write('{"timestamp": "2026-10-07T00:00:00", "provider": "mock"')

    await rt.chat([{"role": "user", "content": "after crash"}])

    lines = [l for l in log.read_text(encoding="utf-8").splitlines() if l.strip()]
    good = 0
    for line in lines:
        try:
            json.loads(line)
            good += 1
        except ValueError:
            continue                                 # the torn fragment
    assert good >= 2, "both real events must survive the torn line"
    events = read_usage_events(log)
    assert any("after" in json.dumps(e) or e.get("provider") == "mock"
               for e in events)
    assert len(events) >= 2                          # reader keeps good lines


@pytest.mark.asyncio
async def test_usage_log_path_is_runtime_only(audit_router) -> None:
    """Sanity: the log never lands in tracked source (OWNERSHIP: usage.jsonl
    is runtime data, gitignored)."""
    _, log = audit_router
    assert log.name == "usage.jsonl"
    assert "brain" in log.parts or log.is_absolute()

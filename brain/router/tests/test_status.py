"""Wave 3 lane goal: usage/rate tracking surfaced in `GET /status`.

`brain.router.usage_status()` is the router-side dict brain-core plugs into
`/status`. It must aggregate the 24 h usage log, expose live RPM/TPM/breaker
state, include the vision-paid budget when the slot is on, never raise on a
missing/corrupt log, and never leak a key.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

import brain.router as router
from brain.router.status import read_usage_events, summarize_events
from brain.router.tests.conftest import make_config


def _event(ts_offset_h=0.0, provider="groq", model="m", outcome="success",
           task_kind="chat", tin=10, tout=5, error_code=None):
    when = (datetime.now(timezone.utc) - timedelta(hours=ts_offset_h)).isoformat()
    return json.dumps({
        "timestamp": when, "provider": provider, "model": model,
        "tokens_input": tin, "tokens_output": tout, "latency_ms": 12.0,
        "outcome": outcome, "task_kind": task_kind, "error_code": error_code,
    })


# --------------------------------------------------------------------------- #
# pure aggregation
# --------------------------------------------------------------------------- #
def test_summarize_events_counts_and_buckets() -> None:
    events = [
        json.loads(_event(provider="groq", task_kind="chat", tin=10, tout=5)),
        json.loads(_event(provider="groq", task_kind="tool", tin=20, tout=8)),
        json.loads(_event(provider="zen_free", task_kind="vision", outcome="failed",
                          error_code="E_PROVIDER_429", tin=0, tout=0)),
        json.loads(_event(provider="go_vision", task_kind="vision", tin=1500, tout=300)),
    ]
    out = summarize_events(events)
    assert out["calls"] == {"total": 4, "ok": 3, "errors": 1}
    assert out["tokens"] == {"input": 1530, "output": 313}
    assert out["by_provider"]["groq"]["calls"] == 2
    assert out["by_provider"]["zen_free"]["errors"] == 1
    assert out["by_provider"]["go_vision"]["input"] == 1500
    assert out["by_purpose"]["vision"]["calls"] == 2
    assert out["by_purpose"]["tool"]["calls"] == 1
    assert out["errors"] == {"E_PROVIDER_429": 1}


def test_read_usage_events_filters_old_and_survives_corruption(tmp_path) -> None:
    path = tmp_path / "usage.jsonl"
    path.write_text(
        _event(ts_offset_h=1.0) + "\n" +
        "this is not json\n" +
        _event(ts_offset_h=48.0) + "\n" +      # outside the 24 h window
        _event(ts_offset_h=0.5) + "\n",
        encoding="utf-8",
    )
    events = read_usage_events(path)
    assert len(events) == 2                    # corrupt + stale lines dropped

    assert read_usage_events(tmp_path / "missing.jsonl") == []   # missing → empty
    path.write_text("", encoding="utf-8")
    assert read_usage_events(path) == []                        # empty → empty


# --------------------------------------------------------------------------- #
# facade
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_usage_status_from_log(tmp_path, monkeypatch) -> None:
    cfg = make_config(tmp_path, ["mock"])
    log = cfg.usage_log_path               # whatever config points at
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(
        _event(provider="groq", task_kind="chat", tin=11, tout=7) + "\n" +
        _event(provider="groq", task_kind="chat", outcome="failed",
               error_code="E_PROVIDER_5XX", tin=0, tout=0) + "\n" +
        _event(provider="go_vision", task_kind="vision", tin=1500, tout=250) + "\n",
        encoding="utf-8",
    )
    router.reset_router()
    rt = router.init_router(cfg)
    out = await rt.usage_status()
    assert out["window_hours"] == 24
    assert out["calls"]["total"] == 3
    assert out["calls"]["errors"] == 1
    assert out["tokens"] == {"input": 1511, "output": 257}
    assert out["by_provider"]["groq"]["errors"] == 1
    assert out["errors"] == {"E_PROVIDER_5XX": 1}
    assert "mock" in out["providers"]          # live block for the chain


@pytest.mark.asyncio
async def test_usage_status_live_rate_state(tmp_path) -> None:
    cfg = make_config(tmp_path, ["mock"], rpm={"mock": 7, "groq": 30, "zen_free": 12,
                                               "go": 10, "go_vision": 10, "ollama": 60},
                      tpm={"mock": 5000, "groq": 1, "zen_free": 1, "go": 1,
                           "go_vision": 1, "ollama": 1})
    router.reset_router()
    rt = router.init_router(cfg)
    await rt.chat([{"role": "user", "content": "hi"}])
    out = await rt.usage_status()
    live = out["providers"]["mock"]
    assert live["circuit"] == "closed"
    assert live["cooldown_s"] == 0.0
    assert live["rpm"] == {"used": 1, "cap": 7, "window_s": 60.0}
    assert live["tpm"]["cap"] == 5000
    assert live["tpm"]["used"] > 0             # the call's tokens were recorded
    assert live["last_error"] is None
    # one call landed in the log too
    assert out["calls"]["total"] >= 1
    assert out["by_purpose"]["chat"]["calls"] >= 1


@pytest.mark.asyncio
async def test_usage_status_never_raises_on_broken_log(tmp_path) -> None:
    cfg = make_config(tmp_path, ["mock"])
    log = cfg.usage_log_path
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("{corrupt json\n\x00\x00garbage", encoding="utf-8")
    router.reset_router()
    rt = router.init_router(cfg)
    out = await rt.usage_status()               # must not raise
    assert out["calls"]["total"] == 0
    assert out["providers"]["mock"]["circuit"] == "closed"


@pytest.mark.asyncio
async def test_usage_status_includes_vision_paid_budget_only_when_enabled(
        tmp_path) -> None:
    router.reset_router()
    plain = router.init_router(make_config(tmp_path, ["mock"]))
    assert "vision_paid" not in await plain.usage_status()
    router.reset_router()
    paid = router.init_router(make_config(tmp_path, ["mock"],
                                          allow_vision_paid=True,
                                          vision_paid_daily_cap_usd=1.0))
    out = await paid.usage_status()
    assert out["vision_paid"]["cap_usd"] == 1.0
    assert out["vision_paid"]["exhausted"] is False


@pytest.mark.asyncio
async def test_usage_status_never_leaks_keys(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "gsk_STATUSMUSTNOTLEAKTHIS0123456789")
    cfg = make_config(tmp_path, ["mock"])
    router.reset_router()
    rt = router.init_router(cfg)
    await rt.chat([{"role": "user", "content": "hi"}])
    out = await rt.usage_status()
    blob = json.dumps(out)
    assert "STATUSMUSTNOTLEAKTHIS" not in blob
    assert "Bearer " not in blob


@pytest.mark.asyncio
async def test_module_facade_usage_status(tmp_path) -> None:
    cfg = make_config(tmp_path, ["mock"])
    router.reset_router()
    router.init_router(cfg)
    out = await router.usage_status()            # what brain-core will import
    assert set(out) >= {"window_hours", "calls", "tokens", "by_provider",
                        "by_purpose", "errors", "providers"}


# --------------------------------------------------------------------------- #
# F-4 (AUDIT-2026-10-07): compact headroom accessor for the orb menu
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_rate_headroom_shape_and_facade(tmp_path) -> None:
    cfg = make_config(tmp_path, ["mock"], allow_vision_paid=True,
                      vision_paid_daily_cap_usd=1.0, vision_paid_total_cap_usd=10.0)
    router.reset_router()
    rt = router.init_router(cfg)
    await rt.chat([{"role": "user", "content": "hi"}])   # consumes 1 RPM slot

    headroom = router.rate_headroom()               # module facade (sync, no I/O)
    mock_block = headroom["providers"]["mock"]
    assert set(mock_block) == {"rpm_headroom", "tpm_headroom", "cooldown_s",
                               "circuit"}
    assert mock_block["rpm_headroom"] == 999        # cap 1000 - 1 used
    assert mock_block["tpm_headroom"] > 0
    assert mock_block["circuit"] == "closed"
    paid_block = headroom["vision_paid"]
    assert paid_block == {"today_usd": 0.0, "day_cap_usd": 1.0, "total_usd": 0.0,
                          "total_cap_usd": 10.0, "exhausted": False,
                          "total_exhausted": False, "ledger_broken": False}
    # /status rides the same accessor (brain-core already wires usage_status)
    status = await rt.usage_status()
    assert status["headroom"] == headroom


@pytest.mark.asyncio
async def test_rate_headroom_without_paid_slot(tmp_path) -> None:
    cfg = make_config(tmp_path, ["mock"], allow_vision_paid=False)
    router.reset_router()
    rt = router.init_router(cfg)
    headroom = rt.rate_headroom()
    assert "vision_paid" not in headroom            # slot disabled → no block
    assert "mock" in headroom["providers"]


# --------------------------------------------------------------------------- #
# AUD-27: usage.jsonl tail read must be BOUNDED (byte-capped), never whole-file
# --------------------------------------------------------------------------- #
def _recent(marker: str) -> str:
    from datetime import datetime as dt, timezone as tz
    return json.dumps({
        "timestamp": dt.now(tz.utc).isoformat(), "provider": marker,
        "model": "m", "tokens_input": 1, "tokens_output": 1,
        "latency_ms": 1.0, "outcome": "success", "task_kind": "chat",
        "error_code": None,
    })


def test_usage_read_is_byte_bounded_and_drops_torn_window_head(tmp_path) -> None:
    from brain.router.status import read_usage_events
    path = tmp_path / "usage.jsonl"
    lines = [_recent("HEAD")] + [_recent(f"FILL{i}") for i in range(10)] + \
            [_recent("TAIL")]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    size = path.stat().st_size
    # window ends exactly 10 bytes INTO the last filler line → that line is a
    # torn fragment at the window start and must be dropped
    max_bytes = len(lines[-1]) + 11
    assert size > max_bytes
    events = read_usage_events(path, max_bytes=max_bytes)
    providers = [e["provider"] for e in events]
    assert providers == ["TAIL"]                     # head excluded, torn line dropped
    for e in events:                                 # everything returned parses
        assert e["outcome"] in ("success", "failed", "retry", "unavailable")


def test_usage_read_default_bound_never_loads_a_growing_file(tmp_path) -> None:
    from brain.router.status import TAIL_BYTES, read_usage_events
    path = tmp_path / "usage.jsonl"
    head = _recent("HEAD-ANCHOR")
    # pad each filler so the file crosses TAIL_BYTES (512 KiB) quickly
    filler = [_recent("FILLER" + "x" * 700) for _ in range(700)]
    tail = _recent("TAIL-ANCHOR")
    path.write_text(head + "\n" + "\n".join(filler) + "\n" + tail + "\n",
                    encoding="utf-8")
    assert path.stat().st_size > TAIL_BYTES
    events = read_usage_events(path)                       # DEFAULT bound
    providers = {e["provider"] for e in events}
    assert "HEAD-ANCHOR" not in providers      # whole-file read would include it
    assert "TAIL-ANCHOR" in providers
    # and we never return more than the line cap
    assert len(events) <= 2000


def test_small_files_keep_old_behaviour(tmp_path) -> None:
    from brain.router.status import read_usage_events
    path = tmp_path / "usage.jsonl"
    path.write_text(_recent("A") + "\nnot json\n" + _recent("B") + "\n",
                    encoding="utf-8")
    events = read_usage_events(path)
    assert [e["provider"] for e in events] == ["A", "B"]

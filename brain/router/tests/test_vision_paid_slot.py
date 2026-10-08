"""Vision-only paid slot (USER APPROVAL 2026-10-06, docs/PAID_USAGE.md).

Scope under test — none of it negotiable:
  1. gate `providers.allow_vision_paid` unlocks ONE Go-tier model for the
     `vision()` purpose ONLY (chat/tools/STT never see the paid endpoint);
  2. discovery by capability — live `/models`, vision-hinted id, never a
     hardcoded id and never a guess (score 0 → E_OFFLINE/no_model, no call);
  3. `providers.vision_paid_daily_cap_usd` hard stop → vision() raises
     E_OFFLINE + coord attention "vision daily cap hit" (once per day);
  4. mock only — no live paid calls in tests (AGENT_RULES §7).
"""
from __future__ import annotations

import json

import pytest

import brain.router as router
from brain.router import RouterError
from brain.router.spend import DailySpend, estimate_cost_usd
from brain.router.tests.conftest import make_config

PAID_VISION_ID = "opencode-go/deepseek-v4-flash-vision-exp"  # from live discovery


def _image() -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _paid_cfg(tmp_path, *, groq_url="http://127.0.0.1:9",
              zen_url="http://127.0.0.1:9", go_url="http://127.0.0.1:9",
              allow_vision_paid=True, cap=1.00, **kw):
    return make_config(
        tmp_path, kw.pop("chain", ["groq"]),
        groq_url=groq_url, zen_url=zen_url, go_url=go_url,
        allow_vision_paid=allow_vision_paid,
        vision_paid_daily_cap_usd=cap,
        **kw,
    )


@pytest.fixture
def attention(monkeypatch):
    """Capture coord attention posts instead of notifying the human."""
    calls: list[str] = []
    monkeypatch.setattr("brain.router.spend.notify_attention",
                        lambda text: calls.append(text))
    return calls


def _spend_state(tmp_path) -> dict:
    """Aggregate the append-only ledger (SEC-8): call entries only."""
    path = tmp_path / "run" / "vision_paid_ledger.jsonl"
    if not path.exists():
        return {}
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            events.append(json.loads(line))
    calls = [e for e in events if e.get("kind") == "call"]
    return {"usd": round(sum(float(e.get("usd") or 0.0) for e in calls), 6),
            "calls": len(calls),
            "models": [e.get("model") for e in calls],
            "events": events}


# --------------------------------------------------------------------------- #
# 1. gate: vision purpose ONLY
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_paid_slot_serves_vision_only(tmp_path, make_server, keys,
                                            attention) -> None:
    free = make_server(models=[{"id": "allam-2-7b"},
                               {"id": "whisper-large-v3"}], free_suffix=False)
    paid = make_server(models=[{"id": "some-text-model"},
                               {"id": PAID_VISION_ID}], free_suffix=False)
    cfg = _paid_cfg(tmp_path, groq_url=free.url, go_url=paid.url)
    router.reset_router()
    rt = router.init_router(cfg)

    out = await rt.vision(_image(), "what is on screen?")
    assert out["provider"] == "go_vision"
    assert "vision" in out["model"]                    # discovered, not hardcoded
    assert len(paid.chat_requests) == 1                # exactly one paid call
    assert len(free.chat_requests) == 0                # free chain had no vision
    # the image really went to the paid endpoint (cloud_temp §7 exception)
    assert b"image_url" in paid.chat_requests[0]["body"]
    # …and it was charged to the daily budget
    state = _spend_state(tmp_path)
    assert state["usd"] > 0 and state["calls"] == 1
    assert PAID_VISION_ID in state["models"]
    assert attention == []                             # cap NOT hit → no ping


@pytest.mark.asyncio
async def test_chat_and_stt_never_touch_paid_endpoint(tmp_path, make_server,
                                                      keys, attention) -> None:
    free = make_server(models=[{"id": "allam-2-7b"},
                               {"id": "whisper-large-v3"}], free_suffix=False)
    paid = make_server(models=[{"id": PAID_VISION_ID}], free_suffix=False)
    cfg = _paid_cfg(tmp_path, groq_url=free.url, go_url=paid.url)
    router.reset_router()
    rt = router.init_router(cfg)

    chat = await rt.chat([{"role": "user", "content": "hi"}])
    assert chat["provider"] == "groq"
    stt = await rt.transcribe(b"RIFF" + b"\x00" * 64)
    assert stt["text"]
    assert paid.requests == []                        # ZERO paid egress for chat/STT

    vision = await rt.vision(_image(), "q")           # only now the slot opens
    assert vision["provider"] == "go_vision"
    assert _spend_state(tmp_path)["calls"] == 1

    # chat chain itself never even lists the paid provider
    assert "go_vision" not in [p.name for p in rt._chain()]
    assert "go_vision" in [p.name for p in rt._vision_chain()]


@pytest.mark.asyncio
async def test_slot_disabled_by_config_is_full_noop(tmp_path, make_server, keys,
                                                    attention) -> None:
    free = make_server(models=[{"id": "allam-2-7b"}], free_suffix=False)
    paid = make_server(models=[{"id": PAID_VISION_ID}], free_suffix=False)
    cfg = _paid_cfg(tmp_path, groq_url=free.url, go_url=paid.url,
                    allow_vision_paid=False)
    router.reset_router()
    rt = router.init_router(cfg)
    with pytest.raises(RouterError) as exc:
        await rt.vision(_image(), "q")
    assert exc.value.code == "E_OFFLINE"
    assert paid.requests == []                        # disabled → not even discovery
    assert not (tmp_path / "run" / "vision_paid_daily.json").exists()


# --------------------------------------------------------------------------- #
# 2. discovery by capability — never hardcoded, never a guess
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_no_vision_capability_means_no_paid_call(tmp_path, make_server,
                                                       keys, attention) -> None:
    free = make_server(models=[{"id": "allam-2-7b"}], free_suffix=False)
    paid = make_server(models=[{"id": "opencode-go/gpt-6-sol"},
                               {"id": "opencode-go/mimo-v2.5"}], free_suffix=False)
    cfg = _paid_cfg(tmp_path, groq_url=free.url, go_url=paid.url)
    router.reset_router()
    rt = router.init_router(cfg)
    with pytest.raises(RouterError) as exc:
        await rt.vision(_image(), "q")
    assert exc.value.code == "E_OFFLINE"              # no_model everywhere
    assert paid.chat_requests == []                   # discovery happened, NO spend
    assert not _spend_state(tmp_path)                 # nothing was charged
    assert attention == []                            # not a cap event


@pytest.mark.asyncio
async def test_paid_model_choice_follows_live_discovery(tmp_path, make_server,
                                                        keys, attention) -> None:
    """Same slot, different discovered id → the router uses what /models said."""
    free = make_server(models=[{"id": "allam-2-7b"}], free_suffix=False)
    paid = make_server(models=[{"id": "vendor/some-vision-model-2026"}],
                       free_suffix=False)
    cfg = _paid_cfg(tmp_path, groq_url=free.url, go_url=paid.url)
    router.reset_router()
    rt = router.init_router(cfg)
    out = await rt.vision(_image(), "q")
    assert out["model"] == "vendor/some-vision-model-2026"


# --------------------------------------------------------------------------- #
# 3. daily cap: hard stop + coord attention
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_cap_exhausted_refuses_paid_slot_with_e_budget(
        tmp_path, make_server, keys, attention) -> None:
    free = make_server(models=[{"id": "allam-2-7b"}], free_suffix=False)
    paid = make_server(models=[{"id": PAID_VISION_ID}], free_suffix=False)
    cfg = _paid_cfg(tmp_path, groq_url=free.url, go_url=paid.url, cap=0.0)
    router.reset_router()
    rt = router.init_router(cfg)
    with pytest.raises(RouterError) as exc:
        await rt.vision(_image(), "q")
    # SEC-8: hard refusal with the budget code (was E_OFFLINE pre-audit)
    assert exc.value.code == "E_BUDGET"
    assert exc.value.retryable is False               # fatal until the reset
    assert exc.value.reason == "vision_paid_cap"
    assert isinstance(exc.value.spoken, str)          # spoken-friendly detail
    assert "cap" in (exc.value.spoken or "").lower()
    assert paid.requests == []                        # refused BEFORE any call
    assert len(attention) == 1                        # coord attention posted
    assert "vision daily cap hit" in attention[0]


@pytest.mark.asyncio
async def test_cap_crossing_charges_then_stops_further_spend(
        tmp_path, make_server, keys, attention) -> None:
    free = make_server(models=[{"id": "allam-2-7b"}], free_suffix=False)
    paid = make_server(models=[{"id": PAID_VISION_ID}], free_suffix=False)
    # cap far below one call's estimated cost → first call crosses it
    cfg = _paid_cfg(tmp_path, groq_url=free.url, go_url=paid.url, cap=0.000001)
    router.reset_router()
    rt = router.init_router(cfg)

    first = await rt.vision(_image(), "q")
    assert first["provider"] == "go_vision"
    assert _spend_state(tmp_path)["usd"] >= 0.000001  # now exhausted

    with pytest.raises(RouterError) as exc:
        await rt.vision(_image(), "q again")
    assert exc.value.code == "E_BUDGET"
    assert exc.value.reason == "vision_paid_cap"
    assert len(paid.chat_requests) == 1               # second call never went out
    assert len(attention) == 1                        # alerted ONCE per day

    with pytest.raises(RouterError):
        await rt.vision(_image(), "q third")
    assert len(attention) == 1                        # still once per day


@pytest.mark.asyncio
async def test_cap_stops_paid_but_free_still_serves(tmp_path, make_server, keys,
                                                    attention) -> None:
    """The cap only gates the PAID slot — free vision (if any) keeps working."""
    free = make_server(models=[{"id": "tiny-vision-8b"}], free_suffix=False)
    paid = make_server(models=[{"id": PAID_VISION_ID}], free_suffix=False)
    cfg = _paid_cfg(tmp_path, groq_url=free.url, go_url=paid.url, cap=0.0)
    router.reset_router()
    rt = router.init_router(cfg)
    out = await rt.vision(_image(), "q")
    assert out["provider"] == "groq"                  # free first, cap irrelevant
    assert paid.requests == []


@pytest.mark.asyncio
async def test_reported_provider_cost_wins_over_estimate(tmp_path, make_server,
                                                         keys, attention) -> None:
    free = make_server(models=[{"id": "allam-2-7b"}], free_suffix=False)
    paid = make_server(models=[{"id": PAID_VISION_ID}], free_suffix=False)
    paid.chat_script.append({
        "cost": 0.02,
        "choices": [{"message": {"content": "vision answer"},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    })
    cfg = _paid_cfg(tmp_path, groq_url=free.url, go_url=paid.url, cap=1.0)
    router.reset_router()
    rt = router.init_router(cfg)
    await rt.vision(_image(), "q")
    assert _spend_state(tmp_path)["usd"] == 0.02      # provider's own number


@pytest.mark.asyncio
async def test_health_exposes_paid_budget(tmp_path, make_server, keys,
                                          attention) -> None:
    free = make_server(models=[{"id": "allam-2-7b"}], free_suffix=False)
    paid = make_server(models=[{"id": PAID_VISION_ID}], free_suffix=False)
    cfg = _paid_cfg(tmp_path, groq_url=free.url, go_url=paid.url, cap=1.0)
    router.reset_router()
    rt = router.init_router(cfg)
    out = await rt.health()
    assert "go_vision" in out["providers"]            # slot is part of vision health
    budget = out["vision_paid"]
    assert budget["cap_usd"] == 1.0
    assert budget["spent_usd"] == 0.0
    assert budget["exhausted"] is False


# --------------------------------------------------------------------------- #
# 4. spend accounting units
# --------------------------------------------------------------------------- #
def test_estimate_cost_prefers_reported_then_tokens() -> None:
    assert estimate_cost_usd({"input": 999, "output": 999}, reported_usd=0.03) == 0.03
    tokens = estimate_cost_usd({"input": 1_000_000, "output": 1_000_000},
                               {"input": 1.0, "output": 2.0})
    assert tokens == 3.0                               # 1 in + 2 out, USD
    assert estimate_cost_usd(None) >= 0.0              # never raises


def test_daily_spend_resets_on_new_date(tmp_path) -> None:
    path = tmp_path / "vision_paid_daily.json"
    path.write_text(json.dumps({"date": "2000-01-01", "usd": 9.99,
                                "calls": 7, "alerted": True}), encoding="utf-8")
    spend = DailySpend(path, cap_usd=1.0)
    assert spend.spent_usd == 0.0                      # old date → fresh budget
    assert spend.exhausted is False
    assert spend.alerted_today is False
    spend.record(0.5, "m")
    assert spend.spent_usd == 0.5
    assert spend.exhausted is False
    total, crossed = spend.record(0.6, "m")
    assert total == 1.1 and crossed is True
    assert spend.exhausted is True
    assert spend.snapshot()["cap_usd"] == 1.0


# --------------------------------------------------------------------------- #
# Bug A regression (BUGS-WAVE2.md): Go endpoint needs x-opencode-session
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_go_vision_requests_carry_session_header(tmp_path, make_server,
                                                       keys, attention) -> None:
    """Regression for Bug A: missing `x-opencode-session` → HTTP 400
    MissingSessionID killed every LIVE vision call (in-process probe worked,
    WS path failed). EVERY request to the Go endpoint — discovery AND
    completion — must carry it, plus the httputil User-Agent (Cloudflare)."""
    free = make_server(models=[{"id": "allam-2-7b"}], free_suffix=False)
    paid = make_server(models=[{"id": PAID_VISION_ID}], free_suffix=False)
    cfg = _paid_cfg(tmp_path, groq_url=free.url, go_url=paid.url)
    router.reset_router()
    rt = router.init_router(cfg)

    out = await rt.vision(_image(), "what am I looking at?")
    assert out["provider"] == "go_vision"
    await rt.health()                                   # hits /models on both

    assert paid.requests, "paid endpoint must have been called"
    session_ids = set()
    for req in paid.requests:
        headers = req["headers"]
        session = headers.get("x-opencode-session", "")
        assert session.startswith("raphael-brain-"), (
            f"missing x-opencode-session on {req['method']} {req['path']}")
        assert "raphael-router" in headers.get("user-agent", ""), (
            "missing router User-Agent (Cloudflare blocks the urllib default)")
        session_ids.add(session)
    assert len(session_ids) == 1, "session id must be stable per process"
    # the header is Go-specific — free providers must not send it
    assert free.requests
    assert all("x-opencode-session" not in r["headers"] for r in free.requests)

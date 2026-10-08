"""Wave 5H SEC-8: spend caps enforced IN CODE — ledger tests.

Maps 1:1 to the audit's required scenarios:
  - simulated restart mid-day        → enforcement reads the persisted ledger
  - concurrent calls racing the cap  → serialized admission, exactly one call
  - clock rollover                   → daily resets, all-time ceiling persists
  - malformed usage response         → charged the conservative floor, never 0
  - global ceiling                   → E_BUDGET / vision_paid_total_cap
  - ledger write failure             → FAIL CLOSED (E_BUDGET / ledger_unwritable)

All mock-only: no network beyond 127.0.0.1, no live paid calls, stack untouched.
"""
from __future__ import annotations

import asyncio
import json

import pytest

import brain.router as router
from brain.router import RouterError
from brain.router.spend import DailySpend, LEDGER_FILENAME, estimate_cost_usd
from brain.router.tests.conftest import make_config

PAID_VISION_ID = "opencode-go/deepseek-v4-flash-vision-exp"
IMAGE = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _paid_cfg(tmp_path, *, free_url="http://127.0.0.1:9",
              paid_url="http://127.0.0.1:9", cap=1.0, total=10.0, **kw):
    return make_config(tmp_path, ["groq"], groq_url=free_url, zen_url=free_url,
                       go_url=paid_url, allow_vision_paid=True,
                       vision_paid_daily_cap_usd=cap,
                       vision_paid_total_cap_usd=total, **kw)


def _ledger(tmp_path):
    return tmp_path / "run" / LEDGER_FILENAME


def _seed_ledger(tmp_path, entries):
    path = _ledger(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for entry in entries:
            fh.write(json.dumps(entry) + "\n")
    return path


def _attention(monkeypatch):
    calls = []
    monkeypatch.setattr("brain.router.spend.notify_attention",
                        lambda text: calls.append(text))
    return calls


def _paid_calls(paid):
    return [r for r in paid.requests if r["path"].endswith("/chat/completions")]


# --------------------------------------------------------------------------- #
# 1. restart mid-day: enforcement survives the process
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_restart_midday_reads_persisted_ledger(tmp_path, make_server,
                                                     keys, monkeypatch) -> None:
    from datetime import date
    today = date.today().isoformat()
    _seed_ledger(tmp_path, [
        {"kind": "call", "date": today, "usd": 0.75, "model": PAID_VISION_ID},
        {"kind": "call", "date": today, "usd": 0.40, "model": PAID_VISION_ID},
    ])                                          # 1.15 >= 1.00 daily cap
    free = make_server(models=[{"id": "allam-2-7b"}], free_suffix=False)
    paid = make_server(models=[{"id": PAID_VISION_ID}], free_suffix=False)
    attention = _attention(monkeypatch)
    cfg = _paid_cfg(tmp_path, free_url=free.url, paid_url=paid.url, cap=1.0)

    router.reset_router()
    rt = router.init_router(cfg)                # "restarted" process
    assert rt._vision_spend.spent_usd == 1.15    # pre-crash spend is visible
    with pytest.raises(RouterError) as exc:
        await rt.vision(IMAGE, "q")
    assert exc.value.code == "E_BUDGET"
    assert exc.value.reason == "vision_paid_cap"
    assert paid.requests == []                   # refused BEFORE any paid call
    assert attention and "vision daily cap hit" in attention[0]


# --------------------------------------------------------------------------- #
# 2. concurrent calls racing the cap
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_concurrent_calls_cannot_race_the_cap(tmp_path, make_server,
                                                    keys, monkeypatch) -> None:
    free = make_server(models=[{"id": "allam-2-7b"}], free_suffix=False)
    paid = make_server(models=[{"id": PAID_VISION_ID}], free_suffix=False)
    attention = _attention(monkeypatch)
    # cap below one call's estimated cost → the FIRST admitted call exhausts it
    cfg = _paid_cfg(tmp_path, free_url=free.url, paid_url=paid.url, cap=0.000001)
    router.reset_router()
    rt = router.init_router(cfg)

    results = await asyncio.gather(
        *[rt.vision(IMAGE, f"q{i}") for i in range(5)],
        return_exceptions=True)
    ok = [r for r in results if isinstance(r, dict)]
    refusals = [r for r in results if isinstance(r, RouterError)]
    assert len(ok) == 1                          # serialized admission → exactly 1
    assert len(refusals) == 4
    assert all(r.code == "E_BUDGET" for r in refusals)
    assert len(_paid_calls(paid)) == 1           # one paid request reached the wire
    events = [json.loads(l) for l in
              _ledger(tmp_path).read_text().splitlines() if l.strip()]
    calls = [e for e in events if e.get("kind") == "call"]
    assert len(calls) == 1                       # ledger agrees: one charge
    assert attention                              # ceiling crossed → attention


# --------------------------------------------------------------------------- #
# 3. clock rollover: daily resets, all-time ceiling persists
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_clock_rollover_keeps_all_time_ceiling(tmp_path, make_server,
                                                     keys, monkeypatch) -> None:
    from datetime import date, timedelta
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    _seed_ledger(tmp_path, [
        {"kind": "call", "date": yesterday, "usd": 5.0, "model": PAID_VISION_ID},
        {"kind": "call", "date": yesterday, "usd": 5.5, "model": PAID_VISION_ID},
    ])                                          # 10.5 total, 0 today
    free = make_server(models=[{"id": "allam-2-7b"}], free_suffix=False)
    paid = make_server(models=[{"id": PAID_VISION_ID}], free_suffix=False)
    attention = _attention(monkeypatch)
    cfg = _paid_cfg(tmp_path, free_url=free.url, paid_url=paid.url,
                    cap=1.0, total=10.0)
    router.reset_router()
    rt = router.init_router(cfg)

    spend = rt._vision_spend
    assert spend.spent_usd == 0.0                # fresh daily budget
    assert round(spend.total_usd, 2) == 10.5      # history persists
    with pytest.raises(RouterError) as exc:      # global ceiling already blown
        await rt.vision(IMAGE, "q")
    assert exc.value.code == "E_BUDGET"
    assert exc.value.reason == "vision_paid_total_cap"
    assert paid.requests == []                   # still no paid call
    assert attention and "ceiling" in attention[0]


# --------------------------------------------------------------------------- #
# 4. malformed usage response → conservative floor, never $0
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_malformed_usage_response_charges_the_floor(tmp_path, make_server,
                                                          keys, monkeypatch) -> None:
    free = make_server(models=[{"id": "allam-2-7b"}], free_suffix=False)
    paid = make_server(models=[{"id": PAID_VISION_ID}], free_suffix=False)
    paid.chat_script.append({                    # cost unparseable, no usage
        "cost": "not-a-number",   # unparseable → must fall back conservatively
        "choices": [{"message": {"content": "vision answer"},
                     "finish_reason": "stop"}],
    })
    _attention(monkeypatch)
    cfg = _paid_cfg(tmp_path, free_url=free.url, paid_url=paid.url, cap=1.0)
    router.reset_router()
    rt = router.init_router(cfg)
    out = await rt.vision(IMAGE, "q")
    assert out["provider"] == "go_vision"
    events = [json.loads(l) for l in
              _ledger(tmp_path).read_text().splitlines() if l.strip()]
    calls = [e for e in events if e.get("kind") == "call"]
    assert len(calls) == 1
    assert calls[0]["usd"] == 0.005              # configured floor, not 0.0


def test_estimate_never_returns_zero_when_floor_given() -> None:
    assert estimate_cost_usd(None, floor_usd=0.005) == 0.005
    assert estimate_cost_usd({"input": 0, "output": 0}, floor_usd=0.005) == 0.005
    assert estimate_cost_usd({}, reported_usd="garbage",
                             floor_usd=0.005) == 0.005
    assert estimate_cost_usd({"input": 1_000_000}, floor_usd=0.005,
                             price_per_mtok={"input": 1.0, "output": 1.0}) == 1.0


# --------------------------------------------------------------------------- #
# 5. ledger write failure → FAIL CLOSED
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_ledger_write_failure_fails_closed(tmp_path, make_server, keys,
                                                 monkeypatch) -> None:
    free = make_server(models=[{"id": "allam-2-7b"}], free_suffix=False)
    paid = make_server(models=[{"id": PAID_VISION_ID}], free_suffix=False)
    attention = _attention(monkeypatch)
    (tmp_path / "run").write_text("i am a file, not a directory", encoding="utf-8")
    cfg = _paid_cfg(tmp_path, free_url=free.url, paid_url=paid.url)
    router.reset_router()
    rt = router.init_router(cfg)

    # first call: send happens, charge cannot be persisted → refuse loudly
    with pytest.raises(RouterError) as exc:
        await rt.vision(IMAGE, "q")
    assert exc.value.code == "E_BUDGET"
    assert exc.value.reason == "ledger_unwritable"
    assert len(_paid_calls(paid)) == 1
    assert attention and "write FAILED" in attention[0]
    # every later call fails CLOSED before touching the provider
    with pytest.raises(RouterError) as exc2:
        await rt.vision(IMAGE, "q again")
    assert exc2.value.code == "E_BUDGET"
    assert len(_paid_calls(paid)) == 1            # unchanged: pre-flight refusal
    assert rt._vision_spend.broken is True        # stays fail-closed until the
    # FS recovers AND a fresh load (init/record) proves the ledger writable again


# --------------------------------------------------------------------------- #
# E_BUDGET shape + status exposure
# --------------------------------------------------------------------------- #
def test_e_budget_is_fatal_and_spoken() -> None:
    from brain.router.errors import FATAL_CODES, RETRYABLE_CODES, SPOKEN_CODES
    err = RouterError("cap", code="E_BUDGET", reason="vision_paid_cap",
                      detail="Vision daily cap reached.")
    assert "E_BUDGET" in FATAL_CODES
    assert "E_BUDGET" not in RETRYABLE_CODES      # auto-retry cannot help
    assert "E_BUDGET" in SPOKEN_CODES
    assert err.retryable is False
    assert err.spoken == "Vision daily cap reached."


@pytest.mark.asyncio
async def test_status_exposes_ledger_and_headroom(tmp_path, keys) -> None:
    cfg = _paid_cfg(tmp_path)
    router.reset_router()
    rt = router.init_router(cfg)
    status = await rt.usage_status()
    paid_block = status["vision_paid"]
    assert paid_block["total_cap_usd"] == 10.0
    assert paid_block["ledger_broken"] is False
    assert paid_block["ledger"].endswith(LEDGER_FILENAME)
    headroom = status["headroom"]                 # F-4 rides the same accessor
    assert headroom["vision_paid"]["total_usd"] == paid_block["total_usd"]
    assert headroom["providers"]["groq"]["rpm_headroom"] <= 1000

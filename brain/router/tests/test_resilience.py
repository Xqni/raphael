"""Wave 4: provider failure-injection resilience suite (mock HTTP only).

Storms + transitions the live stack will eventually see, injected locally:
429 storms with Retry-After, 5xx storms that OPEN the breaker and then
half-open recovery, network drops (connection refused), exhaustion code
precedence per PROTOCOL §10, and failover ORDERING (free chain order is
guaranteed, paid slot last).

The live stack stays untouched (AGENTS rule from wave_open: stack is UP —
no servers spawned here, everything on 127.0.0.1 ephemeral ports).
"""
from __future__ import annotations

import asyncio

import pytest

import brain.router as router
from brain.router import RouterError
from brain.router.core import CircuitBreaker
from brain.router.tests.conftest import make_config


def _msgs(text: str = "hello"):
    return [{"role": "user", "content": text}]


def _cfg(tmp_path, chain, *, groq_url="http://127.0.0.1:9",
         zen_url="http://127.0.0.1:9", **kw):
    return make_config(tmp_path, chain, groq_url=groq_url, zen_url=zen_url, **kw)


def _router(tmp_path, cfg):
    router.reset_router()
    return router.init_router(cfg)


# --------------------------------------------------------------------------- #
# 429 storm
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_429_storm_backs_off_then_fails_over_in_order(
        tmp_path, make_server, keys) -> None:
    groq = make_server(free_suffix=False)
    zen = make_server(models=[{"id": "mimo-flash"}], free_suffix=True)
    groq.chat_script.extend([
        (429, {"Retry-After": "0.01"}, b'{"error":"slow down"}'),
        (429, {"Retry-After": "0.01"}, b'{"error":"slow down"}'),
    ])
    cfg = _cfg(tmp_path, ["groq", "zen_free"], groq_url=groq.url,
               zen_url=zen.url, max_retries=1)
    _router(tmp_path, cfg)
    out = await router.chat(_msgs())
    assert out["provider"] == "zen_free"              # storm → failover
    assert len(groq.chat_requests) == 2               # initial + one retry
    assert len(zen.chat_requests) == 1
    # ORDER: every groq attempt finished before the zen attempt started
    assert max(r["ts"] for r in groq.chat_requests) < min(
        r["ts"] for r in zen.chat_requests)


@pytest.mark.asyncio
async def test_long_retry_after_storm_marks_cooldown_without_stalling(
        tmp_path, make_server, keys) -> None:
    groq = make_server(free_suffix=False)
    zen = make_server(models=[{"id": "mimo-flash"}], free_suffix=True)
    groq.chat_script.append((429, {"Retry-After": "90"}, b""))
    cfg = _cfg(tmp_path, ["groq", "zen_free"], groq_url=groq.url,
               zen_url=zen.url)
    rt = _router(tmp_path, cfg)
    out = await router.chat(_msgs())
    assert out["provider"] == "zen_free"
    assert len(groq.chat_requests) == 1               # no 90 s stall
    assert rt._stats["groq"].cooldown_until > 0
    out2 = await router.chat(_msgs())                 # cooldown window: skip groq
    assert out2["provider"] == "zen_free"
    assert len(groq.chat_requests) == 1               # still one — skipped, not retried


# --------------------------------------------------------------------------- #
# 5xx storm → breaker opens → half-open probe → recovery
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_5xx_storm_opens_breaker_then_half_open_recovery(
        tmp_path, make_server, keys) -> None:
    groq = make_server(free_suffix=False)
    zen = make_server(models=[{"id": "mimo-flash"}], free_suffix=True)
    groq.chat_script.extend([(500, {}, b"boom"), (500, {}, b"boom")])
    cfg = _cfg(tmp_path, ["groq", "zen_free"], groq_url=groq.url,
               zen_url=zen.url, max_retries=0)
    rt = _router(tmp_path, cfg)
    # fast, deterministic breaker for the test (2 failures opens, 1 success closes)
    rt._stats["groq"].circuit = CircuitBreaker(
        failure_threshold=2, success_threshold=1, timeout_s=0.05)

    first = await router.chat(_msgs())
    assert first["provider"] == "zen_free"            # groq failed → failover
    assert rt._stats["groq"].circuit.state.value == "closed"
    second = await router.chat(_msgs())
    assert second["provider"] == "zen_free"
    assert rt._stats["groq"].circuit.state.value == "open"
    assert len(groq.chat_requests) == 2

    third = await router.chat(_msgs())
    assert third["provider"] == "zen_free"
    assert len(groq.chat_requests) == 2               # OPEN → zero new attempts

    await asyncio.sleep(0.08)                         # cooldown elapses
    fourth = await router.chat(_msgs())               # half-open probe, groq healthy now
    assert fourth["provider"] == "groq"               # recovered → served first again
    assert len(groq.chat_requests) == 3
    assert rt._stats["groq"].circuit.state.value == "closed"
    fifth = await router.chat(_msgs())
    assert fifth["provider"] == "groq"
    assert len(groq.chat_requests) == 4


@pytest.mark.asyncio
async def test_non_call_failures_do_not_trip_breaker(tmp_path, make_server,
                                                     keys) -> None:
    """no_model (capability miss) is a skip, not provider health — the
    breaker must stay CLOSED across many of them."""
    free = make_server(models=[{"id": "allam-2-7b"}], free_suffix=False)
    cfg = _cfg(tmp_path, ["groq"], groq_url=free.url, max_retries=0)
    rt = _router(tmp_path, cfg)
    for _ in range(7):                                # > default threshold of 5
        with pytest.raises(RouterError) as exc:
            await router.vision(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8, "q?")
        assert exc.value.code == "E_OFFLINE"
        assert rt._stats["groq"].circuit.state.value == "closed"
    assert len(free.chat_requests) == 0               # never even tried a chat


# --------------------------------------------------------------------------- #
# network drop (connection refused) — storm + single-point isolation
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_network_drop_after_success_fails_over(tmp_path, make_server,
                                                     keys) -> None:
    groq = make_server(free_suffix=False)
    zen = make_server(models=[{"id": "mimo-flash"}], free_suffix=True)
    cfg = _cfg(tmp_path, ["groq", "zen_free"], groq_url=groq.url,
               zen_url=zen.url, max_retries=0)
    _router(tmp_path, cfg)
    first = await router.chat(_msgs())
    assert first["provider"] == "groq"                # healthy before the drop
    groq.stop()                                       # provider goes away
    second = await router.chat(_msgs())
    assert second["provider"] == "zen_free"           # isolated failure


@pytest.mark.asyncio
async def test_all_providers_down_is_e_offline(tmp_path, make_server, keys) -> None:
    dead = make_server(free_suffix=False)
    dead.stop()
    cfg = _cfg(tmp_path, ["groq"], groq_url=dead.url, max_retries=0)
    _router(tmp_path, cfg)
    with pytest.raises(RouterError) as exc:
        await router.chat(_msgs())
    assert exc.value.code == "E_OFFLINE"
    assert exc.value.retryable is True                # §10: transient
    assert isinstance(exc.value.spoken, str)          # spoken-friendly detail


# --------------------------------------------------------------------------- #
# exhaustion code precedence (PROTOCOL §10)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
@pytest.mark.parametrize("script,max_retries,expect_code,expect_retryable", [
    ([(401, {}, b"bad key")], 0, "E_PROVIDER_AUTH", False),
    ([(429, {"Retry-After": "0.01"}, b"")] * 2, 1, "E_PROVIDER_429", True),
    ([(500, {}, b"boom")] * 2, 1, "E_PROVIDER_5XX", True),
    ([(503, {}, b"down")] * 2, 1, "E_PROVIDER_5XX", True),
])
async def test_exhaustion_maps_to_single_protocol_code(
        tmp_path, make_server, keys, script, max_retries, expect_code,
        expect_retryable) -> None:
    srv = make_server(free_suffix=False)
    srv.chat_script.extend(list(script))
    cfg = _cfg(tmp_path, ["groq"], groq_url=srv.url, max_retries=max_retries)
    _router(tmp_path, cfg)
    with pytest.raises(RouterError) as exc:
        await router.chat(_msgs())
    assert exc.value.code == expect_code
    assert exc.value.retryable is expect_retryable


@pytest.mark.asyncio
async def test_auth_error_is_not_blindly_retried(tmp_path, make_server, keys) -> None:
    """401 = fatal per §10: exactly one attempt, no backoff loop."""
    srv = make_server(free_suffix=False)
    srv.chat_script.append((401, {}, b"bad key"))
    cfg = _cfg(tmp_path, ["groq"], groq_url=srv.url, max_retries=3)
    _router(tmp_path, cfg)
    with pytest.raises(RouterError):
        await router.chat(_msgs())
    assert len(srv.chat_requests) == 1


# --------------------------------------------------------------------------- #
# storm volume: bounded requests under sustained failure
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_sustained_storm_is_bounded_and_never_hangs(
        tmp_path, make_server, keys) -> None:
    """10 consecutive failing calls: per-call attempts stay capped by
    max_retries+1 per provider, and every call returns/raises promptly."""
    groq = make_server(free_suffix=False)
    zen = make_server(models=[{"id": "mimo-flash"}], free_suffix=True)
    groq.chat_script.extend([(500, {}, b"boom")] * 100)
    zen.chat_script.append((500, {}, b"boom"))        # zen fails ONCE too
    cfg = _cfg(tmp_path, ["groq", "zen_free"], groq_url=groq.url,
               zen_url=zen.url, max_retries=1)
    rt = _router(tmp_path, cfg)
    for i in range(10):
        out = await asyncio.wait_for(router.chat(_msgs(f"call {i}")), timeout=10)
        assert out["provider"] == "zen_free"          # zen recovered after its 1 failure
    # BOUNDED by both guards: max_retries caps groq at 2 attempts/call, and the
    # breaker opens after the 5th failed call → groq gets ZERO further attempts
    # (2 attempts x 5 calls = 10, not 20), while zen keeps serving every call
    # (1 failed + 1 recovery on call 1, then one each = 11).
    assert len(groq.chat_requests) == 10
    assert rt._stats["groq"].circuit.state.value == "open"
    assert len(zen.chat_requests) == 11

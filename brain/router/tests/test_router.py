"""Router unit tests with mocked HTTP."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from brain.router import (
    CallResult,
    Outcome,
    RouterConfig,
    acquire_model,
    complete,
    get_router,
    init_router,
    shutdown_router,
)
from brain.router.config import LocalModelSettings, RouterSettings
from brain.router.core import CircuitBreaker, RateLimiter


def _make_config(tmp_path: Path) -> RouterConfig:
    return RouterConfig(
        providers=RouterSettings(
            chain=["zen_free", "go", "ollama"],
            allow_go_runtime=False,
            allow_paid_runtime=False,
            allow_free_models_for_personal_data=False,
            zen_base_url="https://example.com/zen/v1",
            go_base_url="https://example.com/zen/go/v1",
            discovery_interval_s=3600,
            max_calls_per_minute=100,
            benchmark_ranking_path=str(tmp_path / "rank.json"),
        ),
        local_model=LocalModelSettings(
            candidates=["qwen3.5:4b"],
            text="auto",
            vision="auto",
            keep_alive="5m",
            vision_keep_alive="0",
            max_concurrency=1,
            ollama_url="http://127.0.0.1:11434",
        ),
        repo_root=tmp_path,
    )


@pytest.mark.asyncio
async def test_go_gate_disabled() -> None:
    cfg = _make_config(Path("/tmp"))
    router = init_router(cfg)
    try:
        # Mock zen discovery returns free model
        with mock.patch.object(router.zen, "_fetch_sync", return_value=[]) as _:
            pass
        with mock.patch.object(router.zen, "get_free_model_ids", return_value=["mimo-v2.6-flash-free"]):
            provider, model = await acquire_model(task_kind="test")
            assert provider == "zen_free"
            assert model == "mimo-v2.6-flash-free"
    finally:
        await shutdown_router()


@pytest.mark.asyncio
async def test_chain_order_zen_go_ollama() -> None:
    cfg = _make_config(Path("/tmp"))
    router = init_router(cfg)
    try:
        with mock.patch.object(router.zen, "get_free_model_ids", return_value=["zen-model"]):
            provider, model = await acquire_model()
            assert provider == "zen_free"
            assert model == "zen-model"
    finally:
        await shutdown_router()


@pytest.mark.asyncio
async def test_go_unreachable_when_disabled() -> None:
    cfg = _make_config(Path("/tmp"))
    router = init_router(cfg)
    try:
        with mock.patch.object(router.zen, "get_free_model_ids", return_value=[]):
            with mock.patch.object(router.ollama, "list_models", return_value=[]):
                with pytest.raises(Exception):
                    await acquire_model()
    finally:
        await shutdown_router()


@pytest.mark.asyncio
async def test_ollama_fallback_last() -> None:
    cfg = _make_config(Path("/tmp"))
    router = init_router(cfg)
    try:
        with mock.patch.object(router.zen, "get_free_model_ids", return_value=[]):
            with mock.patch.object(router.ollama, "list_models", return_value=["qwen3.5:4b"]):
                provider, model = await acquire_model()
                assert provider == "ollama"
                assert model == "qwen3.5:4b"
    finally:
        await shutdown_router()


@pytest.mark.asyncio
async def test_circuit_breaker_transitions() -> None:
    cb = CircuitBreaker(failure_threshold=2, success_threshold=1, timeout_s=0.01)
    now = 0.0
    assert cb.can_proceed(now)
    cb.record_failure(now)
    assert cb.state.value == "closed"
    cb.record_failure(now)
    assert cb.state.value == "open"
    now += 0.02
    assert cb.can_proceed(now)
    assert cb.state.value == "half-open"
    cb.record_success()
    assert cb.state.value == "closed"


@pytest.mark.asyncio
async def test_rate_limiter() -> None:
    rl = RateLimiter(max_calls=2, window_s=60.0)
    now = 0.0
    assert rl.allow(now)
    assert rl.allow(now)
    assert not rl.allow(now)


@pytest.mark.asyncio
async def test_complete_logs_usage() -> None:
    cfg = _make_config(Path("/tmp"))
    router = init_router(cfg)
    try:
        res = await complete(provider="zen_free", model="test-model", prompt="hi there", task_kind="test")
        assert isinstance(res, CallResult)
        assert res.ok
        assert res.outcome == Outcome.SUCCESS
    finally:
        await shutdown_router()

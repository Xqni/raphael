"""Core router with circuit breakers, rate limits, health checks, and usage logging."""
from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional

from .config import RouterConfig, load_config
from .ollama import OllamaProvider, OllamaUnavailable
from .zen import ZenDiscovery, ZenDiscoveryError

REPO_ROOT = Path(__file__).resolve().parents[2]
USAGE_LOG_PATH = REPO_ROOT / "brain" / "router" / "usage.jsonl"
BENCHMARK_RANKING_PATH = REPO_ROOT / "brain" / "router" / "benchmark_ranking.json"


class Outcome(str, Enum):
    SUCCESS = "success"
    RETRY = "retry"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


class ProviderState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half-open"


@dataclass
class CircuitBreaker:
    failure_threshold: int = 5
    success_threshold: int = 2
    timeout_s: float = 60.0
    failure_count: int = 0
    success_count: int = 0
    state: ProviderState = ProviderState.CLOSED
    opened_at: float = 0.0

    def can_proceed(self, now: float) -> bool:
        if self.state == ProviderState.CLOSED:
            return True
        if self.state == ProviderState.OPEN:
            if now - self.opened_at >= self.timeout_s:
                self.state = ProviderState.HALF_OPEN
                self.success_count = 0
                return True
            return False
        # HALF_OPEN
        return True

    def record_success(self) -> None:
        if self.state == ProviderState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.success_threshold:
                self.state = ProviderState.CLOSED
                self.failure_count = 0
                self.success_count = 0
        elif self.state == ProviderState.CLOSED:
            self.failure_count = 0

    def record_failure(self, now: float) -> None:
        if self.state == ProviderState.HALF_OPEN:
            self.state = ProviderState.OPEN
            self.opened_at = now
            self.failure_count = 0
            self.success_count = 0
            return
        self.failure_count += 1
        if self.failure_count >= self.failure_threshold:
            self.state = ProviderState.OPEN
            self.opened_at = now
            self.success_count = 0


@dataclass
class RateLimiter:
    max_calls: int
    window_s: float
    calls: deque[float] = field(default_factory=deque)

    def allow(self, now: float) -> bool:
        while self.calls and now - self.calls[0] > self.window_s:
            self.calls.popleft()
        if len(self.calls) >= self.max_calls:
            return False
        self.calls.append(now)
        return True


@dataclass
class UsageEvent:
    timestamp: str
    provider: str
    model: str
    tokens_input: int
    tokens_output: int
    latency_ms: float
    outcome: Outcome
    task_kind: str | None = None
    error_code: str | None = None


@dataclass
class CallResult:
    provider: str
    model: str
    ok: bool
    text: str = ""
    tokens_input: int = 0
    tokens_output: int = 0
    latency_ms: float = 0.0
    outcome: Outcome = Outcome.FAILED
    error: str | None = None
    error_code: str | None = None


class ProviderUnavailable(Exception):
    pass


class ProviderError(Exception):
    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class ProviderStats:
    circuit: CircuitBreaker = field(default_factory=CircuitBreaker)
    limiter: RateLimiter | None = None


class Router:
    def __init__(self, config: RouterConfig | None = None) -> None:
        self.config = config or load_config()
        self.zen = ZenDiscovery(
            base_url=self.config.providers.zen_base_url,
            ttl_s=self.config.providers.discovery_interval_s,
        )
        self.ollama = OllamaProvider(base_url=self.config.local_model.ollama_url)
        self._stats: dict[str, ProviderStats] = {}
        self._health_task: asyncio.Task[None] | None = None
        self._running = False
        self._usage_lock = asyncio.Lock()
        USAGE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        # init stats
        for p in ("zen_free", "go", "ollama"):
            limiter = None
            if p == "zen_free":
                limiter = RateLimiter(
                    max_calls=self.config.providers.max_calls_per_minute,
                    window_s=60.0,
                )
            elif p == "go":
                limiter = RateLimiter(max_calls=10, window_s=60.0)
            elif p == "ollama":
                limiter = RateLimiter(max_calls=20, window_s=60.0)
            self._stats[p] = ProviderStats(limiter=limiter)

    def _now(self) -> float:
        return time.monotonic()

    def _utc_now(self) -> datetime:
        return datetime.now(timezone.utc)

    async def _write_usage(self, ev: UsageEvent) -> None:
        line = json.dumps(asdict(ev), ensure_ascii=False)
        async with self._usage_lock:
            await asyncio.to_thread(lambda: USAGE_LOG_PATH.open("a", encoding="utf-8").write(line + "\n"))

    async def _health_loop(self) -> None:
        while self._running:
            await asyncio.sleep(30.0 + (time.monotonic() % 5.0))
            await self.health_check()

    async def start(self) -> None:
        self._running = True
        self._health_task = asyncio.create_task(self._health_loop())

    async def shutdown(self) -> None:
        self._running = False
        if self._health_task:
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass

    async def health_check(self) -> dict[str, bool]:
        res: dict[str, bool] = {}
        try:
            await self.zen.get_models()
            res["zen_free"] = True
        except ZenDiscoveryError:
            res["zen_free"] = False
        res["go"] = bool(self.config.providers.allow_go_runtime)
        res["ollama"] = await self.ollama.health_check()
        return res

    async def acquire_model(self, task_kind: str | None = None) -> tuple[str, str]:
        chain = list(self.config.providers.chain)
        for provider in chain:
            if provider == "go" and not self.config.providers.allow_go_runtime:
                continue
            model = await self._try_acquire(provider)
            if model:
                return provider, model
        raise ProviderUnavailable("All providers exhausted")

    async def _try_acquire(self, provider: str) -> str | None:
        if provider == "zen_free":
            try:
                ids = await self.zen.get_free_model_ids()
                if ids:
                    return ids[0]
                return None
            except ZenDiscoveryError:
                return None
        if provider == "go":
            return "go-reserved"
        if provider == "ollama":
            models = await self.ollama.list_models()
            if models:
                return models[0]
            return None
        return None

    async def complete(
        self,
        provider: str,
        model: str,
        prompt: str | None = None,
        task_kind: str | None = None,
    ) -> CallResult:
        start = self._now()
        now = start
        stats = self._stats.setdefault(provider, ProviderStats())
        if not stats.circuit.can_proceed(now):
            res = CallResult(
                provider=provider,
                model=model,
                ok=False,
                outcome=Outcome.UNAVAILABLE,
                error="circuit open",
                error_code="E_CIRCUIT_OPEN",
            )
            await self._write_usage(
                UsageEvent(
                    timestamp=self._utc_now().isoformat(),
                    provider=provider,
                    model=model,
                    tokens_input=0,
                    tokens_output=0,
                    latency_ms=(self._now() - start) * 1000.0,
                    outcome=res.outcome,
                    task_kind=task_kind,
                    error_code=res.error_code,
                )
            )
            return res
        if stats.limiter and not stats.limiter.allow(now):
            res = CallResult(
                provider=provider,
                model=model,
                ok=False,
                outcome=Outcome.RETRY,
                error="rate limited",
                error_code="E_RATE_LIMIT",
            )
            await self._write_usage(
                UsageEvent(
                    timestamp=self._utc_now().isoformat(),
                    provider=provider,
                    model=model,
                    tokens_input=0,
                    tokens_output=0,
                    latency_ms=(self._now() - start) * 1000.0,
                    outcome=res.outcome,
                    task_kind=task_kind,
                    error_code=res.error_code,
                )
            )
            return res
        try:
            text = f"[{provider}:{model}] response"
            latency_ms = (self._now() - start) * 1000.0
            stats.circuit.record_success()
            res = CallResult(
                provider=provider,
                model=model,
                ok=True,
                text=text,
                tokens_input=len((prompt or "").split()),
                tokens_output=len(text.split()),
                latency_ms=latency_ms,
                outcome=Outcome.SUCCESS,
            )
            await self._write_usage(
                UsageEvent(
                    timestamp=self._utc_now().isoformat(),
                    provider=provider,
                    model=model,
                    tokens_input=res.tokens_input,
                    tokens_output=res.tokens_output,
                    latency_ms=latency_ms,
                    outcome=res.outcome,
                    task_kind=task_kind,
                )
            )
            return res
        except Exception as e:
            stats.circuit.record_failure(self._now())
            latency_ms = (self._now() - start) * 1000.0
            res = CallResult(
                provider=provider,
                model=model,
                ok=False,
                outcome=Outcome.FAILED,
                error=str(e),
                error_code="E_PROVIDER_5XX",
            )
            await self._write_usage(
                UsageEvent(
                    timestamp=self._utc_now().isoformat(),
                    provider=provider,
                    model=model,
                    tokens_input=0,
                    tokens_output=0,
                    latency_ms=latency_ms,
                    outcome=res.outcome,
                    task_kind=task_kind,
                    error_code=res.error_code,
                )
            )
            return res

    async def report_usage(self, event: UsageEvent) -> None:
        await self._write_usage(event)


_router: Router | None = None


def init_router(config: RouterConfig | None = None) -> Router:
    global _router
    if _router is None:
        _router = Router(config)
    return _router


def get_router() -> Router:
    if _router is None:
        return init_router()
    return _router


async def acquire_model(task_kind: str | None = None) -> tuple[str, str]:
    return await get_router().acquire_model(task_kind=task_kind)


async def complete(
    provider: str,
    model: str,
    prompt: str | None = None,
    task_kind: str | None = None,
) -> CallResult:
    return await get_router().complete(provider=provider, model=model, prompt=prompt, task_kind=task_kind)


async def report_usage(event: UsageEvent) -> None:
    await get_router().report_usage(event)


async def shutdown_router() -> None:
    if _router is not None:
        await _router.shutdown()

"""Router facade — `chat / vision / transcribe / health` (INTERFACES §a).

**No lane may call a provider HTTP API directly.** Everything goes through
this package; callers get a plain dict on success or a `RouterError` carrying
a PROTOCOL §10 code on failure — never a crash (INTERFACES §a).

Responsibilities layered here (Wave 2 tasks 1-4):

- **chain failover** — walk `providers.chain` (profile-derived) and serve the
  first provider that can answer; Go/paid gates enforced in code;
- **resilience** — 429/5xx backoff with jitter, `Retry-After` + rate-limit
  header honoring, per-provider RPM/TPM budgets, circuit breakers,
  model-vanished → re-discover once;
- **privacy gates** — Private Mode refusal, foreground-window blocklist for
  vision, secret redaction of every outbound string, no image logging;
- **usage log** — one JSON line per call in `brain/router/usage.jsonl`
  (gitignored runtime data).

Legacy seam (`brain/llm.py`, brain-core's side) keeps working:
`acquire_model()` / `complete()` are still exported with their old shapes.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import random
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable

from . import spend as spend_mod
from .config import RouterConfig, load_config
from .errors import RouterError, ProviderError, ProviderUnavailable, aggregate_code
from .httputil import guess_audio_format, guess_image_mime
from .privacy import (
    blocklist_hit,
    describe_image,
    is_private_mode,
    redact_secrets,
    redact_messages,
)
from .provider import ChatResult, Provider, estimate_input_tokens
from .spend import DailySpend, estimate_cost_usd

log = logging.getLogger("raphael.router")

# --------------------------------------------------------------------------- #
# legacy result types (brain/llm.py + older tests read these shapes)
# --------------------------------------------------------------------------- #


class Outcome(str, Enum):
    SUCCESS = "success"
    RETRY = "retry"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


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
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    finish: str = "stop"
    tokens_input: int = 0
    tokens_output: int = 0
    latency_ms: float = 0.0
    outcome: Outcome = Outcome.FAILED
    error: str | None = None
    error_code: str | None = None


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
            # cooldown with jitter (ARCHITECTURE §4) — ±20% of timeout_s
            jitter = self.timeout_s * 0.2 * random.random()
            if now - self.opened_at >= self.timeout_s - jitter:
                self.state = ProviderState.HALF_OPEN
                self.success_count = 0
                return True
            return False
        return True  # HALF_OPEN lets a probe through

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
    """Sliding-window RPM budget for one provider."""

    max_calls: int
    window_s: float = 60.0
    calls: deque[float] = field(default_factory=deque)

    def allow(self, now: float) -> bool:
        self._prune(now)
        if len(self.calls) >= self.max_calls:
            return False
        self.calls.append(now)
        return True

    def _prune(self, now: float) -> None:
        while self.calls and now - self.calls[0] > self.window_s:
            self.calls.popleft()


@dataclass
class TokenBudget:
    """Sliding-window TPM budget for one provider (estimated + actual usage)."""

    max_tokens: int
    window_s: float = 60.0
    events: deque[tuple[float, int]] = field(default_factory=deque)

    def allow(self, now: float, estimate: int) -> bool:
        self._prune(now)
        used = sum(t for _, t in self.events)
        if used + max(0, estimate) > self.max_tokens:
            return False
        return True

    def record(self, now: float, tokens: int) -> None:
        self.events.append((now, max(0, int(tokens))))
        self._prune(now)

    def _prune(self, now: float) -> None:
        while self.events and now - self.events[0][0] > self.window_s:
            self.events.popleft()


@dataclass
class ProviderStats:
    circuit: CircuitBreaker = field(default_factory=CircuitBreaker)
    limiter: RateLimiter | None = None
    budget: TokenBudget | None = None
    cooldown_until: float = 0.0       # set from rate-limit headers / Retry-After
    last_error: str | None = None


# reasons that mean "skip this provider quietly" (no breaker failure, no retry)
SKIP_REASONS = frozenset({
    "circuit_open",
    "cooldown",
    "local_rpm_budget",
    "local_tpm_budget",
    "missing_key",
    "gated",
    "no_model",
    "chain_exhausted",
    "private_mode",
    "blocked_window",
    "cloud_vision_disabled",
    "stt_not_available",
})

# provider failures worth retrying on the SAME provider before failing over
_RETRYABLE = {"E_OFFLINE", "E_PROVIDER_5XX", "E_PROVIDER_429", "E_TIMEOUT"}

SYSTEM_PROMPT = (
    "You are Raphael, a warm and direct local-first desktop companion "
    "with a female voice, talking with the person at this Windows PC. "
    "Voice-first conversation: plain spoken text only — no markdown, no "
    "lists, no emojis, no code. Match length to the ask: one sentence "
    "for quick answers, a few sentences or a short paragraph when "
    "explaining. Be candid about what you don't know. Never announce "
    "that you are a language model."
)


def build_provider(name: str, config: RouterConfig) -> Provider:
    from .groq import GroqProvider
    from .mock import MockProvider
    from .ollama import OllamaLocalProvider
    from .zen import GoProvider, GoVisionProvider, ZenProvider

    builders: dict[str, Callable[[RouterConfig], Provider]] = {
        "groq": GroqProvider,
        "zen_free": ZenProvider,
        "go": GoProvider,
        "go_vision": GoVisionProvider,
        "ollama": OllamaLocalProvider,
        "mock": MockProvider,
    }
    try:
        return builders[name](config)
    except KeyError as e:
        raise ProviderError(f"unknown provider in chain: {name}", code="E_INTERNAL") from e


class Router:
    def __init__(self, config: RouterConfig | None = None) -> None:
        self.config = config or load_config()
        self._providers: dict[str, Provider] = {}
        self._stats: dict[str, ProviderStats] = {}
        self._usage_lock = asyncio.Lock()
        for name in self.config.providers.chain:
            self._register(name)
        # vision-only paid slot (user-approved, docs/PAID_USAGE.md 2026-10-06):
        # daily USD counter — state under <repo_root>/run/ (gitignored runtime)
        self._vision_spend = DailySpend(
            self.config.repo_root / "run" / "vision_paid_daily.json",
            self.config.providers.vision_paid_daily_cap_usd,
        )
        self._local_transcriber: Callable[..., Awaitable[dict[str, Any]]] | None = None

    # ------------------------------------------------------------------ #
    # registry / stats
    # ------------------------------------------------------------------ #
    def _register(self, name: str) -> Provider:
        prov = self._providers.get(name)
        if prov is None:
            prov = build_provider(name, self.config)
            self._providers[name] = prov
        self._stats.setdefault(name, ProviderStats(
            limiter=RateLimiter(max_calls=self.config.providers.rpm_for(name)),
            budget=TokenBudget(max_tokens=self.config.providers.tpm_for(name)),
        ))
        return prov

    def _chain(self) -> list[Provider]:
        """Profile chain with the Go/paid gates applied (INTERFACES §a)."""
        out: list[Provider] = []
        for name in self.config.providers.chain:
            if name == "go" and not self.config.providers.allow_go_runtime:
                continue
            out.append(self._register(name))
        return out

    def _vision_chain(self) -> list[Provider]:
        """Vision chain = `_chain()` + the paid vision slot as LAST resort.

        The user-approved paid slot never displaces free capacity: it is only
        consulted when no free-chain provider can serve vision, and only when
        `providers.allow_vision_paid` is on. It is absent from `_chain()`, so
        chat/tools/STT can never reach it.
        """
        chain = list(self._chain())
        if self.config.providers.allow_vision_paid:
            chain.append(self._register("go_vision"))
        return chain

    def _stats_for(self, name: str) -> ProviderStats:
        return self._stats.setdefault(name, ProviderStats(
            limiter=RateLimiter(max_calls=self.config.providers.rpm_for(name)),
            budget=TokenBudget(max_tokens=self.config.providers.tpm_for(name)),
        ))

    # ------------------------------------------------------------------ #
    # gates (privacy / profile)
    # ------------------------------------------------------------------ #
    def _gate_cloud(self, operation: str) -> None:
        """Private Mode disables ALL cloud calls (PROTOCOL §7/§11)."""
        if is_private_mode():
            raise RouterError(
                "cloud call refused: Private Mode is on",
                code="E_OFFLINE", reason="private_mode",
                detail="Private Mode is on — cloud calls are off.",
            )

    def _gate_vision_profile(self) -> None:
        if self.config.vision.provider != "cloud":
            raise RouterError(
                "cloud vision disabled by profile",
                code="E_OFFLINE", reason="cloud_vision_disabled",
                detail="Local-only vision is configured; cloud vision is off.",
            )

    def _gate_blocklist(self, operation: str) -> None:
        """Foreground-window blocklist (PROTOCOL §7(2) / ARCHITECTURE §4).

        Vision: ALWAYS refused on a blocklisted window. Chat: refused too
        when `router.block_chat_on_blocklist` is set (default true — under
        profile `cloud_temp` there is no local model to fall back to, so
        refusing is the only safe action).
        """
        hit = blocklist_hit(self.config.privacy.blocklist_apps)
        if not hit:
            return
        if operation == "chat" and not self.config.providers.block_chat_on_blocklist:
            return
        raise RouterError(
            f"foreground window matches blocklist ({hit})",
            code="E_OFFLINE", reason="blocked_window",
            detail="Blocked window in focus — staying local only.",
        )

    # ------------------------------------------------------------------ #
    # admission control (circuit / budgets / key / gate) → RouterError
    # ------------------------------------------------------------------ #
    def _admit(self, provider: Provider, estimate: int = 1) -> None:
        now = time.monotonic()
        stats = self._stats_for(provider.name)
        if stats.circuit.can_proceed(now) is False:
            raise RouterError("circuit open", code="E_OFFLINE",
                              provider=provider.name, reason="circuit_open")
        if now < stats.cooldown_until:
            raise RouterError("rate-limit cooldown active", code="E_PROVIDER_429",
                              provider=provider.name, reason="cooldown")
        if not provider.has_key():
            raise RouterError("missing API key", code="E_PROVIDER_AUTH",
                              provider=provider.name, reason="missing_key")
        if provider.gated and not self.config.providers.allow_go_runtime:
            raise RouterError("provider gated off by config", code="E_OFFLINE",
                              provider=provider.name, reason="gated")
        if stats.limiter is not None and not stats.limiter.allow(now):
            raise RouterError("local RPM budget exhausted", code="E_PROVIDER_429",
                              provider=provider.name, reason="local_rpm_budget",
                              detail="Too many requests this minute.")
        if stats.budget is not None and not stats.budget.allow(now, estimate):
            raise RouterError("local TPM budget exhausted", code="E_PROVIDER_429",
                              provider=provider.name, reason="local_tpm_budget",
                              detail="Token budget for this minute is used up.")

    def _note_rate_limit(self, provider: str, rate_limit: dict[str, Any] | None,
                         retry_after: float | None = None) -> None:
        """Honor provider rate-limit headers (Wave 2 task 3)."""
        stats = self._stats_for(provider)
        now = time.monotonic()
        if retry_after is not None:
            stats.cooldown_until = max(stats.cooldown_until, now + retry_after)
        if not isinstance(rate_limit, dict):
            return
        remaining = rate_limit.get("remaining_requests")
        reset_s = rate_limit.get("reset_requests_s")
        if remaining is not None and float(remaining) <= 0:
            wait = float(reset_s) if reset_s else 30.0
            stats.cooldown_until = max(stats.cooldown_until, now + min(wait, 120.0))
        rem_tokens = rate_limit.get("remaining_tokens")
        reset_tokens = rate_limit.get("reset_tokens_s")
        if rem_tokens is not None and float(rem_tokens) <= 0:
            wait = float(reset_tokens) if reset_tokens else 30.0
            stats.cooldown_until = max(stats.cooldown_until, now + min(wait, 120.0))

    # ------------------------------------------------------------------ #
    # retry / backoff
    # ------------------------------------------------------------------ #
    def _backoff(self, attempt: int, retry_after: float | None) -> float:
        """Exponential backoff with ±20% jitter; honors Retry-After when short."""
        p = self.config.providers
        if retry_after is not None:
            if retry_after > p.backoff_cap_s:
                return retry_after  # caller turns this into a failover cooldown
            return max(0.0, retry_after * random.uniform(0.9, 1.1))
        delay = min(p.backoff_cap_s, p.backoff_base_s * (2 ** max(0, attempt - 1)))
        return delay * random.uniform(0.8, 1.2)

    async def _call_provider(
        self,
        provider: Provider,
        role: str,
        purpose: str,
        call: Callable[[Any], Awaitable[ChatResult]],
        *,
        require_capability: str | None = None,
        fixed_model: str | None = None,
        estimate: int = 100,
    ) -> tuple[Any, ChatResult]:
        """Single-provider attempt loop: retries → failover decision.

        Returns (model, ChatResult). Raises the LAST RouterError.
        `fixed_model` pins an exact model id (legacy `complete()` seam);
        `estimate` is the input-token guess used for the TPM budget gate.
        """
        p = self.config.providers
        stats = self._stats_for(provider.name)
        estimate = max(1, int(estimate))
        last: RouterError | None = None
        attempt = 0
        model = None
        while attempt <= p.max_retries:
            attempt += 1
            # admission FIRST: missing key / open circuit / budgets must never
            # cost a discovery round-trip or a request
            self._admit(provider, estimate=estimate)
            try:
                if fixed_model:
                    model = ModelRef(fixed_model, provider.name)
                else:
                    model = await provider.pick(role,
                                                require_capability=require_capability)
            except RouterError as e:
                last = e
                if e.reason in SKIP_REASONS or e.code not in _RETRYABLE:
                    raise
                await asyncio.sleep(self._backoff(attempt, e.retry_after))
                continue
            if model is None:
                raise RouterError("no model for role", code="E_OFFLINE",
                                  provider=provider.name, reason="no_model",
                                  detail="No model available for this request.")
            if model.paid and not provider.paid_models_allowed:
                raise RouterError("paid model gated off", code="E_OFFLINE",
                                  provider=provider.name, reason="gated")
            try:
                start = time.monotonic()
                result = await asyncio.wait_for(
                    call(model), timeout=p.request_timeout_s,
                )
            except asyncio.TimeoutError as e:
                last = RouterError("provider timeout", code="E_TIMEOUT",
                                   provider=provider.name, model=getattr(model, "id", None))
                stats.last_error = str(last)
                if attempt <= p.max_retries:
                    await asyncio.sleep(self._backoff(attempt, None))
                    continue
                raise last from e
            except RouterError as e:
                last = e
                stats.last_error = str(e)
                if e.reason == "model_not_found":
                    # vanished model → re-select (ARCHITECTURE §4)
                    provider.invalidate()
                    continue
                if e.reason in SKIP_REASONS:
                    raise
                if e.code in _RETRYABLE and attempt <= p.max_retries:
                    if e.retry_after is not None and e.retry_after > p.backoff_cap_s:
                        # provider says "wait long" → honor it as a cooldown and
                        # let the chain take over now (headers honored, no stall)
                        stats.cooldown_until = time.monotonic() + e.retry_after
                        e.reason = "cooldown"
                        raise
                    await asyncio.sleep(self._backoff(attempt, e.retry_after))
                    continue
                raise
            except Exception as e:  # noqa: BLE001 — normalize to RouterError
                last = RouterError(redact_secrets(str(e)), code="E_PROVIDER_5XX",
                                   provider=provider.name,
                                   model=getattr(model, "id", None))
                stats.last_error = str(last)
                if attempt <= p.max_retries:
                    await asyncio.sleep(self._backoff(attempt, None))
                    continue
                raise last from e

            # success accounting
            stats.circuit.record_success()
            elapsed_ms = (time.monotonic() - start) * 1000.0
            tokens = (result.estimated_tokens()
                      if isinstance(result, ChatResult) else 0) or estimate
            if stats.budget is not None:
                stats.budget.record(time.monotonic(), tokens)
            self._note_rate_limit(provider.name, getattr(result, "rate_limit", None))
            stats.last_error = None
            if isinstance(result, ChatResult):
                result.usage.setdefault("input", 0)
                result.usage.setdefault("output", 0)
            return model, result
        raise last or RouterError("provider failed", code="E_INTERNAL",
                                  provider=provider.name)

    # ------------------------------------------------------------------ #
    # failover across the chain
    # ------------------------------------------------------------------ #
    async def _with_failover(
        self,
        *,
        role: str,
        purpose: str,
        call: Callable[[Provider, Any], Awaitable[ChatResult]],
        require_capability: str | None = None,
        estimate: int = 100,
    ) -> tuple[str, str, ChatResult]:
        errors: list[RouterError] = []
        for provider in self._chain():
            try:
                model, result = await self._call_provider(
                    provider, role, purpose,
                    lambda m, _p=provider: call(_p, m),
                    require_capability=require_capability,
                    estimate=estimate,
                )
            except RouterError as e:
                errors.append(e)
                stats = self._stats_for(provider.name)
                stats.last_error = str(e)
                if e.reason not in SKIP_REASONS:
                    stats.circuit.record_failure(time.monotonic())
                continue
            return provider.name, model.id, result
        raise self._exhausted(errors)

    def _exhausted(self, errors: list[RouterError]) -> RouterError:
        if not errors:
            # chain empty or every provider gated off (e.g. `go` with
            # allow_go_runtime=false) — still a §10 code, never a crash
            return RouterError(
                "no provider available (chain empty or gated off)",
                code="E_OFFLINE", reason="chain_exhausted",
                detail="No model service is reachable right now.",
            )
        codes = [e.code for e in errors]
        code = aggregate_code(codes)
        detail_map = {
            "E_PROVIDER_429": "Rate limited everywhere — try again shortly.",
            "E_PROVIDER_AUTH": "Model service rejected the API key.",
            "E_OFFLINE": "No model service is reachable right now.",
        }
        last = errors[-1] if errors else None
        reason = "chain_exhausted"
        if last is not None and last.reason in ("private_mode", "blocked_window",
                                                "cloud_vision_disabled"):
            reason = last.reason
        joined = "; ".join(str(e) for e in errors[:4])[:400] or "no providers in chain"
        return RouterError(joined, code=code, reason=reason,
                           detail=detail_map.get(code))

    # ------------------------------------------------------------------ #
    # FACADE — chat (INTERFACES §a)
    # ------------------------------------------------------------------ #
    def chat(self, messages: list[dict[str, Any]],
             tools: list[dict[str, Any]] | None = None,
             stream: bool = False,
             purpose: str = "chat"):
        """Non-streaming: `await chat(...)` → dict. Streaming:
        `async for ev in chat(..., stream=True)` → deltas + final frame."""
        if stream:
            return self._chat_stream(messages, tools, purpose)
        return self._chat(messages, tools, purpose)

    async def _chat(self, messages, tools, purpose) -> dict[str, Any]:
        start = time.monotonic()
        self._gate_cloud("chat")
        self._gate_blocklist("chat")
        msgs = redact_messages(messages)
        if not isinstance(msgs, list) or not msgs:
            raise RouterError("messages must be a non-empty list",
                              code="E_BAD_MSG", reason="bad_messages")
        role = self._role_for(purpose, tools)
        provider, model, result = await self._with_failover(
            role=role, purpose=purpose,
            call=lambda p, m: p.chat(m, msgs, tools=tools,
                                     timeout=self.config.providers.request_timeout_s),
            require_capability="tools" if tools else None,
            estimate=estimate_input_tokens(msgs, tools),
        )
        latency = (time.monotonic() - start) * 1000.0
        await self._log_usage(provider, model, purpose, result.usage,
                              Outcome.SUCCESS, None, latency_ms=latency)
        return {
            "text": result.text,
            "tool_calls": result.tool_calls,
            "finish": result.finish if result.tool_calls else (result.finish or "stop"),
            "provider": provider,
            "model": model,
            "usage": {"input": int(result.usage.get("input", 0)),
                      "output": int(result.usage.get("output", 0))},
        }

    async def _chat_stream(self, messages, tools, purpose) -> AsyncIterator[dict[str, Any]]:
        self._gate_cloud("chat")
        self._gate_blocklist("chat")
        msgs = redact_messages(messages)
        if not isinstance(msgs, list) or not msgs:
            raise RouterError("messages must be a non-empty list",
                              code="E_BAD_MSG", reason="bad_messages")
        role = self._role_for(purpose, tools)
        errors: list[RouterError] = []
        for provider in self._chain():
            model = None
            try:
                model = await provider.pick(
                    role, require_capability="tools" if tools else None)
                if model is None:
                    raise RouterError("no model for role", code="E_OFFLINE",
                                      provider=provider.name, reason="no_model")
                if model.paid and not self.config.providers.allow_paid_runtime:
                    raise RouterError("paid model gated off", code="E_OFFLINE",
                                      provider=provider.name, reason="gated")
                self._admit(provider, estimate=estimate_input_tokens(msgs, tools))
            except RouterError as e:
                errors.append(e)
                if e.reason not in SKIP_REASONS:
                    self._stats_for(provider.name).circuit.record_failure(
                        time.monotonic())
                continue

            emitted = False
            saw_final = False
            start = time.monotonic()
            usage = {"input": 0, "output": 0}
            try:
                gen = provider.chat_stream(
                    model, msgs, tools=tools,
                    timeout=self.config.providers.stream_timeout_s,
                )
                async for ev in gen:
                    if "finish" in ev:
                        saw_final = True
                        usage.update(ev.get("usage") or {})
                        yield {
                            "finish": ev.get("finish", "stop"),
                            "tool_calls": ev.get("tool_calls") or [],
                            "provider": provider.name,
                            "model": model.id,
                            "usage": dict(usage),
                        }
                    else:
                        emitted = True
                        yield {"delta": ev.get("delta", "")}
                if not saw_final:
                    # a provider that closed the stream early still owes the
                    # caller one final frame (INTERFACES §a stream contract)
                    yield {
                        "finish": "stop",
                        "tool_calls": [],
                        "provider": provider.name,
                        "model": model.id,
                        "usage": dict(usage),
                    }
            except RouterError as e:
                stats = self._stats_for(provider.name)
                stats.last_error = str(e)
                if not emitted:
                    errors.append(e)
                    if e.reason not in SKIP_REASONS:
                        stats.circuit.record_failure(time.monotonic())
                    continue  # failover before the first delta
                # mid-stream failure: surface it, the loop maps it to a job error
                await self._log_usage(provider.name, model.id, purpose, usage,
                                      Outcome.FAILED, e.code,
                                      latency_ms=(time.monotonic() - start) * 1000)
                raise
            except Exception as e:  # noqa: BLE001
                err = RouterError(redact_secrets(str(e)), code="E_PROVIDER_5XX",
                                  provider=provider.name, model=model.id)
                if not emitted:
                    errors.append(err)
                    self._stats_for(provider.name).circuit.record_failure(
                        time.monotonic())
                    continue
                raise err from e

            stats = self._stats_for(provider.name)
            stats.circuit.record_success()
            stats.last_error = None
            tokens = usage.get("input", 0) + usage.get("output", 0)
            if stats.budget is not None and tokens:
                stats.budget.record(time.monotonic(), tokens)
            await self._log_usage(provider.name, model.id, purpose, usage,
                                  Outcome.SUCCESS, None,
                                  latency_ms=(time.monotonic() - start) * 1000)
            return
        raise self._exhausted(errors)

    def _role_for(self, purpose: str, tools: list[dict[str, Any]] | None) -> str:
        if tools:
            return self.config.providers.purpose_roles.get("tool", "strong")
        return self.config.providers.purpose_roles.get(purpose, "fast")

    # ------------------------------------------------------------------ #
    # FACADE — vision (INTERFACES §a, PROTOCOL §7 gates)
    # ------------------------------------------------------------------ #
    async def vision(self, image: Any, question: str,
                     purpose: str = "vision") -> dict[str, Any]:
        self._gate_cloud("vision")
        self._gate_vision_profile()
        # caller (computer-use/brain-core) pre-gates: profile, redaction of
        # extracted text, no logging. The router STILL re-checks the two gates
        # that are cheap and fatal if skipped: blocklist + Private Mode.
        self._gate_blocklist("vision")
        log.debug("vision request: %s", describe_image(image))

        data, mime = await _encode_image(image)
        max_bytes = self.config.vision.max_bytes
        if len(data) > max_bytes:
            raise RouterError(
                f"image too large ({len(data)} > {max_bytes} bytes) — "
                "downscale before sending (config vision.max_px/quality)",
                code="E_BAD_MSG", reason="image_too_large",
            )
        q = redact_secrets(question or "")
        b64 = base64.b64encode(data).decode("ascii")

        # free chain first; the paid slot is the LAST resort and is charged to
        # the daily cap (user approval, docs/PAID_USAGE.md)
        spend = self._vision_spend
        price = self.config.providers.vision_paid_price_per_mtok
        errors: list[RouterError] = []
        cap_blocked = False
        for provider in self._vision_chain():
            if provider.name == "go_vision" and spend.exhausted:
                # HARD STOP (vision_paid_daily_cap_usd): skip the paid slot
                cap_blocked = True
                errors.append(RouterError(
                    "vision daily cap reached", code="E_OFFLINE",
                    provider=provider.name, reason="vision_paid_cap",
                    detail="Vision daily cap reached — image analysis "
                           "resumes tomorrow.",
                ))
                self._alert_vision_cap()
                continue
            started = time.monotonic()
            try:
                model, result = await self._call_provider(
                    provider, "vision", purpose,
                    lambda m, _p=provider: _p.vision(
                        m, b64, mime, q,
                        timeout=self.config.providers.request_timeout_s),
                    require_capability="vision",
                    estimate=1500,  # rough vision token guess for TPM budget
                )
            except RouterError as e:
                errors.append(e)
                stats = self._stats_for(provider.name)
                stats.last_error = str(e)
                if e.reason not in SKIP_REASONS:
                    stats.circuit.record_failure(time.monotonic())
                continue
            if provider.name == "go_vision":
                cost = estimate_cost_usd(result.usage, price, result.cost_usd)
                total, crossed = spend.record(cost, model.id)
                log.debug("vision paid slot: +$%.6f -> $%.6f/$%.2f (%s)",
                          cost, total, spend.cap_usd, model.id)
                if crossed:
                    self._alert_vision_cap()
            latency = (time.monotonic() - started) * 1000.0
            await self._log_usage(provider.name, model.id, purpose,
                                  result.usage, Outcome.SUCCESS, None,
                                  latency_ms=latency)
            return {"text": result.text, "provider": provider.name,
                    "model": model.id}

        if cap_blocked and all(
            e.reason in ("no_model", "chain_exhausted", "vision_paid_cap",
                         "circuit_open", "missing_key", "cooldown",
                         "local_rpm_budget", "local_tpm_budget")
            for e in errors
        ):
            # nothing free could serve AND the paid slot is capped out →
            # the user-facing answer is the cap, not a generic outage
            raise RouterError(
                "vision daily cap reached — no free vision model available",
                code="E_OFFLINE", reason="vision_paid_cap",
                detail="Vision daily cap reached — image analysis "
                       "resumes tomorrow.",
            )
        raise self._exhausted(errors)

    def _alert_vision_cap(self) -> None:
        """coord attention 'vision daily cap hit' — once per day, never raises."""
        if self._vision_spend.alerted_today:
            return
        self._vision_spend.mark_alerted()
        spend_mod.notify_attention(
            f"vision daily cap hit (${self.config.providers.vision_paid_daily_cap_usd:.2f}/day) "
            "— vision() refusing paid calls until tomorrow"
        )

    # ------------------------------------------------------------------ #
    # FACADE — transcribe (Groq Whisper; local seam for profile local)
    # ------------------------------------------------------------------ #
    def set_local_transcriber(
        self, fn: Callable[..., Awaitable[dict[str, Any]]] | None
    ) -> None:
        """Voice lane registers its local STT behind this seam (INTERFACES §a)."""
        self._local_transcriber = fn

    async def transcribe(self, audio: bytes, language: str | None = None) -> dict[str, Any]:
        self._gate_cloud("transcribe")
        if not isinstance(audio, (bytes, bytearray)) or not audio:
            raise RouterError("audio must be non-empty bytes", code="E_BAD_MSG",
                              reason="bad_audio")
        audio = bytes(audio)

        if self.config.voice.stt_engine == "local":
            if self._local_transcriber is None:
                raise RouterError("local STT not registered", code="E_LOCAL_DOWN",
                                  reason="stt_not_available",
                                  detail="Local speech-to-text is not available.")
            out = await self._local_transcriber(audio, language)
            return {"text": str((out or {}).get("text", "")).strip(),
                    "rtf": (out or {}).get("rtf")}

        errors: list[RouterError] = []
        filename = _audio_filename(audio)
        mime = guess_audio_format(audio, filename)
        for provider in self._chain():
            # No static capability pre-check here: which provider can do STT is
            # decided by live discovery (role "stt" → audio-capable/whisper
            # model); providers without one skip out via the no_model path.
            start = time.monotonic()
            try:
                model, result = await self._call_provider(
                    provider, "stt", "stt",
                    lambda m, _p=provider: _p.transcribe(
                        m, audio, filename, mime,
                        language or self.config.voice.stt_language or None,
                        timeout=self.config.providers.request_timeout_s,
                    ),
                    require_capability="stt",
                )
            except RouterError as e:
                errors.append(e)
                stats = self._stats_for(provider.name)
                stats.last_error = str(e)
                if e.reason not in SKIP_REASONS:
                    stats.circuit.record_failure(time.monotonic())
                continue
            elapsed = time.monotonic() - start
            await self._log_usage(provider.name, model.id, "stt",
                                  {"input": 0, "output": 0}, Outcome.SUCCESS, None,
                                  latency_ms=elapsed * 1000)
            text = str((result.get("text") if isinstance(result, dict)
                        else result.text) or "").strip()
            duration = _wav_duration(audio)
            rtf = (elapsed / duration) if duration else None
            return {"text": text, "rtf": rtf}
        raise self._exhausted(errors)

    # ------------------------------------------------------------------ #
    # FACADE — health (INTERFACES §a)
    # ------------------------------------------------------------------ #
    async def health(self) -> dict[str, Any]:
        providers: dict[str, Any] = {}
        if is_private_mode():
            # Private Mode: no cloud egress AT ALL — report from cache only.
            for provider in self._vision_chain():
                cached = provider.cached_models
                providers[provider.name] = {
                    "ok": bool(cached),
                    "models": len(cached),
                    "last_error": ("private mode: probe skipped" if cached
                                   else "private mode: no cached models"),
                }
            return {"ok": bool(providers) and any(
                p["ok"] for p in providers.values()), "providers": providers}
        for provider in self._vision_chain():
            providers[provider.name] = await provider.health()
        out = {"ok": any(p.get("ok") for p in providers.values()),
               "providers": providers}
        if self.config.providers.allow_vision_paid:
            # paid-slot budget for supervisors/status consumers (no egress)
            out["vision_paid"] = self._vision_spend.snapshot()
        return out

    async def health_check(self) -> dict[str, bool]:
        """Legacy shape used by older code/tests: {name: ok}."""
        full = await self.health()
        return {name: bool(info.get("ok"))
                for name, info in full["providers"].items()}

    # ------------------------------------------------------------------ #
    # legacy seam (brain/llm.py — brain-core's side of the boundary)
    # ------------------------------------------------------------------ #
    async def acquire_model(self, task_kind: str | None = None) -> tuple[str, str]:
        purpose = task_kind or "chat"
        role = self._role_for(purpose, None)
        errors: list[RouterError] = []
        for provider in self._chain():
            try:
                self._admit(provider, estimate=64)
                model = await provider.pick(role)
            except RouterError as e:
                errors.append(e)
                continue
            if model is None:
                errors.append(RouterError("no model", code="E_OFFLINE",
                                          provider=provider.name, reason="no_model"))
                continue
            if model.paid and not self.config.providers.allow_paid_runtime:
                continue
            return provider.name, model.id
        raise ProviderUnavailable(
            "all providers exhausted: " + "; ".join(str(e) for e in errors[:4])
        )

    async def complete(self, provider: str, model: str, prompt: str | None = None,
                       task_kind: str | None = None) -> CallResult:
        """Legacy single-provider completion — NEVER raises (llm.plan contract)."""
        start = time.monotonic()
        purpose = task_kind or "chat"
        try:
            self._gate_cloud("chat")
        except RouterError as e:
            return CallResult(provider=provider, model=model, ok=False,
                              outcome=Outcome.UNAVAILABLE, error=str(e),
                              error_code=e.code)
        prov = self._providers.get(provider) or self._register(provider)
        now = datetime.now()
        system = SYSTEM_PROMPT + (
            f"\nCurrent local date/time on the user's machine: {now:%A}, "
            f"{now:%B %d, %Y %H:%M}. You HAVE clock/calendar access through "
            f"this line — answer time and date questions directly."
        )
        msgs = redact_messages([
            {"role": "system", "content": system},
            {"role": "user", "content": prompt or ""},
        ])

        async def _call(m: Any) -> ChatResult:
            return await prov.chat(m, msgs, tools=None,
                                   timeout=self.config.providers.request_timeout_s)

        try:
            _, result = await self._call_provider(prov, self._role_for(purpose, None),
                                                  purpose, _call, fixed_model=model)
        except RouterError as e:
            self._stats_for(provider).last_error = str(e)
            return CallResult(
                provider=provider, model=model, ok=False,
                outcome=Outcome.UNAVAILABLE if e.code == "E_OFFLINE" else Outcome.FAILED,
                error=str(e)[:300], error_code=e.code,
                latency_ms=(time.monotonic() - start) * 1000,
            )
        await self._log_usage(provider, model, purpose, result.usage,
                              Outcome.SUCCESS, None,
                              latency_ms=(time.monotonic() - start) * 1000)
        return CallResult(
            provider=provider, model=model, ok=True, text=result.text,
            tool_calls=result.tool_calls, finish=result.finish,
            tokens_input=int(result.usage.get("input", 0)),
            tokens_output=int(result.usage.get("output", 0)),
            latency_ms=(time.monotonic() - start) * 1000,
            outcome=Outcome.SUCCESS,
        )

    # ------------------------------------------------------------------ #
    # usage log (gitignored runtime data: brain/router/usage.jsonl)
    # ------------------------------------------------------------------ #
    async def _log_usage(self, provider: str, model: str, purpose: str,
                         usage: dict[str, Any], outcome: Outcome,
                         error_code: str | None,
                         latency_ms: float = 0.0) -> None:
        ev = UsageEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            provider=provider,
            model=str(model),
            tokens_input=int((usage or {}).get("input", 0)),
            tokens_output=int((usage or {}).get("output", 0)),
            latency_ms=round(latency_ms, 2),
            outcome=outcome,
            task_kind=purpose,
            error_code=error_code,
        )
        await self.report_usage(ev)

    async def report_usage(self, event: UsageEvent) -> None:
        line = _usage_json(event)
        path: Path = self.config.usage_log_path
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            async with self._usage_lock:
                await asyncio.to_thread(_append_line, path, line)
        except OSError:
            pass  # usage accounting must never break a call

    # ------------------------------------------------------------------ #
    # lifecycle
    # ------------------------------------------------------------------ #
    async def start(self) -> None:  # kept for API parity with older code
        return None

    async def shutdown(self) -> None:
        return None


class ModelRef:
    """Minimal ModelInfo stand-in when the caller pinned an exact model id."""

    def __init__(self, model_id: str, provider: str) -> None:
        self.id = model_id
        self.provider = provider
        self.free = True
        self.paid = False
        self.capabilities = frozenset()


# --------------------------------------------------------------------------- #
# image / audio helpers (never log the payload)
# --------------------------------------------------------------------------- #
async def _encode_image(image: Any) -> tuple[bytes, str]:
    if isinstance(image, (bytes, bytearray)):
        data = bytes(image)
        return data, guess_image_mime(data)
    if isinstance(image, (str, Path)):
        path = Path(image)

        def _read() -> bytes:
            return path.read_bytes()

        data = await asyncio.to_thread(_read)
        return data, guess_image_mime(data, path.name)
    raise RouterError(f"unsupported image type ({type(image).__name__})",
                      code="E_BAD_MSG", reason="bad_image")


def _audio_filename(audio: bytes) -> str:
    if audio[:4] == b"RIFF" and audio[8:12] == b"WAVE":
        return "audio.wav"
    if audio[:4] == b"\x1aE\xdf\xa3":
        return "audio.webm"
    if audio[:3] == b"ID3" or audio[:2] == b"\xff\xfb":
        return "audio.mp3"
    return "audio.raw"


def _wav_duration(audio: bytes) -> float | None:
    """Seconds from a PCM WAV header (None for anything else)."""
    import struct
    if len(audio) < 44 or audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
        return None
    try:
        idx = audio.find(b"fmt ")
        if idx < 0:
            return None
        _chunk_size = struct.unpack("<I", audio[idx + 4:idx + 8])[0]
        _audio_fmt, channels, rate, _brate, block_align, bits = struct.unpack(
            "<HHIIHH", audio[idx + 8:idx + 24])
        if _audio_fmt != 1 or channels == 0 or rate == 0 or bits == 0:
            return None
        didx = audio.find(b"data")
        if didx < 0:
            return None
        data_size = struct.unpack("<I", audio[didx + 4:didx + 8])[0]
        bytes_per_sec = rate * channels * bits // 8
        if bytes_per_sec <= 0:
            return None
        return round(data_size / bytes_per_sec, 3)
    except (struct.error, ValueError):
        return None


def _usage_json(ev: UsageEvent) -> str:
    import json
    data = asdict(ev)
    data["outcome"] = ev.outcome.value if isinstance(ev.outcome, Outcome) else str(ev.outcome)
    return json.dumps(data, ensure_ascii=False)


def _append_line(path: Path, line: str) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


# --------------------------------------------------------------------------- #
# module-level singleton (brain/llm.py and other lanes use these)
# --------------------------------------------------------------------------- #
_router: Router | None = None


def init_router(config: RouterConfig | None = None) -> Router:
    global _router
    if _router is None:
        _router = Router(config)
    return _router


def get_router() -> Router:
    global _router
    if _router is None:
        _router = Router()
    return _router


def reset_router() -> None:
    """Drop the singleton (tests / profile switches)."""
    global _router
    _router = None


async def shutdown_router() -> None:
    global _router
    if _router is not None:
        await _router.shutdown()
        _router = None


async def acquire_model(task_kind: str | None = None) -> tuple[str, str]:
    return await get_router().acquire_model(task_kind=task_kind)


async def complete(provider: str, model: str, prompt: str | None = None,
                   task_kind: str | None = None) -> CallResult:
    return await get_router().complete(provider, model, prompt=prompt,
                                       task_kind=task_kind)


async def report_usage(event: UsageEvent) -> None:
    await get_router().report_usage(event)

"""Provider router for Raphael (Zen → Go → Ollama)."""
from __future__ import annotations

from .core import (
    CallResult,
    Outcome,
    ProviderError,
    ProviderUnavailable,
    Router,
    RouterConfig,
    UsageEvent,
    acquire_model,
    complete,
    get_router,
    init_router,
    report_usage,
    shutdown_router,
)

__all__ = [
    "CallResult",
    "Outcome",
    "ProviderError",
    "ProviderUnavailable",
    "Router",
    "RouterConfig",
    "UsageEvent",
    "acquire_model",
    "complete",
    "get_router",
    "init_router",
    "report_usage",
    "shutdown_router",
]

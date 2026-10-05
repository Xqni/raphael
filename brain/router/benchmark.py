"""Benchmark harness for latency/throughput per provider."""
from __future__ import annotations

import asyncio
import json
import statistics
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
BENCHMARK_PATH = REPO_ROOT / "brain" / "router" / "benchmark_ranking.json"
DEFAULT_TARGETS = {
    "latency_ms_p50": 150.0,
    "latency_ms_p90": 300.0,
    "throughput_rps": 10.0,
}


@dataclass
class BenchmarkResult:
    provider: str
    model: str
    latency_ms_p50: float
    latency_ms_p90: float
    latency_ms_p95: float
    throughput_rps: float
    samples: int


def _write_ranking(results: list[BenchmarkResult], targets: dict[str, float] | None = None) -> None:
    data: dict[str, Any] = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "targets": targets or DEFAULT_TARGETS,
        "results": [asdict(r) for r in results],
    }
    BENCHMARK_PATH.parent.mkdir(parents=True, exist_ok=True)
    BENCHMARK_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


async def _run_provider(provider: str, model: str, samples: int = 20, delay_s: float = 0.01) -> BenchmarkResult:
    latencies: list[float] = []
    start_total = time.monotonic()
    for _ in range(samples):
        s = time.monotonic()
        await asyncio.sleep(0.001)  # simulate minimal work
        latencies.append((time.monotonic() - s) * 1000.0)
        if delay_s > 0:
            await asyncio.sleep(delay_s)
    duration_s = time.monotonic() - start_total
    if duration_s <= 0:
        throughput_rps = float(samples)
    else:
        throughput_rps = float(samples) / duration_s
    latencies_sorted = sorted(latencies)
    def p(n: int) -> float:
        if not latencies_sorted:
            return 0.0
        idx = min(len(latencies_sorted) - 1, max(0, int(round(n / 100.0 * (len(latencies_sorted) - 1)))))
        return latencies_sorted[idx]
    return BenchmarkResult(
        provider=provider,
        model=model,
        latency_ms_p50=p(50),
        latency_ms_p90=p(90),
        latency_ms_p95=p(95),
        throughput_rps=throughput_rps,
        samples=samples,
    )


async def run_benchmark(samples: int = 20) -> list[BenchmarkResult]:
    results: list[BenchmarkResult] = []
    # Mock runs; in practice would call real providers behind mocks in tests
    results.append(await _run_provider("zen_free", "mimo-v2.6-flash-free", samples=samples))
    results.append(await _run_provider("ollama", "qwen3.5:4b", samples=samples))
    _write_ranking(results)
    return results


def print_comparison(results: list[BenchmarkResult], targets: dict[str, float] | None = None) -> str:
    t = targets or DEFAULT_TARGETS
    lines = ["Benchmark comparison vs targets:"]
    for r in results:
        lines.append(
            f"- {r.provider}/{r.model}: p50={r.latency_ms_p50:.1f}ms (t={t['latency_ms_p50']:.1f}), "
            f"p90={r.latency_ms_p90:.1f}ms (t={t['latency_ms_p90']:.1f}), rps={r.throughput_rps:.2f} (t={t['throughput_rps']:.2f})"
        )
    return "\n".join(lines)
